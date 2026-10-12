import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from agent_runtime import INDIA_TZ
from followup_service import _connect
from visit_service import request_visit,update_visit_status
from property_advisors import save_assignment,run_advisor_worker,schema
from visit_attendance import register_context

class AdvisorAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.db=Path(self.tmp.name)/'db.sqlite'
        self.now=datetime.now(INDIA_TZ);self.at=self.now+timedelta(days=1)
        self.ids=[]
        for title in ('A','B'):
            vid=request_visit(record={'property_id':title,'title':title},user_id=title,visit_at=self.at,slot_kind='Custom time',customer_name=title,contact_method='Email',contact_value=title+'@example.com',consent=True,db_path=self.db)
            update_visit_status(vid,'Confirmed',db_path=self.db);self.ids.append(vid)
        with _connect(self.db) as c:self.visits=[dict(r) for r in c.execute('SELECT * FROM property_visit_requests').fetchall()]
        self.cfg=dict(VISIT_EMAIL_ENABLED='true',FOLLOWUP_SMTP_HOST='smtp.example.com',FOLLOWUP_SMTP_USERNAME='sender',FOLLOWUP_SMTP_PASSWORD='test',FOLLOWUP_SMTP_FROM='sender@example.com',FOLLOWUP_PUBLIC_URL='https://example.com')

    def test_separate_scopes_dedup_and_reassignment_revokes(self):
        for v in self.visits:save_assignment(v['property_key'],v['customer_name']+' advisor',v['customer_name']+'advisor@example.com',db_path=self.db)
        with patch('property_advisors.smtplib.SMTP') as smtp:
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(2,0))
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0))
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,2)
        with _connect(self.db) as c:rows=[dict(r) for r in c.execute('SELECT * FROM advisor_register_delivery').fetchall()]
        for r in rows:
            context=register_context(r['token'],self.db)
            self.assertEqual([v['id'] for v in context['visits']],[r['visit_id']])
        v=self.visits[0];old=next(r for r in rows if r['visit_id']==v['id'])
        save_assignment(v['property_key'],'Replacement','replacement@example.com',db_path=self.db)
        self.assertIsNone(register_context(old['token'],self.db))
        with patch('property_advisors.smtplib.SMTP'):
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(1,0))

    def test_missing_disabled_and_uncertain_delivery(self):
        with patch('property_advisors.smtplib.SMTP') as smtp:
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0));smtp.assert_not_called()
        v=self.visits[0]
        save_assignment(v['property_key'],'Advisor','advisor@example.com',active=False,db_path=self.db)
        self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0))
        save_assignment(v['property_key'],'Advisor','advisor@example.com',db_path=self.db)
        with patch('property_advisors.smtplib.SMTP',side_effect=TimeoutError):
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,1))
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0))
        with _connect(self.db) as c:self.assertEqual(c.execute('SELECT status FROM advisor_register_delivery').fetchone()['status'],'needs_review')
