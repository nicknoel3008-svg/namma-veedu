"""Verify delayed email delivery using a temporary queue and mocked SMTP."""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_runtime import INDIA_TZ
from followup_service import _connect, schedule_email_followup, send_due_followups


class FollowupDeliveryTests(unittest.TestCase):
    def test_delayed_worker_spaces_messages_and_completes_sequence(self):
        config = {
            "FOLLOWUP_SMTP_HOST": "smtp.example.com",
            "FOLLOWUP_SMTP_USERNAME": "test", "FOLLOWUP_SMTP_PASSWORD": "test",
            "FOLLOWUP_SMTP_FROM": "test@example.com",
            "FOLLOWUP_PUBLIC_URL": "https://example.com",
        }
        with TemporaryDirectory() as folder:
            db = Path(folder) / "queue.sqlite3"
            schedule_id = schedule_email_followup(
                user_id="test", conversation_id="test", recipient_email="recipient@example.com",
                customer_name="", preference_summary="Plots", started_at=datetime.now(INDIA_TZ),
                max_messages=3, db_path=db,
            )
            with patch("followup_service.smtplib.SMTP") as smtp, patch("inquiry_log.update_conversation_fields"):
                for index in range(3):
                    with _connect(db) as connection:
                        connection.execute("UPDATE email_followups SET next_send_at=? WHERE id=?", (
                            (datetime.now(INDIA_TZ) - timedelta(days=10)).isoformat(), schedule_id,
                        ))
                    before = datetime.now(INDIA_TZ).replace(microsecond=0)
                    self.assertEqual(send_due_followups(config, db), (1, 0))
                    with _connect(db) as connection:
                        row = connection.execute("SELECT * FROM email_followups WHERE id=?", (schedule_id,)).fetchone()
                    self.assertEqual(row["sent_count"], index + 1)
                    self.assertGreaterEqual(datetime.fromisoformat(row["next_send_at"]), before + timedelta(days=3))
                    self.assertEqual(row["status"], "complete" if index == 2 else "scheduled")
                    self.assertEqual(send_due_followups(config, db), (0, 0))
                self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 3)


if __name__ == "__main__":
    unittest.main()
