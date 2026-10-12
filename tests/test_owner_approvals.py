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
            with patch('owner_approvals._connect',side_effect=lambda *a,**k:_connect(db)),patch('owner_approvals.prepare_current_actions',return_value=None):
                app=AppTest.from_string(script)
                app.session_state['owner_pending_changes']={'test':('Advisor assignment',callback)}
                app.run()
                self.assertFalse(app.exception)
                next(b for b in app.button if b.label=='Approve all changes').click().run()
                self.assertFalse(app.exception)
                callback.assert_called_once()
                self.assertEqual(app.session_state['owner_pending_changes'],{})

    def test_one_click_prepares_and_approves_messages_created_by_updates(self):
        from streamlit.testing.v1 import AppTest
        from unittest.mock import patch
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from datetime import datetime,timedelta
        from agent_runtime import INDIA_TZ
        from followup_service import _connect
        from visit_service import request_visit,update_visit_status,list_visit_requests
        from property_advisors import save_assignment
        from owner_approvals import prepare_current_actions,approve_messages,pending_messages,is_approved
        with TemporaryDirectory() as folder:
            db=Path(folder)/'queue.sqlite3'
            vid=request_visit(record={'property_id':'A','title':'A'},user_id='u',visit_at=datetime.now(INDIA_TZ)+timedelta(days=1),slot_kind='Custom time',customer_name='Test',contact_method='Email',contact_value='test@example.com',consent=True,email_reminders=True,db_path=db)
            property_key=list_visit_requests(db_path=db)[0]['property_key']
            def save_updates():
                update_visit_status(vid,'Confirmed',db_path=db)
                save_assignment(property_key,'Advisor','advisor@example.com',db_path=db)
            script="import streamlit as st\nst.session_state.owner_dashboard_authenticated=True\nfrom owner_approvals import render\nrender()"
            with patch('owner_approvals._connect',side_effect=lambda *a,**k:_connect(db)),patch('owner_approvals.prepare_current_actions',side_effect=lambda:prepare_current_actions(db)),patch('owner_approvals.approve_messages',side_effect=lambda items,actor:approve_messages(items,actor,db)),patch('property_advisors.smtplib.SMTP') as advisor_smtp,patch('visit_journey.smtplib.SMTP') as customer_smtp:
                app=AppTest.from_string(script)
                app.session_state['owner_pending_changes']={'updates':('Visit and advisor updates',save_updates)}
                app.run()
                next(b for b in app.button if b.label=='Approve all changes').click().run()
                self.assertFalse(app.exception)
                self.assertIn('2 pending email action(s) approved',app.success[-1].value)
                self.assertEqual(pending_messages(db),[])
                with _connect(db) as c:
                    self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM owner_message_approvals').fetchone()['n'],2)
                advisor_smtp.assert_not_called()
                customer_smtp.assert_not_called()
