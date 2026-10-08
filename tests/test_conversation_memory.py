import unittest
import pandas as pd
from conversation_memory import update_preferences, contextual_reply


class ConversationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame({"city": ["Chennai", "Chennai"], "locality": ["Anna Nagar", "Adyar"]})

    def test_multi_turn_correction_and_question(self):
        memory = update_preferences("I need a quiet 3 BHK near Anna Nagar Chennai under 80 lakhs", self.data)
        self.assertEqual(memory["location"], "Anna Nagar")
        self.assertEqual(memory["bedrooms"], 3)
        memory = update_preferences("Actually I can do 70 lakh", self.data, memory)
        self.assertEqual(memory["max_budget"], 7_000_000)
        memory = update_preferences("What about schools nearby?", self.data, memory)
        self.assertEqual(memory["location"], "Anna Nagar")
        reply = contextual_reply("What about schools nearby?", memory)
        self.assertIn("70 lakh", reply)
        self.assertIn("don’t verify", reply)
        memory = update_preferences("Adyar instead", self.data, memory)
        self.assertEqual(memory["location"], "Adyar")
        self.assertEqual(memory["bedrooms"], 3)

    def test_removing_constraints_and_reset(self):
        memory = {"location": "Anna Nagar", "bedrooms": 3, "max_budget": 8_000_000}
        memory = update_preferences("Any area, no budget cap", self.data, memory)
        self.assertEqual(memory, {"bedrooms": 3})
        self.assertEqual(update_preferences("Start over", self.data, memory), {})

    def test_no_lifestyle_interception_for_search(self):
        self.assertIsNone(contextual_reply("Find a quiet 3 BHK", {}))

    def test_bedroom_wording(self):
        self.assertEqual(update_preferences("I need 3 bedrooms", self.data)["bedrooms"], 3)


if __name__ == "__main__":
    unittest.main()
