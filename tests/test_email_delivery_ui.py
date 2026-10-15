import unittest
from unittest.mock import Mock,patch
from email_delivery_ui import display_status,dispatch_worker

class EmailDeliveryTests(unittest.TestCase):
    def test_approval_states_are_distinct(self):
        self.assertEqual(display_status('queued',False),'Awaiting approval')
        self.assertEqual(display_status('queued',True),'Approved / queued')
        self.assertEqual(display_status('needs_review',True),'Needs attention')
        self.assertEqual(display_status('sent',True),'Sent (SMTP accepted)')
    @patch('email_delivery_ui.requests.post')
    def test_dispatch_uses_existing_main_workflow(self,post):
        post.return_value=Mock(status_code=204)
        dispatch_worker('private-test-token')
        self.assertEqual(post.call_args.kwargs['json'],{'ref':'main'})
        self.assertEqual(post.call_count,1)
    @patch('email_delivery_ui.requests.post')
    def test_missing_connection_never_dispatches(self,post):
        with self.assertRaises(ValueError):dispatch_worker('')
        post.assert_not_called()
    @patch('email_delivery_ui.requests.post')
    def test_rejected_dispatch_is_not_reported_as_success(self,post):
        post.return_value=Mock(status_code=403)
        with self.assertRaises(ValueError):dispatch_worker('test-token')
