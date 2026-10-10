from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from agent_runtime import INDIA_TZ
from conversation_engine import conversational_turn
from property_search import load_properties
from visit_service import request_visit,update_visit_status
from visit_journey import owner_journeys,run_visit_worker
from purchase_confirmation import confirm_purchase,run_purchase_worker,reports,save_rating
from followup_service import _connect


class InterestTests(unittest.TestCase):
    def turn(self,text,memory=None,chat=None):
        return conversational_turn(text,load_properties(),chat or [],memory=memory or {})

    def test_interest_offers_assistance_without_purchase(self):
        turn=self.turn("I'm interested in this property",{'selected':{'title':'Test home'}})
        self.assertEqual(turn['intent'],'purchase_assistance_offer')
        self.assertIn('loan guidance',turn['reply'])
        self.assertNotIn('Purchased',str(turn['memory']))
        turn=self.turn('yes',turn['memory'])
        self.assertEqual(turn['intent'],'purchase_assistance_type')
        turn=self.turn('loan advisor',turn['memory'])
        self.assertEqual(turn['advisor_role'],'Loan advisor')
        self.assertIn('consent',turn['reply'])

    def test_ambiguous_interest_resolves_property_before_help(self):
        chat=[{'role':'assistant','mode':'results','records':[{'title':'First home'},{'title':'Second home'}]}]
        turn=self.turn("I'm interested in the property",chat=chat)
        self.assertEqual(turn['intent'],'purchase_interest_property')
        turn=self.turn('second',turn['memory'],chat)
        self.assertEqual(turn['memory']['selected']['title'],'Second home')
        self.assertEqual(turn['intent'],'purchase_assistance_offer')

    def test_decline_and_general_search_do_not_become_purchase(self):
        turn=self.turn('no thanks',{'purchase_help_pending':'assistance','selected':{'title':'Home'}})
        self.assertEqual(turn['intent'],'purchase_assistance_declined')
        turn=self.turn("I'm interested in flats in Chennai")
        self.assertNotEqual(turn['intent'],'purchase_assistance_offer')
        turn=self.turn("I'm not interested in this property",{'selected':{'title':'Home'}})
        self.assertNotEqual(turn['intent'],'purchase_assistance_offer')

    def test_tamil_offer(self):
        turn=self.turn('இந்த சொத்தில் விருப்பம்',{'selected':{'title':'Home'},'response_language':'Tamil'})
        self.assertEqual(turn['intent'],'purchase_assistance_offer')
        self.assertIn('கடன்',turn['reply'])

    def test_fifth_listing_reference(self):
        chat=[{'role':'assistant','mode':'results','records':[{'title':f'Home {i}'} for i in range(1,6)]}]
        turn=self.turn("I'm interested in the property",chat=chat)
        for reference in ('5','fifth'):
            resolved=self.turn(reference,turn['memory'],chat)
            self.assertEqual(resolved['memory']['selected']['title'],'Home 5')

    def test_chat_interest_to_consented_loan_callback(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).parent/'website_sandbox.py'),default_timeout=60).run()
        app.session_state['buyer_memory']={'selected':{'title':'Test home','property_id':'test'},'response_language':'English'}
        def send(text):
            next(x for x in app.text_input if x.label=='Message Mira').set_value(text)
            next(x for x in app.button if x.label=='Send').click().run()
            self.assertFalse(app.exception)
        send("I'm interested in this property")
        self.assertIn('loan guidance',app.session_state['chat'][-1]['content'])
        send('loan advisor')
        self.assertEqual(app.session_state['advisor_request']['role'],'Loan advisor')
        for text in ('email','customer@example.com','Tomorrow at 10 AM','yes'):send(text)
        self.assertEqual(app.session_state['chat'][-1]['mode'],'callback_request_confirmed')
        self.assertNotIn('purchased',app.session_state['chat'][-1]['content'].lower())


class PurchaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'visits.sqlite3'
        self.at=datetime.now(INDIA_TZ)+timedelta(days=1)
        self.visit=request_visit(record={'property_id':'home','title':'Test home'},user_id='u',conversation_id='c',visit_at=self.at,slot_kind='Custom time',customer_name='Test',contact_method='Email',contact_value='test@example.com',consent=True,email_reminders=True,db_path=self.db)
        update_visit_status(self.visit,'Confirmed',db_path=self.db)
        from advisor_directory import save_advisor
        save_advisor('Property agent','Nick','owner@example.com',self.db)
        self.config=dict(VISIT_EMAIL_ENABLED='true',FOLLOWUP_SMTP_HOST='smtp.example.com',FOLLOWUP_SMTP_USERNAME='test',FOLLOWUP_SMTP_PASSWORD='test',FOLLOWUP_SMTP_FROM='sender@example.com',FOLLOWUP_PUBLIC_URL='https://example.com')

    def test_explicit_confirmation_identity_and_idempotent_emails(self):
        with self.assertRaises(ValueError):confirm_purchase(self.visit,user_id='u',db_path=self.db)
        with self.assertRaises(ValueError):confirm_purchase(self.visit,user_id='other',confirmed=True,db_path=self.db)
        confirm_purchase(self.visit,user_id='u',confirmed=True,email_receipt=True,db_path=self.db)
        confirm_purchase(self.visit,user_id='u',confirmed=True,email_receipt=True,db_path=self.db)
        self.assertEqual(len(reports(self.db)),1)
        row=owner_journeys(self.db)[0]
        self.assertEqual(row['purchase_outcome'],'Unknown')
        self.assertIn('customer reported',row['Purchase interest'])
        with patch('visit_journey.smtplib.SMTP') as smtp:
            self.assertEqual(run_visit_worker(self.config,self.db,now=self.at-timedelta(minutes=30)),(0,0));smtp.assert_not_called()
        with patch('purchase_confirmation.smtplib.SMTP') as smtp:
            self.assertEqual(run_purchase_worker(self.config,self.db),(2,0))
            self.assertEqual(run_purchase_worker(self.config,self.db),(0,0))
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,2)

    def test_customer_email_requires_permission_rating_is_validated(self):
        confirm_purchase(self.visit,user_id='u',confirmed=True,db_path=self.db)
        self.assertEqual(reports(self.db)[0]['customer_mail'],'not_requested')
        with _connect(self.db) as c:token=c.execute('SELECT token FROM purchase_receipts').fetchone()['token']
        with self.assertRaises(ValueError):save_rating(token,0,self.db)
        with self.assertRaises(ValueError):save_rating('invalid',5,self.db)
        save_rating(token,5,self.db)
        self.assertEqual(reports(self.db)[0]['rating'],5)

    def test_disabled_worker_and_ambiguous_smtp_failure_not_retried(self):
        confirm_purchase(self.visit,user_id='u',confirmed=True,db_path=self.db)
        self.assertEqual(run_purchase_worker({},self.db),(0,0))
        with patch('purchase_confirmation.smtplib.SMTP',side_effect=OSError):
            self.assertEqual(run_purchase_worker(self.config,self.db),(0,1))
            self.assertEqual(run_purchase_worker(self.config,self.db),(0,0))
        self.assertEqual(reports(self.db)[0]['owner_mail'],'needs_review')
