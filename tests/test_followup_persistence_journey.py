"""Chat-to-storage integration using real, temporary SQLite and workbook files."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from followup_service import schedule_email_followup, list_email_followups, cancel_user_followups
from inquiry_log import append_inquiry, update_conversation_fields, read_inquiries

ROOT = Path(__file__).resolve().parents[1]


class FollowupPersistenceJourneyTests(unittest.TestCase):
    def test_chat_consent_persists_and_returning_user_stops_email(self):
        with TemporaryDirectory() as folder:
            db = Path(folder) / "followups.sqlite3"
            workbook = Path(folder) / "inquiries.xlsx"
            with patch("ai_config.select_ai_config", return_value=("offline", "", "")), \
                 patch("storage_backend._database_url", return_value=""), \
                 patch("inquiry_log.append_inquiry", side_effect=lambda record: append_inquiry(record, workbook)), \
                 patch("inquiry_log.update_conversation_fields", side_effect=lambda conversation, fields: update_conversation_fields(conversation, fields, workbook)), \
                 patch("followup_service.email_config_ready", return_value=False), \
                 patch("followup_service.schedule_email_followup", side_effect=lambda **kwargs: schedule_email_followup(**kwargs, db_path=db)), \
                 patch("followup_service.list_email_followups", side_effect=lambda user: list_email_followups(user, db_path=db)), \
                 patch("followup_service.cancel_user_followups", side_effect=lambda user: cancel_user_followups(user, db_path=db)):
                app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
                def send(text):
                    next(item for item in app.text_input if item.label == "Message Mira").set_value(text)
                    next(item for item in app.button if item.label == "Send").click().run()
                    self.assertFalse(app.exception)
                send("email me later")
                send("qa@example.com")
                self.assertEqual(list_email_followups(app.session_state["user_id"], db), [])
                send("yes")
                saved, = list_email_followups(app.session_state["user_id"], db)
                self.assertEqual(saved["status"], "saved_pending_activation")
                self.assertEqual(saved["recipient_email"], "qa@example.com")
                self.assertEqual([toast.value for toast in app.toast], ["Follow-up saved"])
                rows = read_inquiries(workbook)
                self.assertEqual(rows[-1]["Follow-up method"], "Email")
                self.assertEqual(rows[-1]["Follow-up schedule status"], "Saved (email delivery off)")
                self.assertEqual(rows[-1]["Conversation ID"], app.session_state["inquiry_conversation_id"])
                send("Show me flats in Chennai")
                saved, = list_email_followups(app.session_state["user_id"], db)
                self.assertEqual(saved["status"], "cancelled")
