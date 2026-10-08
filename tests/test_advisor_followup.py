import unittest
from advisor_followup import advisor_reply


class AdvisorFollowupTests(unittest.TestCase):
    def test_offer_help_before_callback(self):
        state, message = advisor_reply("I want a human", handoff=True)
        self.assertEqual(state["stage"], "offer_help")
        self.assertIn("help another way", message)
        state, message = advisor_reply("Explain this listing", state)
        self.assertEqual(state, {})
        self.assertIsNone(message)

    def test_callback_requires_explicit_confirmation(self):
        state, _ = advisor_reply("human please", handoff=True)
        for message in ("callback please", "email", "test@example.com", "Tomorrow afternoon"):
            state, response = advisor_reply(message, state)
            self.assertNotEqual(state["stage"], "confirmed")
        self.assertEqual(state["stage"], "confirm")
        state, response = advisor_reply("yes", state)
        self.assertEqual(state["stage"], "confirmed")
        self.assertIn("isn’t a confirmed appointment", response)

    def test_cancel_and_switch_back_to_help(self):
        state, _ = advisor_reply("human please", handoff=True)
        state, _ = advisor_reply("callback", state)
        self.assertEqual(advisor_reply("cancel", state)[0], {})
        self.assertEqual(advisor_reply("help me instead", state)[0], {})

    def test_tamil_and_invalid_contact(self):
        state, message = advisor_reply("human", tamil=True, handoff=True)
        self.assertIn("வேறு வழியில்", message)
        state, _ = advisor_reply("callback", state)
        state, _ = advisor_reply("phone", state)
        state, _ = advisor_reply("not-a-number", state)
        self.assertEqual(state["stage"], "contact")
