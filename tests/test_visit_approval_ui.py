import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from visit_approval_ui import approve_selected

class ApprovalTests(unittest.TestCase):
    def test_bulk_only_selected_requested_and_errors(self):
        rows=[{'Request ID':k,'Customer':k,'Status':status,'Approve':selected} for k,status,selected in [('a','Requested',True),('b','Requested',False),('c','Confirmed',True),('d','Requested',True)]]
        with patch('visit_service.update_visit_status',side_effect=[True,ValueError('Slot unavailable')]) as save:
            approved,errors=approve_selected(rows)
        self.assertEqual(approved,['a'])
        self.assertEqual(errors,['d: Slot unavailable'])
        self.assertEqual(save.call_count,2)

    def test_select_all_approves_dataset(self):
        visit=dict(id='v',customer_name='Joseph',property_title='Home',visit_at='2026-10-13T10:00+05:30',status='Requested',contact_method='WhatsApp',contact_value='+919876543210',visit_email_consent='Yes',followup_email='test@example.com')
        script="import streamlit as st\nst.session_state.owner_dashboard_authenticated=True\nfrom visit_approval_ui import render\nrender()"
        def save_visit(*args):
            visit['status']='Confirmed'
            return True
        with patch('visit_service.list_visit_requests',side_effect=lambda:[visit]),patch('visit_service.update_visit_status',side_effect=save_visit) as save:
            app=AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            app.checkbox[0].check().run()
            self.assertFalse(app.button[0].disabled)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            save.assert_not_called()
            pending=app.session_state['owner_pending_changes']
            pending['visit_approvals'][1]()
            save.assert_called_once_with('v','Confirmed')
