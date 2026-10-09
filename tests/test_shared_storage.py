import unittest
from unittest.mock import patch, Mock, MagicMock
import storage_backend


class SharedStorageTests(unittest.TestCase):
    def test_legacy_records_import_once_without_overwriting_cloud(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [({"Inquiry ID": "legacy", "Feedback ID": "feedback"},)]
        reader = Mock(return_value=[{"Inquiry ID": "legacy", "Feedback ID": "feedback"}])
        with patch.object(storage_backend, "_database_url", return_value="test-database"), patch.object(storage_backend, "is_configured", return_value=True), patch.object(storage_backend, "_connect", return_value=connection), patch.object(storage_backend, "_imported_local_databases", set()):
            self.assertEqual(storage_backend.read_inquiries(reader)[0]["Feedback ID"], "feedback")
            storage_backend.read_inquiries(reader)
        reader.assert_called_once()
        inserts = [call for call in cursor.execute.call_args_list if "INSERT INTO" in call.args[0]]
        self.assertEqual(len(inserts), 1)
        self.assertIn("ON CONFLICT (inquiry_id) DO NOTHING", inserts[0].args[0])

    def test_unconfigured_development_keeps_local_storage(self):
        with patch.object(storage_backend, "_database_url", return_value=""):
            self.assertEqual(storage_backend._db_call(Mock(), lambda: "local"), "local")

    def test_database_failure_never_reports_local_save(self):
        fallback = Mock()
        with patch.object(storage_backend, "_database_url", return_value="configured"), patch.object(storage_backend, "is_configured", return_value=True), patch.object(storage_backend, "_connect", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "Shared storage is unavailable"):
                storage_backend._db_call(Mock(), fallback)
        fallback.assert_not_called()

    def test_missing_driver_never_switches_to_local(self):
        fallback = Mock()
        with patch.object(storage_backend, "_database_url", return_value="configured"), patch.object(storage_backend, "is_configured", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "driver"):
                storage_backend._db_call(Mock(), fallback)
        fallback.assert_not_called()
