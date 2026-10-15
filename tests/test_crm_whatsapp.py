from datetime import datetime,timedelta
from urllib.parse import urlsplit,parse_qs
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from agent_runtime import INDIA_TZ
from crm_whatsapp import chat_link,reminder_due,visit_message,response_link


class CRMWhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(INDIA_TZ)
        self.visit=dict(visit_id='v',visit_at=(self.now+timedelta(minutes=60)).isoformat(),property_title='Plot & garden',customer_name='Test',status='Confirmed',attendance='Awaiting response')

    def test_encoded_message_and_phone_validation(self):
        message='Hello & welcome\nதமிழ் + ₹'
        url=chat_link('+91 98765 43210',message)
        self.assertEqual(urlsplit(url).path,'/919876543210')
        self.assertEqual(parse_qs(urlsplit(url).query)['text'],[message])
        with self.assertRaises(ValueError): chat_link('9876543210',message)

    def test_reminder_window_and_ineligible_visits(self):
        self.assertTrue(reminder_due(self.visit,self.now))
        self.assertFalse(reminder_due(self.visit,self.now-timedelta(seconds=1)))
        self.assertFalse(reminder_due(self.visit,self.now+timedelta(hours=1)))
        for changes in ({'status':'Cancelled'},{'status':'Requested'},{'customer_purchase_confirmed_at':'yes'}):
            visit={**self.visit,**changes}
            self.assertFalse(reminder_due(visit,self.now))
            with self.assertRaises(ValueError): visit_message(visit,'reminder',now=self.now)

    def test_feedback_and_time_guard(self):
        with self.assertRaises(ValueError): visit_message(self.visit,'feedback',now=self.now)
        later=self.now+timedelta(hours=2)
        text=visit_message(self.visit,'feedback',now=later,response_url='https://example.com/?visit_response=test')
        self.assertIn('Did you attend',text)
        self.assertIn('interested in purchasing',text)
        self.assertIn('reason',text)
        self.assertIn('visit_response=test',text)
        with self.assertRaises(ValueError): visit_message(self.visit,'confirmation',now=later)

    def test_localhost_response_link_rejected(self):
        self.assertEqual(response_link(self.visit,'http://localhost:8501'),'')
        self.assertEqual(response_link(self.visit,'https://localhost'),'')

    def test_ui_does_not_enable_send_without_permission(self):
        source="""
from crm_whatsapp import render
render({'id':'lead','customer_name':'Test','phone':'+919876543210'},[],'Owner')
"""
        with patch('crm_service.add_note') as note:
            app=AppTest.from_string(source).run()
            self.assertFalse(app.exception)
            self.assertFalse(any(b.label=='3. Save WhatsApp send record' for b in app.button))
            self.assertTrue(app.get('link_button')[0].proto.disabled)
            next(c for c in app.checkbox if c.label.startswith('I have verified')).check()
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.get('link_button')[0].proto.url.startswith('https://wa.me/'))
            self.assertFalse(any(b.label=='3. Save WhatsApp send record' for b in app.button))
            note.assert_not_called()
