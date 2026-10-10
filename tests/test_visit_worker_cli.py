import unittest
from unittest.mock import patch
import run_visit_worker as worker


class VisitWorkerCliTests(unittest.TestCase):
    def test_check_never_connects_or_sends(self):
        with patch.object(worker,'load_config',return_value={'DATABASE_URL':'postgresql://test'}), patch.object(worker,'email_config_issues',return_value=[]), patch.object(worker,'_connect') as connect, patch.object(worker,'run_visit_worker') as send, patch.dict(worker.os.environ,{},clear=True):
            self.assertEqual(worker.main(['--check']),0)
            connect.assert_not_called()
            send.assert_not_called()

    def test_missing_shared_storage_cannot_send(self):
        with patch.object(worker,'load_config',return_value={}), patch.object(worker,'email_config_issues',return_value=[]), patch.object(worker,'run_visit_worker') as send:
            self.assertEqual(worker.main([]),2)
            send.assert_not_called()

    def test_requires_explicit_delivery_enable(self):
        with patch.object(worker,'load_config',return_value={'DATABASE_URL':'postgresql://test','VISIT_EMAIL_ENABLED':'true'}), patch.object(worker,'email_config_issues',return_value=[]), patch.object(worker,'run_visit_worker',return_value=(0,0)) as send, patch.dict(worker.os.environ,{},clear=True):
            self.assertEqual(worker.main([]),0)
            self.assertEqual(send.call_args.args[0]['VISIT_EMAIL_ENABLED'],'false')
