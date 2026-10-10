import json
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_runtime import INDIA_TZ
from customer_journey import select_property,choices,timeline,preferences_json
from visit_service import request_visit,update_visit_status
from visit_journey import response_context,record_response,owner_journeys,resume_preferences,record_purchase_outcome
from followup_service import _connect


class CustomerJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'journey.sqlite3'
        self.at=datetime.now(INDIA_TZ)+timedelta(days=1)
        self.record={'property_id':'test','title':'Test plot'}
        self.prefs={'location':'Chennai','max_budget':5000000,'secret':'never retain'}

    def booking(self):
        self.visit=request_visit(record=self.record,user_id='u',conversation_id='c',preferences=self.prefs,
            visit_at=self.at,slot_kind='Custom time',customer_name='Test',contact_method='Email',
            contact_value='test@example.com',consent=True,db_path=self.db)
        update_visit_status(self.visit,'Confirmed',db_path=self.db)
        with _connect(self.db) as c:
            self.token=c.execute('SELECT token FROM visit_journeys WHERE visit_id=?',(self.visit,)).fetchone()['token']

    def test_selection_is_explicit_idempotent_and_can_be_removed(self):
        args=dict(user_id='u',conversation_id='c',record=self.record,preferences=self.prefs,db_path=self.db)
        select_property(**args);select_property(**args)
        self.assertEqual(len(choices('u',self.db)),1)
        self.assertEqual(len(timeline(self.db)),1)
        self.assertNotIn('secret',json.loads(choices('u',self.db)[0]['preferences']))
        select_property(**args,selected=False)
        self.assertEqual(choices('u',self.db)[0]['status'],'Removed')
        self.assertEqual(len(timeline(self.db)),2)
        self.assertEqual(choices('other',self.db),[])

    def test_linked_visit_exists_without_activating_worker(self):
        self.booking()
        row=owner_journeys(self.db)[0]
        self.assertEqual(row['conversation_id'],'c')
        self.assertEqual(json.loads(row['preferences'])['location'],'Chennai')
        self.assertEqual({r['event'] for r in timeline(self.db)},{'Visit requested','Visit confirmed'})
        self.assertIsNone(resume_preferences(self.token,self.db))

    def test_rejection_requires_reason_and_overrides_engagement(self):
        self.booking()
        args=dict(action='feedback',attended='Yes',satisfied='Yes',assistance='Loan advisor',
            details='Discuss eligibility',advisor_consent=True,purchase_intent='Not interested',
            db_path=self.db,now=self.at+timedelta(hours=3))
        with self.assertRaises(ValueError):record_response(self.token,**args)
        record_response(self.token,reason='Too far from work',explore_consent=True,revised_preferences='Prefer Coimbatore',**args)
        row=owner_journeys(self.db)[0]
        self.assertEqual(row['Purchase interest'],'Not interested in this property')
        resumed=resume_preferences(self.token,self.db)
        self.assertEqual(resumed['changes'],'Prefer Coimbatore')
        self.assertNotIn('contact_value',resumed)
        self.assertEqual(set(resumed),{'preferences','changes'})

    def test_purchase_outcome_needs_evidence_and_is_audited(self):
        self.booking()
        with self.assertRaises(ValueError):record_purchase_outcome(self.visit,'Purchased','',self.db)
        record_purchase_outcome(self.visit,'Purchased','Customer confirmed completion to owner',self.db)
        row=owner_journeys(self.db)[0]
        self.assertEqual(row['Purchase interest'],'Purchased (owner recorded)')
        self.assertEqual(row['purchase_outcome'],'Purchased')
        self.assertIn('Purchase outcome recorded',[r['event'] for r in timeline(self.db)])

    def test_preference_size_rejected_without_broken_json(self):
        with self.assertRaises(ValueError):preferences_json({'location':'x'*9000})

    def test_advisor_draft_requires_consent_and_correct_role(self):
        from advisor_directory import save_advisor,prepare_handoff
        self.booking()
        save_advisor('Loan advisor','Test advisor','advisor@example.com',self.db)
        with self.assertRaises(ValueError):prepare_handoff(self.visit,'Loan advisor',self.db)
        record_response(self.token,action='feedback',attended='Yes',satisfied='Yes',assistance='Loan advisor',details='Explain loan requirements',advisor_consent=True,purchase_intent='Interested',db_path=self.db,now=self.at+timedelta(hours=2))
        draft=prepare_handoff(self.visit,'Loan advisor',self.db)
        self.assertEqual(draft['to'],'advisor@example.com')
        self.assertIn('test@example.com',draft['body'])
        with self.assertRaises(ValueError):prepare_handoff(self.visit,'Property agent',self.db)

    def test_removal_does_not_allow_another_users_choice(self):
        from customer_journey import remove_choice
        select_property(user_id='u',conversation_id='c',record=self.record,preferences={},db_path=self.db)
        row=choices('u',self.db)[0]
        self.assertFalse(remove_choice(row['id'],'other',self.db))
        self.assertTrue(remove_choice(row['id'],'u',self.db))

    def test_buyer_decision_after_visit_keeps_confirmed_booking(self):
        self.booking()
        record_response(self.token,action='feedback',attended='Yes',satisfied='Partly',purchase_intent='Undecided',explore_consent=True,revised_preferences='remove budget',db_path=self.db,now=self.at+timedelta(hours=2))
        resumed=resume_preferences(self.token,self.db)
        from conversation_memory import update_preferences
        import pandas as pd
        restored=update_preferences(resumed['changes'],pd.read_csv('data/properties.csv'),resumed['preferences'])
        self.assertNotIn('max_budget',restored)
        self.assertEqual(owner_journeys(self.db)[0]['status'],'Confirmed')

    def test_owner_journey_view_renders_linked_records(self):
        from streamlit.testing.v1 import AppTest
        self.booking()
        app=AppTest.from_file(str(Path(__file__).parent/'owner_dashboard_sandbox.py'),default_timeout=60)
        app.session_state['qa_journeys']=owner_journeys(self.db)
        app.session_state['qa_events']=timeline(self.db)
        app.run()
        next(button for button in app.button if button.label=='Load customer journey').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(widget.label=='Outcome' for widget in app.selectbox))
        self.assertTrue(any(widget.label=='Advisor role' for widget in app.selectbox))
        self.assertTrue(any(widget.label=='Conversation timeline' for widget in app.selectbox))


if __name__=='__main__':unittest.main()
