import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from chat_followup import followup_turn, TZ


class ChatFollowupTests(unittest.TestCase):
    now = datetime(2026, 10, 9, 12, tzinfo=TZ)

    def turn(self, text, state=None):
        return followup_turn(text, state, now=self.now)

    def test_save_direct_request_and_same_weekday(self):
        for text in ("follow up today at 6 PM", "remind me Friday at 6 PM"):
            self.assertEqual(self.turn(text)["action"]["due_at"], "2026-10-09T18:00+05:30")

    def test_collect_missing_time_and_accept_correction(self):
        state = self.turn("follow up at 10 AM")["state"]
        self.assertEqual(self.turn("tomorrow at 6 PM", state)["action"]["due_at"], "2026-10-10T18:00+05:30")

    def test_email_requires_address_and_consent(self):
        state = self.turn("email me later")["state"]
        consent = self.turn("buyer@example.com", state)
        self.assertIsNone(consent["action"])
        self.assertEqual(self.turn("yes", consent["state"])["action"]["email"], "buyer@example.com")
        self.assertEqual(self.turn("no", consent["state"])["state"], {})

    def test_regular_sharing_does_not_start_email(self):
        self.assertIsNone(self.turn("share these results"))

    def test_declining_followup_does_not_start_setup(self):
        for text in ("no followup please", "no reminders", "no more followups"):
            self.assertEqual(self.turn(text)["state"], {})
            self.assertIsNone(self.turn(text)["action"])

    def test_cancel_saved_request_is_distinct_from_pending_setup(self):
        self.assertTrue(self.turn("cancel my followup")["cancel_saved"])
        self.assertFalse(self.turn("cancel my followup", self.turn("set a followup")["state"])["cancel_saved"])

    def test_new_search_can_interrupt_setup(self):
        state = self.turn("followup")["state"]
        self.assertTrue(self.turn("show flats in Chennai", state)["resume"])

    def test_24_hour_time(self):
        self.assertEqual(self.turn("remind me tomorrow at 18:30")["action"]["due_at"], "2026-10-10T18:30+05:30")

    def test_24_hour_correction_replaces_earlier_time(self):
        state = self.turn("followup at 10 AM")["state"]
        self.assertEqual(self.turn("tomorrow at 18:30", state)["action"]["due_at"], "2026-10-10T18:30+05:30")

    def test_past_weekday_time_moves_to_next_week(self):
        self.assertEqual(self.turn("remind me Friday at 10:00")["action"]["due_at"], "2026-10-16T10:00+05:30")

    def test_next_friday_does_not_schedule_today(self):
        self.assertEqual(self.turn("follow up next Friday at 6 PM")["action"]["due_at"], "2026-10-16T18:00+05:30")

    def test_after_three_days(self):
        self.assertEqual(self.turn("follow up after 3 days at 10 AM")["action"]["due_at"], "2026-10-12T10:00+05:30")

    def test_next_week(self):
        self.assertEqual(self.turn("remind me next week at 10 AM")["action"]["due_at"], "2026-10-16T10:00+05:30")

    def test_new_day_replaces_previous_day(self):
        state = self.turn("followup tomorrow")["state"]
        self.assertEqual(self.turn("Sunday at 6 PM", state)["action"]["due_at"], "2026-10-11T18:00+05:30")

    def test_switch_email_to_in_app(self):
        state = self.turn("email me later")["state"]
        result = self.turn("use an in-app reminder tomorrow at 10 AM", state)
        self.assertEqual(result["action"]["method"], "in_app")

    def test_switch_in_app_to_email_with_address(self):
        state = self.turn("set a followup")["state"]
        result = self.turn("email qa@example.com", state)
        self.assertEqual(result["state"]["method"], "email")
        self.assertIsNone(result["action"])
        self.assertEqual(self.turn("yes", result["state"])["action"]["email"], "qa@example.com")

    def test_past_time_and_invalid_date_do_not_save(self):
        self.assertIsNone(self.turn("remind me today at 10 AM")["action"])
        self.assertIsNone(self.turn("remind me 2026-13-40 at 10 AM")["action"])

    def test_out_of_range_relative_date_does_not_crash(self):
        for days in ("999999999999", "9999999"):
            with self.subTest(days=days):
                result = self.turn(f"remind me in {days} days at 10 AM")
                self.assertIsNone(result["action"])
                self.assertIn("When", result["reply"])

    def test_website_chat_saves_reminder_without_opening_form(self):
        from streamlit.testing.v1 import AppTest
        with patch("ai_config.select_ai_config", return_value=("offline", "", "")), \
             patch("inquiry_log.append_inquiry"), \
             patch("inquiry_log.update_conversation_fields"), \
             patch("followup_service.cancel_user_followups", return_value=0):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
            app.session_state["pending_prompt"] = "remind me tomorrow at 10 AM"
            app.run()
            self.assertFalse(app.exception)
            reminders = app.session_state["in_app_reminders"]
            self.assertEqual(len(reminders), 1)
            self.assertEqual(reminders[0]["status"], "saved")
            self.assertEqual(app.session_state["chat"][-1]["mode"], "followup_saved")
            self.assertNotEqual(app.session_state["active_info_panel"], "followups")
            self.assertEqual([item.value for item in app.toast], ["Follow-up saved"])

    def test_website_email_saves_under_current_conversation(self):
        from streamlit.testing.v1 import AppTest
        with patch("ai_config.select_ai_config", return_value=("offline", "", "")), \
             patch("inquiry_log.append_inquiry"), \
             patch("inquiry_log.update_conversation_fields"), \
             patch("followup_service.cancel_user_followups", return_value=0), \
             patch("followup_service.schedule_email_followup", return_value="test-email") as save, \
             patch("followup_service.list_email_followups", return_value=[{"id": "test-email", "next_send_at": "2026-11-01T10:00:00+05:30"}]):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
            for message in ("email me later", "buyer@example.com"):
                app.session_state["pending_prompt"] = message
                app.run()
                self.assertFalse(app.exception)
                save.assert_not_called()
                self.assertEqual(len(app.toast), 0)
            app.session_state["pending_prompt"] = "yes"
            app.run()
            self.assertFalse(app.exception)
            save.assert_called_once()
            self.assertEqual(save.call_args.kwargs["conversation_id"], app.session_state["inquiry_conversation_id"])
            self.assertEqual(app.session_state["chat"][-1]["mode"], "followup_saved")
            self.assertEqual([item.value for item in app.toast], ["Follow-up saved"])
