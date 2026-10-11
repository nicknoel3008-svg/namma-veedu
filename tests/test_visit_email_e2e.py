"""Actual customer/owner/response UI against isolated storage and a fake SMTP server."""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from agent_runtime import INDIA_TZ
from followup_service import _connect
from visit_service import list_visit_requests
from visit_journey import run_visit_worker, owner_journeys

ROOT = Path(__file__).resolve().parents[1]


class VisitEmailEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'end-to-end.sqlite3'
        self.config = dict(VISIT_EMAIL_ENABLED='true', FOLLOWUP_SMTP_HOST='smtp.example.com',
            FOLLOWUP_SMTP_USERNAME='sender', FOLLOWUP_SMTP_PASSWORD='test',
            FOLLOWUP_SMTP_FROM='sender@example.com', FOLLOWUP_PUBLIC_URL='https://example.com')
        self.smtp = patch('visit_journey.smtplib.SMTP').start()
        self.addCleanup(patch.stopall)

    def source(self, name):
        source = (ROOT / 'tests' / name).read_text(encoding='utf-8')
        return source.replace('ROOT = Path(__file__).resolve().parents[1]', f'ROOT = Path({str(ROOT)!r})')

    def test_customer_request_owner_approval_email_response_and_feedback(self):
        self.check_customer_journey(mixed=False)

    def test_whatsapp_booking_with_email_followups_and_feedback(self):
        self.check_customer_journey(mixed=True)

    def check_customer_journey(self, mixed):
        source = self.source('website_sandbox.py')
        source = source.replace('with patch("ai_config',
            f'from functools import partial\nfrom visit_service import request_visit as real_request\ndb=Path({str(self.db)!r})\nwith patch("ai_config', 1)
        source = source.replace('patch("visit_service.request_visit", return_value="qa-visit-request")',
            'patch("visit_service.request_visit", side_effect=partial(real_request, db_path=db))')
        customer = AppTest.from_string(source, default_timeout=60).run()
        customer.session_state['visit_property'] = {'property_id':'e2e-home','title':'E2E home'}
        customer.run()
        next(x for x in customer.radio if x.label=='Choose a visit time').set_value('Custom time').run()
        next(x for x in customer.date_input if x.label=='Visit date').set_value((datetime.now(INDIA_TZ)+timedelta(days=2)).date())
        next(x for x in customer.text_input if x.key=='visit_customer_name').set_value('E2E customer')
        if mixed:
            next(x for x in customer.selectbox if x.key=='visit_contact_method').set_value('WhatsApp').run()
            next(x for x in customer.text_input if x.key=='visit_followup_email').set_value('e2e@example.com')
            next(x for x in customer.checkbox if x.key=='visit_manual_whatsapp_confirmation').check()
        next(x for x in customer.text_input if x.key=='visit_contact_value').set_value('+919876543210' if mixed else 'e2e@example.com')
        next(x for x in customer.checkbox if x.key=='visit_consent').check()
        next(x for x in customer.checkbox if x.key=='visit_email_reminders').check()
        next(x for x in customer.button if x.label=='Request visit').click().run()
        self.assertFalse(customer.exception)
        visit = list_visit_requests(db_path=self.db)[0]
        self.assertEqual(visit['status'], 'Requested')
        self.assertEqual(visit['visit_email_consent'], 'Yes')
        self.assertEqual(run_visit_worker(self.config, self.db), (0,0))

        source = self.source('owner_dashboard_sandbox.py')
        source = source.replace('with patch("ai_config',
            f'from functools import partial\nfrom visit_service import list_visit_requests as real_list, update_visit_status as real_update\nfrom visit_journey import owner_journeys as real_journeys\ndb=Path({str(self.db)!r})\nwith patch("visit_service.list_visit_requests", side_effect=partial(real_list, db_path=db)), patch("visit_service.update_visit_status", side_effect=partial(real_update, db_path=db)), patch("ai_config', 1)
        source = source.replace('side_effect=lambda *args,**kwargs: st.session_state.get("qa_journeys", [])',
            'side_effect=partial(real_journeys, db_path=db)')
        owner = AppTest.from_string(source, default_timeout=60).run()
        self.assertFalse(owner.exception)
        next(x for x in owner.button if x.label=='Load visit requests').click().run()
        self.assertFalse(owner.exception)
        owner.session_state['visit_requests_editor'] = {'edited_rows':{0:{'status':'Confirmed'}},'added_rows':[],'deleted_rows':[]}
        next(x for x in owner.button if x.label=='Save visit decisions').click().run()
        self.assertFalse(owner.exception)
        self.assertEqual(list_visit_requests(db_path=self.db)[0]['status'], 'Confirmed')
        at = datetime.fromisoformat(visit['visit_at'])
        self.assertEqual(run_visit_worker(self.config, self.db, now=at-timedelta(days=1)), (0,0) if mixed else (1,0))
        self.assertEqual(run_visit_worker(self.config, self.db, now=at-timedelta(days=1)), (0,0))
        if not mixed:
            confirmation = self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(confirmation['To'], 'e2e@example.com')
            self.assertIn('visit is confirmed', confirmation['Subject'])
            self.assertIn('E2E home', confirmation.get_content())
        self.assertEqual(run_visit_worker(self.config, self.db, now=at-timedelta(minutes=55)), (1,0))
        with _connect(self.db) as c:
            token = c.execute('SELECT token FROM visit_journeys WHERE visit_id=?',(visit['id'],)).fetchone()['token']
        source = f'''from pathlib import Path
from functools import partial
from unittest.mock import patch
from visit_journey import response_context, record_response
from visit_journey_ui import render_visit_response
db=Path({str(self.db)!r})
with patch('visit_journey_ui.response_context', partial(response_context,db_path=db)), patch('visit_journey_ui.record_response', partial(record_response,db_path=db)):
    render_visit_response()
'''
        response = AppTest.from_string(source, default_timeout=60)
        response.query_params['visit_response'] = token
        response.run()
        self.assertFalse(response.exception)
        next(x for x in response.button if x.label=='Save response').click().run()
        self.assertFalse(response.exception)
        self.assertEqual(owner_journeys(self.db)[0]['attendance'], 'Yes')
        self.assertEqual(run_visit_worker(self.config, self.db, now=at+timedelta(hours=2)), (1,0))
        self.assertEqual(run_visit_worker(self.config, self.db, now=at+timedelta(hours=2)), (0,0))
        feedback_source = source.replace('with patch(', f'''from datetime import datetime
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):
        return datetime.fromisoformat({(at+timedelta(hours=2)).isoformat()!r})
with patch('visit_journey_ui.datetime',Clock), patch(''',1)
        feedback_source = feedback_source.replace('partial(record_response,db_path=db)',
            f'partial(record_response,db_path=db,now=Clock.now())')
        feedback = AppTest.from_string(feedback_source,default_timeout=60)
        feedback.query_params['visit_response'] = token
        feedback.run()
        self.assertFalse(feedback.exception)
        self.assertEqual(next(x for x in feedback.radio if x.label=='How can we help?').value,'Visit feedback')
        next(x for x in feedback.button if x.label=='Save response').click().run()
        self.assertFalse(feedback.exception)
        self.assertFalse(feedback.error)
        self.assertEqual(owner_journeys(self.db)[0]['attended'], 'Yes')
        self.assertEqual(self.smtp.return_value.__enter__.return_value.send_message.call_count,2 if mixed else 3)
        self.assertEqual(run_visit_worker(self.config,self.db,now=at+timedelta(hours=2)),(1,0))
        decision=self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(decision['To'],'e2e@example.com')
        self.assertIn('Next steps',decision['Subject'])
        self.assertEqual(run_visit_worker(self.config,self.db,now=at+timedelta(hours=2)),(0,0))
        owner.run()
        self.assertFalse(owner.exception)
        self.assertEqual(owner_journeys(self.db)[0]['confirmation email'],'Not sent' if mixed else 'sent')


if __name__=='__main__':
    unittest.main()
