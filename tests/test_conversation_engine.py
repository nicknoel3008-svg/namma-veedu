from datetime import datetime
from zoneinfo import ZoneInfo
import unittest
import pandas as pd
from audit_mira_conversation import MESSAGES
from conversation_engine import conversational_turn, response_language
from property_search import load_properties
from buyer_memory import prepare_inventory


class ConversationEngineTests(unittest.TestCase):
    def test_commute_space_advice_preserves_preferences_and_evidence_limits(self):
        context = {"location": "Chennai", "bedrooms": 3, "max_budget": 6000000, "property_type": "Flat"}
        turn = conversational_turn(
            "How should I balance a shorter commute with extra living space for my parents?",
            self.data, [], context=context,
        )
        self.assertEqual(turn["intent"], "commute_space_tradeoff")
        self.assertEqual(turn["context"], context)
        self.assertIn("do not verify commute", turn["reply"])
        self.assertIn("add charges", turn["reply"])
        self.assertNotIn("15", turn["reply"])
        self.assertFalse(turn.get("search"))
        self.assertEqual(turn["reply"].count("?"), 1)

    @classmethod
    def setUpClass(cls):
        cls.data = load_properties()

    def test_entire_mixed_language_conversation_without_provider(self):
        context, memory, chat = {}, {}, []
        replies = []
        for index, text in enumerate(MESSAGES, 1):
            turn = conversational_turn(text, self.data, chat, context, memory,
                now=datetime(2026, 10, 8, 10, tzinfo=ZoneInfo("Asia/Kolkata")))
            context, memory = turn["context"], turn["memory"]
            self.assertTrue(turn.get("reply"), f"Turn {index} was not handled")
            replies.append(turn)
            chat.extend([{"role": "user", "content": text}, {"role": "assistant", "content": turn["reply"]}])
            if index >= 5:
                self.assertTrue(memory["avoid_ground_floor"])
                self.assertEqual(memory["preferences"]["lift"], "required")
            if index >= 3:
                self.assertEqual(context["max_budget"], 4500000)
        self.assertEqual(replies[7]["memory"]["response_language"], "Tamil")
        self.assertEqual(replies[8]["memory"]["response_language"], "Tanglish")
        self.assertEqual(memory["workplace"], "Taramani")
        self.assertEqual(memory["facing"], "East")
        self.assertEqual(replies[16]["intent"], "payment_concern")
        self.assertIn("2026-10-09T18:00", replies[18]["reminder_due"])
        self.assertTrue(replies[19]["close"])

    def test_hard_constraints_exclude_unknown_floor_and_lift(self):
        sample = pd.DataFrame([
            {"title": "Ground", "floor_number": "0", "amenities": "lift", "facing": "East"},
            {"title": "Unknown", "floor_number": "", "amenities": "lift", "facing": "East"},
            {"title": "No lift", "floor_number": "2", "amenities": "", "facing": "East"},
            {"title": "West", "floor_number": "2", "amenities": "lift", "facing": "West"},
            {"title": "Match", "floor_number": "2", "amenities": "lift", "facing": "East"},
        ])
        found = prepare_inventory(sample, {"avoid_ground_floor": True, "facing": "East", "preferences": {"lift": "required", "hospital_access": "verify"}})
        self.assertEqual(found["title"].tolist(), ["Match"])

    def test_language_persists_and_can_switch_back(self):
        self.assertEqual(response_language("English only please", "Tanglish"), "English")
        self.assertEqual(response_language("Maintenance evlo?", "Tamil"), "Tamil")

    def test_human_guidance_scenarios_from_customer_library(self):
        scenarios = {
            "Explain freehold versus leasehold ownership simply.": "ownership_education",
            "How do leasehold duration and renewal affect a buyer?": "ownership_education",
            "Please compare fixed and floating interest rates without quoting a rate.": "loan_rate_education",
            "I want to buy a flat but I don't know anything about the process.": "first_time_buyer",
            "Just looking around, not sure what I want.": "exploring",
            "Need a flat. Fast.": "urgent_search",
            "What all can you help me with?": "scope",
            "My salary is 85k. Can I afford a 60 lakh home?": "affordability",
            "Should I stretch my budget for a better flat?": "budget_tradeoff",
            "Which bank should I take the loan from?": "loan_education",
            "My CIBIL score is low. Will my loan be rejected?": "credit_guidance",
            "Is the title for this flat clear? Please confirm.": "legal_verification",
            "The builder is showing a model flat. Will mine look the same?": "project_due_diligence",
            "House hunting is exhausting and I am overwhelmed.": "emotional_support",
            "Is it still available?": "availability",
            "How much will stamp duty and registration cost?": "current_costs",
            "Are you sure, or are you giving random answers?": "trust_boundary",
        }
        for text, expected_intent in scenarios.items():
            turn = conversational_turn(text, self.data, [], {}, {}, now=datetime(2026, 10, 8, 10, tzinfo=ZoneInfo("Asia/Kolkata")))
            self.assertEqual(turn["intent"], expected_intent, text)
            self.assertTrue(turn["reply"], text)

    def test_human_guidance_preserves_tanglish(self):
        turn = conversational_turn("House hunting romba stress-aa irukku", self.data, [], {}, {"response_language": "Tanglish"})
        self.assertEqual(turn["intent"], "emotional_support")
        self.assertIn("puriyudhu", turn["reply"])

    def test_gratitude_removal_email_and_feedback_requests_are_acknowledged(self):
        thank_you = conversational_turn("Thanks Mira, that was a great suggestion", self.data, [], {}, {})
        self.assertEqual(thank_you["intent"], "appreciation")
        self.assertIn("Thank you", thank_you["reply"])

        chat = [{"role": "assistant", "mode": "results", "records": [{"property_id": "one", "title": "Saved flat"}]}]
        remove = conversational_turn("Please remove those previous suggestions", self.data, chat, {}, {})
        self.assertEqual(remove["intent"], "remove_suggestions")
        self.assertIn("one", remove["memory"]["rejected"])

        email = conversational_turn("Please share these suggestions to my email", self.data, [], {}, {})
        self.assertEqual(email["intent"], "email_followup_request")
        self.assertTrue(email["open_followups"])

        disappointed = conversational_turn("This is not helpful", self.data, [], {}, {})
        self.assertEqual(disappointed["intent"], "feedback_offer")
        self.assertTrue(disappointed["offer_feedback"])
