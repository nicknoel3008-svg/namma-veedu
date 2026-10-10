"""No real messages or production writes: temporary queue, mocked Meta and SMTP."""
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

from agent_runtime import INDIA_TZ
from chat_followup import followup_turn
from followup_service import _connect, list_email_followups, cancel_email_followup, schedule_email_followup, send_due_followups
from followup_recommendations import recommendation_snapshot
from whatsapp_followup import normalize_phone, schedule_whatsapp_followup, send_due_whatsapp_followups, whatsapp_config_issues

CONFIG = {"FOLLOWUP_WHATSAPP_ENABLED":"true", "WHATSAPP_ACCESS_TOKEN":"test-secret", "WHATSAPP_PHONE_NUMBER_ID":"123",
          "WHATSAPP_API_VERSION":"v99.0", "WHATSAPP_TEMPLATE_NAME":"namma_veedu_followup", "WHATSAPP_TEMPLATE_LANGUAGE":"en",
          "FOLLOWUP_PUBLIC_URL":"https://example.com"}


class WhatsAppFollowupTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name)/"queue.sqlite3"
        self.args = dict(user_id="qa",conversation_id="qa",recipient_phone="+91 98765 43210",customer_name="",
                         preference_summary="Chennai 2BHK",started_at=datetime.now(INDIA_TZ),consent=True,
                         recommendations="Saved listing A; recorded price ₹50 lakh; source https://example.com/a")

    def due(self, **changes):
        args = {**self.args,"initial_status":"scheduled",**changes}
        key = schedule_whatsapp_followup(**args,db_path=self.db)
        with _connect(self.db) as connection:
            connection.execute("UPDATE email_followups SET next_send_at=? WHERE id=?", ((datetime.now(INDIA_TZ)-timedelta(days=1)).isoformat(),key))
        return key

    def test_consent_normalization_dedup_and_channel_selection(self):
        self.assertEqual(normalize_phone(self.args["recipient_phone"]), "+919876543210")
        with self.assertRaises(ValueError):
            schedule_whatsapp_followup(**{**self.args,"consent":False},db_path=self.db)
        with self.assertRaises(ValueError):
            normalize_phone("9876543210")
        key=schedule_whatsapp_followup(**self.args,db_path=self.db)
        self.assertEqual(schedule_whatsapp_followup(**self.args,db_path=self.db),key)
        row,=list_email_followups("qa",self.db)
        self.assertEqual(row["channel"],"whatsapp")
        self.assertEqual(row["status"],"saved_pending_activation")
        self.assertIn("Saved listing A",row["recommendations"])

    def test_chat_collects_number_and_separate_consent(self):
        for request in ("text me on WhatsApp", "set a followup via WhatsApp"):
            first=followup_turn(request)
            consent=followup_turn("+91 98765 43210",first["state"])
            self.assertIsNone(consent["action"])
            self.assertIn("recommendations",consent["reply"])
            self.assertTrue(followup_turn("yes",consent["state"])["action"]["consent"])
            self.assertIsNone(followup_turn("no",consent["state"])["action"])
        self.assertTrue(followup_turn("stop WhatsApp followup")["cancel_saved"])

    def test_worker_sends_recommendations_once_and_reports_acceptance(self):
        key=self.due()
        response=Mock()
        response.json.return_value={"messages":[{"id":"wamid.test"}]}
        with patch("whatsapp_followup.requests.post",return_value=response) as post, patch("inquiry_log.update_conversation_fields"):
            self.assertEqual(send_due_whatsapp_followups(CONFIG,self.db),(1,0))
            self.assertEqual(send_due_whatsapp_followups(CONFIG,self.db),(0,0))
            payload=post.call_args.kwargs["json"]
            self.assertEqual(payload["to"],"919876543210")
            self.assertIn("Saved listing A",payload["template"]["components"][0]["parameters"][0]["text"])
            self.assertEqual(payload["template"]["components"][1]["parameters"][0]["text"],key)
            row,=list_email_followups("qa",self.db)
            self.assertEqual(row["status"],"accepted")
            self.assertEqual(row["provider_message_id"],"wamid.test")

    def test_cancelled_and_inactive_never_send_and_failures_do_not_retry(self):
        key=self.due()
        with patch("inquiry_log.update_conversation_fields"):
            self.assertTrue(cancel_email_followup(key,"qa",self.db))
        with patch("whatsapp_followup.requests.post") as post:
            self.assertEqual(send_due_whatsapp_followups(CONFIG,self.db),(0,0))
            post.assert_not_called()
        self.due(preference_summary="new")
        with patch("whatsapp_followup.requests.post",side_effect=TimeoutError("token must never be logged")) as post:
            self.assertEqual(send_due_whatsapp_followups(CONFIG,self.db),(0,1))
            self.assertEqual(send_due_whatsapp_followups(CONFIG,self.db),(0,0))
            self.assertEqual(post.call_count,1)
        self.assertTrue(whatsapp_config_issues({**CONFIG,"FOLLOWUP_WHATSAPP_ENABLED":"false"}))

    def test_email_worker_includes_recommendations_and_ignores_whatsapp(self):
        self.due()
        key=schedule_email_followup(user_id="qa",conversation_id="email",recipient_email="qa@example.com",customer_name="",preference_summary="Chennai",started_at=datetime.now(INDIA_TZ),max_messages=1,recommendations=self.args["recommendations"],db_path=self.db)
        with _connect(self.db) as connection:
            connection.execute("UPDATE email_followups SET next_send_at=? WHERE id=?", ((datetime.now(INDIA_TZ)-timedelta(days=1)).isoformat(),key))
        config={"FOLLOWUP_SMTP_HOST":"smtp.example.com","FOLLOWUP_SMTP_USERNAME":"qa","FOLLOWUP_SMTP_PASSWORD":"test","FOLLOWUP_SMTP_FROM":"qa@example.com","FOLLOWUP_PUBLIC_URL":"https://example.com"}
        with patch("followup_service.smtplib.SMTP") as smtp, patch("inquiry_log.update_conversation_fields"):
            self.assertEqual(send_due_followups(config,self.db),(1,0))
            message=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertIn("Saved listing A",message.get_content())
            self.assertIn("https://example.com/a",message.get_content())
        self.assertEqual(next(row for row in list_email_followups("qa",self.db) if row["channel"]=="whatsapp")["sent_count"],0)

    def test_recommendations_do_not_invent_matches_or_source_links(self):
        self.assertIn("No matching saved",recommendation_snapshot([],{"location":"Chennai"}))
        text=recommendation_snapshot([{"title":"A","source_url":"javascript:alert(1)"}],{})
        self.assertIn("Price not reported",text)
        self.assertNotIn("javascript:",text)
        self.assertIn("Source link not recorded",text)
        self.assertIn("Loans panel", text)

    def test_recommendation_snapshot_keeps_budget_range_and_selected_property(self):
        text = recommendation_snapshot(
            [{"title": "Customer choice", "location": "Chennai", "price_display": "₹55 lakh", "source_url": "https://example.com/chosen"}],
            {"min_budget": 1_500_000, "max_budget": 9_000_000},
        )
        self.assertIn("Minimum budget INR: 1500000", text)
        self.assertIn("Maximum budget INR: 9000000", text)
        self.assertIn("Customer choice", text)
        self.assertIn("https://example.com/chosen", text)

    def test_stop_link_works_after_meta_accepts_message(self):
        from followup_service import cancel_followup_from_link
        key = self.due()
        with _connect(self.db) as connection:
            connection.execute("UPDATE email_followups SET status='accepted' WHERE id=?", (key,))
        with patch("inquiry_log.update_conversation_fields"):
            self.assertTrue(cancel_followup_from_link(key, self.db))
        self.assertEqual(list_email_followups("qa", self.db)[0]["status"], "cancelled")

    def test_test_worker_skips_other_recipients_without_changing_their_queue(self):
        self.due()
        with patch("whatsapp_followup.requests.post") as post:
            self.assertEqual(send_due_whatsapp_followups(CONFIG,self.db,recipient_allowlist={"+919999999999"}),(0,0))
            post.assert_not_called()
        self.assertEqual(list_email_followups("qa",self.db)[0]["status"],"scheduled")

    def test_chat_and_manual_ui_persist_recommendations_and_popup(self):
        from streamlit.testing.v1 import AppTest
        import pandas as pd
        with ExitStack() as stack:
            for target,value in (("ai_config.select_ai_config",("offline","","")),("storage_backend._database_url",""),
                                 ("followup_service.cancel_user_followups",0),("inquiry_log.read_inquiries",[]),
                                 ("mira_learning_library.load_learning_rules",[])):
                stack.enter_context(patch(target,return_value=value))
            stack.enter_context(patch("inquiry_log.append_inquiry"))
            stack.enter_context(patch("inquiry_log.update_conversation_fields"))
            stack.enter_context(patch("whatsapp_followup.schedule_whatsapp_followup",side_effect=lambda **kw:schedule_whatsapp_followup(**kw,db_path=self.db)))
            stack.enter_context(patch("followup_service.list_email_followups",side_effect=lambda user:list_email_followups(user,self.db)))
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"),default_timeout=60).run()
            app.session_state["main_results"]=pd.DataFrame([{"title":"Chosen search listing","price_display":"₹50 lakh","source_url":"https://example.com/a"}])
            app.session_state["search_context"]={"location":"Chennai"}
            for message in ("followup on WhatsApp", "+919876543210", "yes"):
                app.session_state["pending_prompt"]=message
                app.run()
                self.assertFalse(app.exception)
            row,=list_email_followups(app.session_state["user_id"],self.db)
            self.assertIn("Chosen search listing",row["recommendations"])
            self.assertEqual(row["status"],"saved_pending_activation")
            self.assertEqual([item.value for item in app.toast],["Follow-up saved"])
            self.assertEqual(app.session_state["followup_schedule"]["method"],"WhatsApp")
            app.session_state["active_info_panel"]="followups"
            app.run()
            next(x for x in app.radio if x.label=="Follow-up method").set_value("WhatsApp follow-up").run()
            self.assertFalse(app.exception)
            self.assertTrue(any(x.label=="Your WhatsApp number (with country code)" for x in app.text_input))
