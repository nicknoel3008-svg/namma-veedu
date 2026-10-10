"""App-level coverage for the three result-panel starting actions."""
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class StartActionTests(unittest.TestCase):
    EXPECTED_HELP = {
        "⌂ Find a home": "Start a guided search using your location, budget, and home requirements.",
        "⚖ Explore auctions": "View saved bank-auction properties and verify their source details.",
        "☷ Set my preferences": "Choose your area, property type, BHK, budget, size, and listing type.",
    }

    def run_action(self, label):
        with patch("ai_config.select_ai_config", return_value=("offline", "", "")), \
             patch("storage_backend._database_url", return_value=""), \
             patch("inquiry_log.append_inquiry"), \
             patch("inquiry_log.update_conversation_fields"), \
             patch("followup_service.cancel_user_followups", return_value=0):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
            button = next(item for item in app.button if item.label == label)
            self.assertFalse(button.help)
            help_cards = [str(item.value) for item in app.markdown if str(item.value).startswith('<div class="start-option-help">')]
            self.assertEqual(len(help_cards), 3)
            self.assertTrue(any(self.EXPECTED_HELP[label] in card for card in help_cards))
            button.click().run()
            self.assertFalse(app.exception)
            return app

    def test_find_home_action_produces_a_guided_reply(self):
        app = self.run_action("⌂ Find a home")
        self.assertTrue(any(item.get("role") == "user" for item in app.session_state["chat"]))
        self.assertTrue(any(item.get("role") == "assistant" and item.get("mode") != "welcome" for item in app.session_state["chat"]))
        visible = " ".join(str(item.value) for item in app.markdown)
        self.assertIn("city or locality", visible.casefold())

    def test_explore_auctions_action_shows_results(self):
        app = self.run_action("⚖ Explore auctions")
        self.assertEqual(app.session_state["main_results_mode"], "chat")
        self.assertGreater(app.session_state["main_results_total_count"], 0)

    def test_set_preferences_action_starts_preference_collection(self):
        app = self.run_action("☷ Set my preferences")
        reply = app.session_state["chat"][-1]
        self.assertIn(reply.get("mode"), {"preference_setup", "gather_location"})
        self.assertIn("area", reply.get("content", "").casefold())
        visible = " ".join(str(item.value) for item in app.markdown)
        self.assertIn("preferences one at a time", visible.casefold())

    def test_each_active_action_can_be_selected_again_to_hide_its_result(self):
        for label in self.EXPECTED_HELP:
            app = self.run_action(label)
            active = next(item for item in app.button if item.label == f"✓ {label}")
            active.click().run()
            self.assertIsNone(app.session_state["main_start_action"], label)
            self.assertEqual(app.session_state["main_results_mode"], "none", label)
            self.assertFalse(any(item.label == f"✓ {label}" for item in app.button), label)


if __name__ == "__main__":
    unittest.main()
