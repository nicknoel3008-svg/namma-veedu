from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import mira_studio_access


class MiraStudioAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp_file = Path.cwd() / "data" / "private" / f"test_studio_users_{uuid4().hex}.json"
        self.addCleanup(lambda: self.temp_file.unlink(missing_ok=True))
        self.file_patch = patch.object(
            mira_studio_access, "LOCAL_FILE", self.temp_file
        )
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)
        self.db_patch = patch("storage_backend._database_url", return_value="")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_owner_can_create_verify_and_revoke_manager(self):
        code = "safe-manager-code-123"
        mira_studio_access.save_manager("Peer@Example.com", "Priya", code)
        raw = mira_studio_access.LOCAL_FILE.read_text(encoding="utf-8")
        self.assertNotIn(code, raw)
        account = mira_studio_access.verify_manager("peer@example.com", code)
        self.assertEqual(account["display_name"], "Priya")
        self.assertEqual(account["role"], "Manager")
        self.assertIsNone(mira_studio_access.verify_manager("peer@example.com", "wrong-code-value"))
        mira_studio_access.set_manager_active("peer@example.com", False)
        self.assertIsNone(mira_studio_access.verify_manager("peer@example.com", code))

    def test_invalid_email_and_short_code_are_rejected(self):
        with self.assertRaises(ValueError):
            mira_studio_access.save_manager("not-an-email", "Peer", "safe-manager-code-123")
        with self.assertRaises(ValueError):
            mira_studio_access.save_manager("peer@example.com", "Peer", "short")
