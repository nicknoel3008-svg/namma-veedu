import unittest
from inquiry_log import inquiry_snapshot_groups


class SnapshotDateTests(unittest.TestCase):
    def test_shared_records_use_india_date_and_ignore_invalid_timestamps(self):
        rows = [{"Timestamp (Asia/Kolkata)": "2026-10-09T20:00:00+00:00"},
                {"Timestamp (Asia/Kolkata)": "2026-10-10T08:00:00+05:30"},
                {"Timestamp (Asia/Calcutta)": "2026-10-09T10:00:00"},
                {"Timestamp (Asia/Kolkata)": "invalid"}]
        grouped = inquiry_snapshot_groups(rows)
        self.assertEqual(len(grouped["2026-10-10"]), 2)
        self.assertEqual(len(grouped["2026-10-09"]), 1)
