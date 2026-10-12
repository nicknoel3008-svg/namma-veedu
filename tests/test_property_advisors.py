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
    def test_editable_table_select_all_stages_without_saving(self):
        from streamlit.testing.v1 import AppTest
        script="import streamlit as st\nst.session_state.owner_dashboard_authenticated=True\nfrom property_advisors import render_setup\nrender_setup()"
        with patch('visit_service.list_visit_requests',return_value=self.visits),patch('property_advisors.assignments',return_value=[]),patch('advisor_directory.advisors',return_value=[{'role':'Property agent','name':'Temporary advisor','email':'temporary@example.com'}]),patch('property_search.load_properties') as load,patch('property_advisors._connect',side_effect=lambda *a,**k:_connect(self.db)),patch('property_advisors.save_assignment') as save:
            load.return_value.fillna.return_value.to_dict.return_value=[]
            app=AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.text_input),0)
            self.assertTrue(app.button[0].disabled)
            app.checkbox[0].check().run()
            self.assertFalse(app.button[0].disabled)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            save.assert_not_called()
            self.assertEqual(len(app.session_state['owner_pending_changes']),2)

    def test_table_contact_selection_fills_only_edited_property(self):
        from property_advisors import apply_assignment_edits
        rows=[{'Property':'A','Advisor':'Old','Advisor email':'old@example.com'},{'Property':'B','Advisor':'Other','Advisor email':'other@example.com'}]
        result=apply_assignment_edits(rows,{0:{'Saved CRM advisor':'New'}},{'New':{'name':'New advisor','email':'new@example.com'}})
        self.assertEqual(result[0]['Advisor email'],'new@example.com')
        self.assertEqual(result[1],rows[1])
        self.assertEqual(rows[0]['Advisor'],'Old')
    def test_prefill_requires_exact_property_and_unambiguous_contact(self):
        from property_advisors import suggested_assignment
        from visit_service import property_key
        record={'property_id':'site-a','agent_name':'Site A advisor','agent_email':'a@example.com'}
        visit={'property_key':property_key(record)}
        self.assertEqual(suggested_assignment(visit,[record])['email'],'a@example.com')
        self.assertEqual(suggested_assignment(visit,[{**record,'property_id':'site-b'}]),{})
        self.assertEqual(suggested_assignment(visit,[record,{**record,'agent_email':'other@example.com'}]),{})
        self.assertEqual(suggested_assignment(visit,[{'property_id':'site-a','source_name':'Builder'}]),{})
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.db=Path(self.tmp.name)/'db.sqlite'
        self.now=datetime.now(INDIA_TZ);self.at=self.now+timedelta(days=1)
        self.ids=[]
        for title in ('A','B'):
            vid=request_visit(record={'property_id':title,'title':title},user_id=title,visit_at=self.at,slot_kind='Custom time',customer_name=title,contact_method='Email',contact_value=title+'@example.com',consent=True,db_path=self.db)
            update_visit_status(vid,'Confirmed',db_path=self.db);self.ids.append(vid)
        with _connect(self.db) as c:self.visits=[dict(r) for r in c.execute('SELECT * FROM property_visit_requests').fetchall()]
        self.cfg=dict(VISIT_EMAIL_ENABLED='true',FOLLOWUP_SMTP_HOST='smtp.example.com',FOLLOWUP_SMTP_USERNAME='sender',FOLLOWUP_SMTP_PASSWORD='test',FOLLOWUP_SMTP_FROM='sender@example.com',FOLLOWUP_PUBLIC_URL='https://example.com')

    def test_directory_and_property_assignments_use_separate_storage(self):
        from advisor_directory import save_advisor,advisors
        from property_advisors import assignments
        save_advisor('Property agent','Directory advisor','directory@example.com',self.db)
        visit=self.visits[0]
        save_assignment(visit['property_key'],'Site advisor','site@example.com',db_path=self.db)
        self.assertEqual(assignments(self.db)[0]['property_key'],visit['property_key'])
        self.assertEqual(advisors(self.db)[0]['name'],'Directory advisor')
        save_advisor('Loan advisor','Loan advisor','loan@example.com',self.db)
        self.assertEqual(len(assignments(self.db)),1)
        self.assertEqual(len(advisors(self.db)),2)


    def approve_ready(self):
        from owner_approvals import approve_messages
        with patch('property_advisors.smtplib.SMTP') as smtp:
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0))
            smtp.assert_not_called()
        with _connect(self.db) as c:
            ids=[r['id'] for r in c.execute("SELECT id FROM advisor_register_delivery WHERE status='queued'")]
        approve_messages([('advisor',identifier) for identifier in ids],'Owner',self.db)

    def test_separate_scopes_dedup_and_reassignment_revokes(self):
        for v in self.visits:save_assignment(v['property_key'],v['customer_name']+' advisor',v['customer_name']+'advisor@example.com',db_path=self.db)
        self.approve_ready()
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
        self.approve_ready()
        with patch('property_advisors.smtplib.SMTP'):
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(1,0))

    def test_missing_disabled_and_uncertain_delivery(self):
        with patch('property_advisors.smtplib.SMTP') as smtp:
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0));smtp.assert_not_called()
        v=self.visits[0]
        save_assignment(v['property_key'],'Advisor','advisor@example.com',active=False,db_path=self.db)
        self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0))
        save_assignment(v['property_key'],'Advisor','advisor@example.com',db_path=self.db)
        self.approve_ready()
        with patch('property_advisors.smtplib.SMTP',side_effect=TimeoutError):
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,1))
            self.assertEqual(run_advisor_worker(self.cfg,self.db),(0,0))
        with _connect(self.db) as c:self.assertEqual(c.execute('SELECT status FROM advisor_register_delivery').fetchone()['status'],'needs_review')
