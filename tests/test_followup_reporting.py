import unittest

from followup_reporting import followup_metrics
from inquiry_log import customer_summary_rows


class FollowupReportingTests(unittest.TestCase):
    def test_chat_schedules_count_once_and_cancellation_closes_them(self):
        rows = [{"Conversation ID": "a", "Timestamp (Asia/Kolkata)": str(i),
                 "Follow-up method": "In-app reminder", "Follow-up schedule status": "Scheduled"} for i in range(3)]
        self.assertEqual(followup_metrics(rows), dict(saved=1, open=1, completed=0))
        rows.append({"Conversation ID": "a", "Timestamp (Asia/Kolkata)": "4", "Follow-up schedule status": "Removed"})
        self.assertEqual(followup_metrics(rows), dict(saved=1, open=0, completed=0))

    def test_pending_email_and_owner_completion(self):
        row = {"Conversation ID": "a", "Follow-up method": "Email", "Follow-up schedule status": "Saved (email delivery off)"}
        self.assertEqual(followup_metrics([row])["open"], 1)
        row["Follow-up status (owner)"] = "Completed"
        self.assertEqual(followup_metrics([row]), dict(saved=1, open=0, completed=1))

    def test_details_survive_later_turn_without_schedule_fields(self):
        rows = [{"Conversation ID": "a", "Timestamp (Asia/Kolkata)": "1", "Follow-up method": "In-app reminder", "Follow-up summary": "Call about parking"},
                {"Conversation ID": "a", "Timestamp (Asia/Kolkata)": "2"}]
        summary = customer_summary_rows(rows)[0]
        self.assertEqual(summary["Follow-up method"], "In-app reminder")
        self.assertEqual(summary["Follow-up summary"], "Call about parking")
