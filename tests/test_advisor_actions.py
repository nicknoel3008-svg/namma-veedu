import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from agent_runtime import INDIA_TZ
from followup_service import _connect
from visit_service import request_visit
from visit_journey import schema as journey_schema,ensure_journey
from advisor_directory import save_advisor
from advisor_actions import create_request,context,respond,run_worker
from owner_approvals import approve_messages

class AdvisorActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'db.sqlite'
        self.visit=request_visit(record={'property_id':'site','title':'Property'},user_id='u',visit_at=datetime.now(INDIA_TZ)+timedelta(days=5),slot_kind='Custom time',customer_name='Test',contact_method='Email',contact_value='customer@example.com',consent=True,email_reminders=True,db_path=self.db)
        with _connect(self.db) as c:
            journey_schema(c)
            v=c.execute('SELECT * FROM property_visit_requests WHERE id=?',(self.visit,)).fetchone()
            ensure_journey(c,v,datetime.now(INDIA_TZ).isoformat())
            c.execute("UPDATE visit_journeys SET assistance='Loan advisor',advisor_consent='Yes',followup_paused='Yes' WHERE visit_id=?",(self.visit,))
        save_advisor('Loan advisor','Advisor','advisor@example.com',self.db)
        self.identifier=create_request(self.visit,'Loan assistance',self.db)
        with _connect(self.db) as c:self.token=c.execute('SELECT token FROM advisor_action_requests WHERE id=?',(self.identifier,)).fetchone()['token']
    def test_deduplicated_and_pause_preserved_on_progress(self):
        self.assertEqual(create_request(self.visit,'Loan assistance',self.db),self.identifier)
        respond(self.token,'Accepted',db_path=self.db)
        respond(self.token,'Completed',db_path=self.db)
        with _connect(self.db) as c:
            row=c.execute('SELECT advisor_status,followup_paused FROM visit_journeys WHERE visit_id=?',(self.visit,)).fetchone()
        self.assertEqual(row['advisor_status'],'Completed');self.assertEqual(row['followup_paused'],'Yes')
    def test_changed_recipient_invalidates_link(self):
        save_advisor('Loan advisor','Replacement','replacement@example.com',self.db)
        self.assertIsNone(context(self.token,self.db))
        with self.assertRaises(ValueError):respond(self.token,'Accepted',db_path=self.db)
    @patch('advisor_actions.smtplib.SMTP')
    def test_worker_requires_approval_and_deduplicates(self,smtp):
        config=dict(VISIT_EMAIL_ENABLED='true',FOLLOWUP_SMTP_HOST='smtp.example.com',FOLLOWUP_SMTP_PORT='587',FOLLOWUP_SMTP_USERNAME='sender',FOLLOWUP_SMTP_PASSWORD='test',FOLLOWUP_SMTP_FROM='sender@example.com',FOLLOWUP_PUBLIC_URL='https://example.com')
        self.assertEqual(run_worker(config,self.db),(0,0));smtp.assert_not_called()
        approve_messages([('advisor_action',self.identifier)],'Owner',self.db)
        self.assertEqual(run_worker(config,self.db),(1,0))
        self.assertEqual(run_worker(config,self.db),(0,0))
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()
    def test_expired_link_is_rejected(self):
        with _connect(self.db) as c:c.execute("UPDATE advisor_action_requests SET expires_at='2020-01-01T00:00+05:30'")
        self.assertIsNone(context(self.token,self.db))

    def test_availability_acceptance_does_not_confirm_booking(self):
        from property_advisors import save_assignment
        with _connect(self.db) as c:
            key=c.execute('SELECT property_key FROM property_visit_requests WHERE id=?',(self.visit,)).fetchone()['property_key']
        save_assignment(key,'Site advisor','site@example.com',db_path=self.db)
        identifier=create_request(self.visit,'Visit availability',self.db)
        with _connect(self.db) as c:token=c.execute('SELECT token FROM advisor_action_requests WHERE id=?',(identifier,)).fetchone()['token']
        respond(token,'Accepted',db_path=self.db)
        with _connect(self.db) as c:status=c.execute('SELECT status FROM property_visit_requests WHERE id=?',(self.visit,)).fetchone()['status']
        self.assertEqual(status,'Requested')
