"""User journeys through Streamlit controls, with isolated external side effects."""
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class WebsiteJourneyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("ai_config.select_ai_config", return_value=("offline", "", "")))
        self.stack.enter_context(patch("storage_backend._database_url", return_value=""))
        self.saved = self.stack.enter_context(patch("inquiry_log.append_inquiry"))
        self.stack.enter_context(patch("inquiry_log.update_conversation_fields"))
        self.stack.enter_context(patch("followup_service.cancel_user_followups", return_value=0))
        self.stack.enter_context(patch("followup_service.list_email_followups", return_value=[]))
        self.app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
        self.assertFalse(self.app.exception)

    def button(self, label):
        return next(item for item in self.app.button if item.label == label)

    def send(self, text):
        composer = next(item for item in self.app.text_input if item.label == "Message Mira")
        composer.set_value(text)
        next(item for item in self.app.button if item.label in {"Send", "அனுப்பு"}).click().run()
        self.assertFalse(self.app.exception, text)
        last = self.app.session_state["chat"][-1]
        self.assertEqual(last["role"], "assistant")
        self.assertTrue(last["content"].strip())
        return last

    def test_search_refine_then_end_and_restart(self):
        self.send("Show me 2BHK flats in Chennai under 60 lakh")
        self.assertEqual(self.app.session_state["search_context"]["bedrooms"], 2)
        self.send("Keep my budget but change to 3BHK")
        context = self.app.session_state["search_context"]
        self.assertEqual(context["bedrooms"], 3)
        self.assertEqual(context["max_budget"], 6000000)
        self.button("End chat").click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.session_state["conversation_closed"])
        self.button("Start a new conversation").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.session_state["conversation_closed"])
        self.assertEqual(self.app.session_state["search_context"], {})

    def test_followup_missing_details_then_save_and_cancel_next(self):
        self.send("Set a followup")
        self.assertEqual(len(self.app.session_state["in_app_reminders"]), 0)
        last = self.send("tomorrow at 6 PM")
        self.assertEqual(last["mode"], "followup_saved")
        self.assertEqual(len(self.app.session_state["in_app_reminders"]), 1)
        self.send("Set another followup")
        self.send("cancel")
        self.assertEqual(len(self.app.session_state["in_app_reminders"]), 1)
        self.assertEqual(self.app.session_state["chat_followup"], {})

    def test_email_decline_then_resume_property_search(self):
        self.send("email me later")
        self.send("qa@example.com")
        self.send("no")
        self.assertEqual(self.app.session_state["chat_followup"], {})
        self.send("Show me plots in Chennai under 30 lakh")
        self.assertEqual(self.app.session_state["search_context"]["property_type"], "Plot")

    def test_information_panels_open_and_close(self):
        for label in ("🔨 Auction", "💰 Loans", "📐 Area & price", "🔎 Sources", "🔔 Follow-up"):
            with self.subTest(label=label):
                self.button(label).click().run()
                self.assertFalse(self.app.exception)
                self.assertIsNotNone(self.app.session_state["active_info_panel"])
                self.button("✓ " + label).click().run()
                self.assertFalse(self.app.exception)
                self.assertIsNone(self.app.session_state["active_info_panel"])

    def test_filter_controls_update_catalogue(self):
        checkbox = next(item for item in self.app.checkbox if item.label == "Flat")
        checkbox.check().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["main_results_mode"], "filters")
        cards = [str(item.value) for item in self.app.markdown if "grid-template-columns:repeat(auto-fit,minmax(145px,1fr))" in str(item.value)]
        self.assertGreater(len(cards), 0)
        self.assertTrue(all("Flat" in card for card in cards))

    def test_tamil_chat_reminder(self):
        reply = self.send("நாளை 10 AM நினைவூட்டுங்கள்")
        self.assertEqual(reply["mode"], "followup_saved")
        self.assertEqual(len(self.app.session_state["in_app_reminders"]), 1)

    def test_welcome_asks_language_and_chat_choice_updates_ui(self):
        welcome = self.app.session_state["chat"][0]["content"]
        self.assertIn("Namma Veedu", welcome)
        self.assertIn("English", welcome)
        self.assertIn("Tamil", welcome)
        self.send("Tamil")
        self.assertEqual(self.app.session_state["language"], "தமிழ்")
        self.assertEqual(self.app.session_state["customer_name"], "")
        self.assertEqual(self.app.session_state["buyer_memory"]["response_language"], "Tamil")
        self.send("I prefer English")
        self.assertEqual(self.app.session_state["language"], "English")

    def test_language_choice_preserves_pending_followup(self):
        self.send("Set a followup")
        self.send("Tamil")
        self.assertTrue(self.app.session_state["chat_followup"])
        self.send("நாளை 10 AM")
        self.assertEqual(len(self.app.session_state["in_app_reminders"]), 1)
        self.assertEqual([item.value for item in self.app.toast], ["Follow-up சேமிக்கப்பட்டது"])

    def test_tamil_language_popup(self):
        next(item for item in self.app.selectbox if item.label == "Language / மொழி").select("தமிழ்").run()
        self.assertFalse(self.app.exception)
        reply = self.send("நாளை 10 AM நினைவூட்டுங்கள்")
        self.assertEqual(reply["mode"], "followup_saved")
        self.assertEqual([item.value for item in self.app.toast], ["Follow-up சேமிக்கப்பட்டது"])

    def test_area_conversion_and_loan_emi(self):
        self.button("📐 Area & price").click().run()
        next(item for item in self.app.number_input if item.label == "Enter the area").set_value(100.0)
        next(item for item in self.app.selectbox if item.label == "Current unit").select("sq m").run()
        self.assertFalse(self.app.exception)
        metric = next(item for item in self.app.metric if item.label == "Area in square feet")
        self.assertIn("1,076.39", metric.value)
        self.button("💰 Loans").click().run()
        next(item for item in self.app.number_input if item.label == "Loan amount you have in mind (₹)").set_value(1000000.0)
        next(item for item in self.app.number_input if item.label == "Annual rate from a lender (%) — optional").set_value(8.0).run()
        self.assertFalse(self.app.exception)
        emi = next(item for item in self.app.metric if item.label == "Illustrative monthly EMI")
        self.assertEqual(emi.value, "₹8,364")

    def test_new_search_interrupts_followup_setup_in_ui(self):
        self.send("Set a followup")
        self.assertEqual(self.app.session_state["customer_name"], "")
        self.send("Show flats in Chennai under 60 lakh")
        self.assertEqual(self.app.session_state["chat_followup"], {})
        self.assertEqual(self.app.session_state["search_context"]["property_type"], "Flat")

    def test_manual_reminder_shows_saved_popup(self):
        self.button("🔔 Follow-up").click().run()
        summary = next(item for item in self.app.text_area if item.label == "What would you like to revisit?")
        summary.set_value("Review Chennai flats")
        self.button("Save follow-up").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.session_state["in_app_reminders"]), 1)
        self.assertEqual([item.value for item in self.app.toast], ["Follow-up saved"])

    def test_complete_and_remove_saved_reminder(self):
        self.send("remind me tomorrow at 6 PM")
        self.button("🔔 Follow-up").click().run()
        self.button("Mark complete").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["in_app_reminders"][0]["status"], "complete")
        self.assertEqual(self.app.session_state["followup_schedule"]["status"], "Completed")
        self.assertEqual(self.app.session_state["followup_schedule"]["next_at"], "")
        self.button("Remove").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["in_app_reminders"], [])
        self.assertEqual(self.app.session_state["followup_schedule"]["status"], "Removed")

    def test_chat_cancels_latest_saved_reminder(self):
        self.send("remind me tomorrow at 6 PM")
        self.send("cancel my followup")
        self.assertEqual(self.app.session_state["in_app_reminders"], [])
        self.assertEqual(self.app.session_state["followup_schedule"]["status"], "Removed")
        self.assertEqual(len(self.app.toast), 0)

    def test_completing_older_reminder_keeps_latest_schedule(self):
        self.send("remind me tomorrow at 6 PM about loans")
        self.send("remind me tomorrow at 6 PM about plots")
        latest_id = self.app.session_state["followup_schedule"]["reminder_id"]
        self.button("🔔 Follow-up").click().run()
        next(item for item in self.app.button if item.label == "Mark complete").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["followup_schedule"]["reminder_id"], latest_id)
        self.assertEqual(self.app.session_state["followup_schedule"]["status"], "Scheduled")

    def test_failed_email_save_has_no_success_popup(self):
        self.send("email me later")
        self.send("qa@example.com")
        with patch("followup_service.schedule_email_followup", side_effect=RuntimeError("QA simulated save failure")):
            reply = self.send("yes")
        self.assertNotEqual(reply["mode"], "followup_saved")
        self.assertEqual(len(self.app.toast), 0)
        self.assertIn("couldn’t save", reply["content"].casefold())

    def test_payment_question_preserves_purchase_budget(self):
        self.send("My budget is 45 lakh for a flat")
        self.send("Advance 2 lakh anuppa sollraanga, anuppalama? Romba urgent nu solraanga.")
        self.assertEqual(self.app.session_state["search_context"]["max_budget"], 4500000)
