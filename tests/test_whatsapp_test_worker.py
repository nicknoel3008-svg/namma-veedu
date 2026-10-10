import unittest
from unittest.mock import Mock, patch
from run_whatsapp_test_worker import run


class TestWorkerGuards(unittest.TestCase):
    def setUp(self):
        self.config = {"WHATSAPP_ACCESS_TOKEN":"test", "WHATSAPP_PHONE_NUMBER_ID":"1330438393493229", "WHATSAPP_API_VERSION":"v25.0", "WHATSAPP_TEMPLATE_NAME":"namma_veedu_followup", "WHATSAPP_TEMPLATE_LANGUAGE":"en_US"}

    def response(self, status):
        response = Mock(ok=True)
        response.json.return_value = {"data":[{"name":"namma_veedu_followup","language":"en_US","status":status}]}
        return response

    def test_pending_and_invalid_token_never_send(self):
        for response in (self.response("PENDING"), Mock(ok=False, status_code=401)):
            with patch("run_whatsapp_test_worker.requests.get",return_value=response), patch("run_whatsapp_test_worker.send_due_whatsapp_followups") as send:
                self.assertEqual(run(self.config,"+919876543210")["sent"],0)
                send.assert_not_called()

    def test_approved_checks_do_not_send_and_runs_restrict_recipient(self):
        with patch("run_whatsapp_test_worker.requests.get",return_value=self.response("APPROVED")), patch("run_whatsapp_test_worker.send_due_whatsapp_followups",return_value=(0,0)) as send:
            self.assertEqual(run(self.config,"+919876543210",check_only=True)["status"],"ready")
            send.assert_not_called()
            self.assertEqual(run(self.config,"+919876543210")["status"],"processed")
            self.assertEqual(send.call_args.kwargs["recipient_allowlist"],{"+919876543210"})
