"""Verify the real shared storage with rollback-only test records and fake SMTP."""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta
from email.utils import parseaddr
import os
from unittest.mock import patch
from uuid import uuid4

from agent_runtime import INDIA_TZ
from run_followup_worker import load_config
from followup_service import _connect
import visit_service as visits
import visit_journey as journeys
import crm_service as crm
import visit_attendance as attendance
import visit_whatsapp as whatsapp
import customer_journey as customer
import visit_actions as actions
from crm_whatsapp import visit_message, chat_link


def main():
    config=load_config()
    official='propertynm38@gmail.com'
    if not config.get('DATABASE_URL') or config.get('FOLLOWUP_SMTP_USERNAME','').lower()!=official or parseaddr(config.get('FOLLOWUP_SMTP_FROM',''))[1].lower()!=official:
        raise ValueError('Shared database and official sender settings are required.')
    os.environ['DATABASE_URL']=config['DATABASE_URL']
    config['VISIT_EMAIL_ENABLED']='true'
    # Commit each migration independently so this check does not hold schema
    # locks across unrelated CRM and visit tables while the live app is active.
    for migrate in (journeys.schema,crm.schema,attendance.schema,whatsapp.outbox_schema,customer.schema,actions.schema):
        with _connect() as c:
            if not getattr(c,'shared',False): raise ValueError('Shared PostgreSQL is required.')
            migrate(c)
    with _connect() as c:
        for table in ('property_visit_requests','visit_journeys','visit_email_outbox','crm_leads','crm_activity','crm_deals','crm_tasks','advisor_visit_registers','crm_visit_task_links'):
            row=c.execute('SELECT relrowsecurity FROM pg_class WHERE oid=CAST(? AS regclass)',(table,)).fetchone()
            assert row and row['relrowsecurity'], 'Private table protections missing'
    print('Shared PostgreSQL schemas and private table protections verified.')
    with _connect() as c:
        @contextmanager
        def shared(*args,**kwargs):
            yield c
        try:
            with ExitStack() as stack:
                for module in (visits,journeys,crm,attendance,actions):
                    stack.enter_context(patch.object(module,'_connect',shared))
                # Schema is verified above; avoid reacquiring DDL locks inside the
                # long rollback-only data test while customers use the website.
                for module,name in ((visits,'_schema'),(journeys,'schema'),(crm,'schema'),(attendance,'schema'),(whatsapp,'outbox_schema'),(customer,'schema'),(actions,'schema')):
                    stack.enter_context(patch.object(module,name,lambda c:None))
                smtp=stack.enter_context(patch('visit_journey.smtplib.SMTP'))
                now=datetime.now(INDIA_TZ)
                at=(now+timedelta(days=2)).replace(second=0,microsecond=0)
                marker='hosted-qa-'+uuid4().hex
                visit_id=visits.request_visit(record={'property_id':marker,'title':'Hosted QA property'},
                    user_id=marker,conversation_id=marker,visit_at=at,slot_kind='Custom time',
                    customer_name='Hosted QA',contact_method='WhatsApp',contact_value='+919876543210',
                    consent=True,email_reminders=True,followup_email=official,manual_whatsapp_confirmation=True)
                assert journeys.run_visit_worker(config,now=now,only_visit_id=visit_id)==(0,0)
                visits.update_visit_status(visit_id,'Confirmed')
                row=next(v for v in journeys.owner_journeys() if v['visit_id']==visit_id)
                assert chat_link(row['contact_value'],visit_message(row,'confirmation',now=now)).startswith('https://wa.me/')
                assert journeys.run_visit_worker(config,now=now,only_visit_id=visit_id)==(1,0)
                assert journeys.run_visit_worker(config,now=at-timedelta(hours=1),only_visit_id=visit_id)==(1,0)
                assert journeys.run_visit_worker(config,now=at-timedelta(hours=1),only_visit_id=visit_id)==(0,0)
                after=at+timedelta(hours=2)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(1,0)
                token=c.execute('SELECT token FROM visit_journeys WHERE visit_id=?',(visit_id,)).fetchone()['token']
                journeys.record_response(token,action='feedback',attended='Yes',satisfied='Yes',
                    purchase_intent='Interested',now=after)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(0,0)
                register=attendance.create_register(visit_id,'Release QA advisor')
                attendance.record_agent_attendance(register,visit_id,'No',now=after)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(1,0)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(0,0)
                attendance.record_agent_attendance(register,visit_id,'Yes','Correction verified in QA',now=after)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(1,0)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(0,0)
                row=next(v for v in journeys.owner_journeys() if v['visit_id']==visit_id)
                crm.sync_visits([row])
                summary=crm.journey_summary(row,now=after)
                assert summary['Attendance']=='Visited' and summary['Purchase interest']=='Interested'
                journeys.record_response(token,action='feedback',attended='No',satisfied='Not visited',reason='QA schedule conflict',now=after)
                row=next(v for v in journeys.owner_journeys() if v['visit_id']==visit_id)
                assert crm.journey_summary(row,now=after)['Attendance']=='Did not visit'
                journeys.record_response(token,action='help',assistance='Property agent',details='QA floor plan question',advisor_consent=True,callback_preference='QA preferred time',now=after)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(1,0)
                assert journeys.run_visit_worker(config,now=after,only_visit_id=visit_id)==(0,0)
                assert any(t['visit_id']==visit_id and t['kind']=='assistance' for t in actions.list_actions())
                for call in smtp.return_value.__enter__.return_value.send_message.call_args_list:
                    mail=call.args[0]
                    assert mail['To']==official and parseaddr(mail['From'])[1].lower()==official
                assert smtp.return_value.__enter__.return_value.send_message.call_count==6
                print('Shared booking, manual WhatsApp draft, reminder, feedback, decision email, CRM attendance/interest and duplicate prevention verified. SMTP simulated; no customer messages sent.')
        finally:
            c.execute('ROLLBACK')
    print('Test records rolled back; schema remains ready.')


if __name__=='__main__':
    try: main()
    except Exception as error:
        raise SystemExit('Hosted CRM verification failed: '+type(error).__name__) from None
