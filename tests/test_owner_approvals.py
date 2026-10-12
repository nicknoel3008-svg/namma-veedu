import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from agent_runtime import INDIA_TZ
from visit_service import request_visit,update_visit_status
from visit_journey import run_visit_worker
from datetime import timedelta
from followup_service import _connect
from owner_approvals import approve_messages

class OwnerMessageApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'queue.sqlite3'
        self.at=datetime.now(INDIA_TZ)+timedelta(days=2)
        vid=request_visit(record={'property_id':'plot','title':'Test plot'},user_id='u',visit_at=self.at,slot_kind='Custom time',customer_name='Test',contact_method='Email',contact_value='test@example.com',consent=True,email_reminders=True,db_path=self.db)
        update_visit_status(vid,'Confirmed',db_path=self.db)
        self.config=dict(VISIT_EMAIL_ENABLED='true',VISIT_CONFIRMATION_EMAIL_ENABLED='false',FOLLOWUP_SMTP_HOST='smtp.example.com',FOLLOWUP_SMTP_USERNAME='sender',FOLLOWUP_SMTP_PASSWORD='test',FOLLOWUP_SMTP_FROM='sender@example.com',FOLLOWUP_PUBLIC_URL='https://example.com')
        self.mock=patch('visit_journey.smtplib.SMTP');self.smtp=self.mock.start();self.addCleanup(self.mock.stop)

    # Only this new contract test; base cases are exercised separately.
    def test_manual_gate_then_exact_message_approval(self):
        now=self.at-timedelta(hours=1)
        self.assertEqual(run_visit_worker(self.config,self.db,now=now),(0,0))
        self.smtp.return_value.__enter__.return_value.send_message.assert_not_called()
        with _connect(self.db) as c:
            rows=list(c.execute('SELECT id FROM visit_email_outbox'))
        self.assertTrue(rows)
        approve_messages([('visit',r['id']) for r in rows],'Owner',self.db)
        self.assertEqual(run_visit_worker(self.config,self.db,now=now),(1,0))
        self.assertEqual(run_visit_worker(self.config,self.db,now=now),(0,0))


class DashboardApprovalTests(unittest.TestCase):
    def test_global_button_applies_staged_changes(self):
        from streamlit.testing.v1 import AppTest
        from unittest.mock import Mock,patch
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from followup_service import _connect
        with TemporaryDirectory() as folder:
            db=Path(folder)/'queue.sqlite3'
            callback=Mock()
            script="import streamlit as st\nst.session_state.owner_dashboard_authenticated=True\nfrom owner_approvals import render\nrender()"
            with patch('owner_approvals._connect',side_effect=lambda *a,**k:_connect(db)):
                app=AppTest.from_string(script)
                app.session_state['owner_pending_changes']={'test':('Advisor assignment',callback)}
                app.run()
                self.assertFalse(app.exception)
                next(b for b in app.button if b.label=='Approve all changes').click().run()
                self.assertFalse(app.exception)
                callback.assert_called_once()
                self.assertEqual(app.session_state['owner_pending_changes'],{})
