from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_runtime import INDIA_TZ
from followup_service import _connect
from visit_service import request_visit, update_visit_status, list_visit_requests
from visit_journey import run_visit_worker, record_response, owner_journeys, set_advisor_status, response_context


class VisitJourneyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'queue.sqlite3'
        self.at=(datetime.now(INDIA_TZ)+timedelta(days=2)).replace(second=0,microsecond=0)
        self.args=dict(record={'property_id':'plot','title':'Test plot'},user_id='u',
            visit_at=self.at,slot_kind='Custom time',customer_name='Test',contact_method='Email',
            contact_value='test@example.com',consent=True,email_reminders=True,db_path=self.db)
        self.id=request_visit(**self.args)
        update_visit_status(self.id,'Confirmed',db_path=self.db)
        self.config=dict(VISIT_EMAIL_ENABLED='true',VISIT_CONFIRMATION_EMAIL_ENABLED='false',FOLLOWUP_SMTP_HOST='smtp.example.com',
            FOLLOWUP_SMTP_USERNAME='sender',FOLLOWUP_SMTP_PASSWORD='test',
            FOLLOWUP_SMTP_FROM='sender@example.com',FOLLOWUP_PUBLIC_URL='https://example.com')
        self.smtp=patch('visit_journey.smtplib.SMTP').start();self.addCleanup(patch.stopall)

    def remind(self):
        return run_visit_worker(self.config,self.db,now=self.at-timedelta(hours=1))

    def test_crm_discovers_booking_before_email_worker_runs(self):
        from crm_service import sync_visits, list_leads
        rows=owner_journeys(self.db)
        self.assertEqual(rows[0]['visit_id'],self.id)
        self.assertEqual(rows[0]['confirmation email'],'Not sent')
        sync_visits(rows,self.db)
        self.assertEqual(list_leads(self.db)[0]['conversation_id'],'visit:'+self.id)
        self.assertEqual(owner_journeys(self.db)[0]['visit_id'],self.id)
        self.smtp.return_value.__enter__.return_value.send_message.assert_not_called()

    def test_confirmation_reminder_and_review_sequence(self):
        self.config['VISIT_CONFIRMATION_EMAIL_ENABLED']='true'
        early=self.at-timedelta(days=1)
        self.assertEqual(run_visit_worker(self.config,self.db,now=early),(1,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=early),(0,0))
        message=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertIn('visit is confirmed',message['Subject'])
        self.assertIn('visit_response=',message.get_body(preferencelist=('plain',)).get_content())
        self.assertEqual(owner_journeys(self.db)[0]['confirmation email'],'sent')
        self.assertEqual(self.remind(),(1,0))
        self.assertEqual(self.remind(),(0,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at+timedelta(hours=2)),(1,0))
        self.assertEqual(self.smtp.return_value.__enter__.return_value.send_message.call_count,3)

    def test_last_hour_confirmation_covers_reminder(self):
        self.config['VISIT_CONFIRMATION_EMAIL_ENABLED']='true'
        self.assertEqual(self.remind(),(1,0))
        self.assertEqual(self.remind(),(0,0))
        message=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertIn('visit is confirmed',message['Subject'])

    def test_confirmation_excludes_requested_cancelled_and_nonconsenting(self):
        self.config['VISIT_CONFIRMATION_EMAIL_ENABLED']='true'
        for status in ('Requested','Cancelled','Confirmed'):
            with _connect(self.db) as c:
                c.execute('UPDATE property_visit_requests SET status=?, visit_email_consent=? WHERE id=?',(status,'' if status=='Confirmed' else 'Yes',self.id))
            self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(days=1)),(0,0))
        self.smtp.assert_not_called()

    def token(self):
        with _connect(self.db) as c:
            return c.execute('SELECT token FROM visit_journeys WHERE visit_id=?',(self.id,)).fetchone()['token']

    def test_default_disabled_and_one_hour_window_and_no_duplicate(self):
        self.assertEqual(run_visit_worker({},self.db),(0,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(hours=2)),(0,0))
        self.assertEqual(self.remind(),(1,0));self.assertEqual(self.remind(),(0,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at),(0,0))
        self.assertEqual(self.smtp.return_value.__enter__.return_value.send_message.call_count,1)

    def test_old_booking_without_new_consent_is_excluded(self):
        with _connect(self.db) as c:
            c.execute("UPDATE property_visit_requests SET visit_email_consent='' WHERE id=?",(self.id,))
        self.assertEqual(self.remind(),(0,0));self.smtp.assert_not_called()

    def test_delivery_test_has_no_dead_live_booking_link(self):
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(hours=1),delivery_test=True),(1,0))
        message=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(message['Subject'],'Namma Veedu email delivery test')
        self.assertNotIn('visit_response=',message.get_body(preferencelist=('plain',)).get_content())
        self.assertIn('not a property visit booking',message.get_body(preferencelist=('plain',)).get_content())

    def test_delivery_test_refuses_live_queue(self):
        with self.assertRaisesRegex(ValueError,'isolated'):
            run_visit_worker(self.config,delivery_test=True)

    def test_yes_welcome_and_no_reply_does_not_cancel(self):
        self.remind();self.assertEqual(list_visit_requests('u',self.db)[0]['status'],'Confirmed')
        reply=record_response(self.token(),action='yes',db_path=self.db,now=self.at-timedelta(minutes=30))
        self.assertIn('welcoming',reply)
        self.assertEqual(owner_journeys(self.db)[0]['attendance'],'Yes')

    def test_no_requires_reason_and_cancels(self):
        self.remind()
        with self.assertRaises(ValueError): record_response(self.token(),action='no',db_path=self.db)
        record_response(self.token(),action='no',reason='Unavailable',db_path=self.db)
        self.assertEqual(list_visit_requests('u',self.db)[0]['status'],'Cancelled')
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at+timedelta(hours=2)),(0,0))

    def test_reschedule_pending_and_old_link_invalid(self):
        self.remind();old=self.token()
        record_response(old,action='reschedule',reason='Busy',visit_at=self.at+timedelta(days=1),db_path=self.db)
        self.assertEqual(list_visit_requests('u',self.db)[0]['status'],'Requested')
        self.assertIsNone(response_context(old,self.db))
        update_visit_status(self.id,'Confirmed',db_path=self.db)
        run_visit_worker(self.config,self.db,now=self.at+timedelta(days=1)-timedelta(hours=1))
        self.assertNotEqual(old,self.token())

    def test_conflicting_reschedule_keeps_original_booking(self):
        self.remind();new_time=self.at+timedelta(days=1)
        other=request_visit(**{**self.args,'user_id':'other','visit_at':new_time})
        update_visit_status(other,'Confirmed',db_path=self.db)
        with self.assertRaises(ValueError):
            record_response(self.token(),action='reschedule',reason='Busy',visit_at=new_time,db_path=self.db)
        self.assertEqual(next(r for r in list_visit_requests('u',self.db) if r['id']==self.id)['visit_at'],self.at.isoformat(timespec='minutes'))

    def test_review_and_advisor_consent_and_interest(self):
        self.remind();now=self.at+timedelta(hours=2)
        self.assertEqual(run_visit_worker(self.config,self.db,now=now),(1,0))
        args=dict(action='feedback',attended='Yes',satisfied='Yes',assistance='Loan advisor',details='Explain eligibility',db_path=self.db,now=now)
        with self.assertRaises(ValueError):record_response(self.token(),**args)
        record_response(self.token(),advisor_consent=True,**args)
        row=owner_journeys(self.db)[0]
        self.assertEqual(row['advisor_status'],'Requested')
        self.assertEqual(row['Purchase interest'],'Strong engagement')
        set_advisor_status(self.id,'Connected',self.db)
        self.assertIn('connection recorded',owner_journeys(self.db)[0]['Evidence'])
        from visit_attendance import create_register, record_agent_attendance
        register=create_register(self.id,'Advisor',self.db)
        record_agent_attendance(register,self.id,'Yes',db_path=self.db,now=now)
        self.assertEqual(run_visit_worker(self.config,self.db,now=now),(1,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=now),(0,0))

    def test_manual_whatsapp_confirmation_with_automatic_emails(self):
        args=dict(self.args, user_id='mixed',record={'property_id':'mixed','title':'Mixed visit'},
                  contact_method='WhatsApp',contact_value='+919876543210',
                  followup_email='mixed@example.com',manual_whatsapp_confirmation=True)
        mixed_id=request_visit(**args)
        update_visit_status(mixed_id,'Confirmed',db_path=self.db)
        with _connect(self.db) as c:
            c.execute("UPDATE property_visit_requests SET visit_email_consent='' WHERE id=?",(self.id,))
            token=c.execute('SELECT token FROM visit_journeys WHERE visit_id=?',(mixed_id,)).fetchone()['token']
        self.config['VISIT_CONFIRMATION_EMAIL_ENABLED']='true'
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(days=1)),(1,0))
        self.assertEqual(self.remind(),(1,0))
        message=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(message['To'],'mixed@example.com')
        self.assertIn('Reminder',message['Subject'])
        self.assertEqual(self.remind(),(0,0))
        after=self.at+timedelta(hours=2)
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(1,0))
        from visit_attendance import create_register, record_agent_attendance
        register=create_register(mixed_id,'Test advisor',self.db)
        record_agent_attendance(register,mixed_id,'No',db_path=self.db,now=after)
        record_response(token,action='feedback',attended='No',satisfied='Not visited',
                        reason='Work conflict',db_path=self.db,now=after)
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(1,0))
        message=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertIn('reschedule',message.get_body(preferencelist=('plain',)).get_content())
        self.assertEqual(message['To'],'mixed@example.com')
        self.assertEqual(run_visit_worker(self.config,self.db,now=after),(0,0))

    def test_whatsapp_email_requires_valid_address_and_consent(self):
        args=dict(self.args,user_id='mixed',record={'property_id':'another','title':'Another visit'},contact_method='WhatsApp',contact_value='+919876543210')
        with self.assertRaisesRegex(ValueError,'valid email'):
            request_visit(**args)
        mixed_id=request_visit(**dict(args,email_reminders=False,followup_email='unused@example.com'))
        with _connect(self.db) as c:
            row=c.execute('SELECT * FROM property_visit_requests WHERE id=?',(mixed_id,)).fetchone()
        self.assertEqual(row['followup_email'],'')
        self.assertEqual(row['visit_email_consent'],'')

    def test_scoped_worker_never_sends_another_visits_queued_email(self):
        with _connect(self.db) as c:
            c.execute("INSERT INTO visit_email_outbox(id,visit_id,visit_at,kind,updated_at) VALUES(?,?,?,?,?)",
                      ('outside',self.id,self.at.isoformat(timespec='minutes'),'reminder',self.at.isoformat()))
        self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(hours=1),only_visit_id='missing'),(0,0))
        self.smtp.assert_not_called()
        with _connect(self.db) as c:
            self.assertEqual(c.execute("SELECT status FROM visit_email_outbox WHERE id='outside'").fetchone()['status'],'queued')

    def test_explore_requires_permission(self):
        self.remind()
        with self.assertRaises(ValueError):record_response(self.token(),action='explore',reason='Different area',db_path=self.db)
        record_response(self.token(),action='explore',reason='Different area',explore_consent=True,db_path=self.db)
        self.assertEqual(owner_journeys(self.db)[0]['explore_consent'],'Yes')

    def test_failure_is_held_for_review_not_resent(self):
        self.smtp.return_value.__enter__.return_value.send_message.side_effect=TimeoutError()
        self.assertEqual(self.remind(),(0,1));self.assertEqual(self.remind(),(0,0))
        with _connect(self.db) as c:
            self.assertEqual(c.execute('SELECT status FROM visit_email_outbox').fetchone()['status'],'needs_review')

    def test_invalid_token_and_early_feedback(self):
        self.remind()
        self.assertIsNone(response_context('invalid',self.db))
        with self.assertRaises(ValueError):record_response(self.token(),action='feedback',attended='Yes',satisfied='Yes',db_path=self.db)

    def test_response_page_view_does_not_change_booking_and_yes_saves(self):
        from streamlit.testing.v1 import AppTest
        self.remind()
        source = f'''from pathlib import Path
from functools import partial
from unittest.mock import patch
from visit_journey import response_context, record_response
from visit_journey_ui import render_visit_response
db=Path({str(self.db)!r})
with patch('visit_journey_ui.response_context', partial(response_context, db_path=db)), patch('visit_journey_ui.record_response', partial(record_response, db_path=db)):
    render_visit_response()
'''
        app=AppTest.from_string(source,default_timeout=30)
        app.query_params['visit_response']=self.token()
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(owner_journeys(self.db)[0]['attendance'],'Awaiting response')
        next(button for button in app.button if button.label=='Save response').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(owner_journeys(self.db)[0]['attendance'],'Yes')


if __name__=='__main__': unittest.main()
