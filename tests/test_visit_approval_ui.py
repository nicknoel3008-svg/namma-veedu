import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

class ApprovalTests(unittest.TestCase):
    def test_explicit_approval_and_already_confirmed(self):
        visit=dict(id='v',customer_name='Joseph',property_title='Home',visit_at='2026-10-13T10:00+05:30',status='Requested',contact_method='WhatsApp',contact_value='+919876543210',visit_email_consent='Yes',followup_email='test@example.com')
        script="import streamlit as st\nst.session_state.owner_dashboard_authenticated=True\nfrom visit_approval_ui import render\nrender()"
        with patch('visit_service.list_visit_requests',return_value=[visit]),patch('visit_service.update_visit_status',return_value=True) as save:
            app=AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            app.checkbox[0].check().run()
            app.button[0].click().run()
            save.assert_called_once_with('v','Confirmed')
            visit['status']='Confirmed'
            app=AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.button),0)
            self.assertIn('Already approved',app.success[0].value)

