import unittest
import pandas as pd
import json
from types import SimpleNamespace
from unittest.mock import patch
from agent_runtime import run_openai_agent
from agent import parse_request
from buyer_memory import (update_buyer_memory, record_detail_reply, feature_evidence,
    prepare_inventory, enforce_search_args, grounded_search_reply, resolve_reference)
from property_search import search_properties


class BuyerMemoryTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"property_id": "a", "title": "First home", "price_inr": 6000000, "city": "Chennai", "locality": "Anna Nagar", "property_type": "Flat", "bedrooms": 3, "listing_status": "Existing sale", "source_status": "saved", "price_per_sqm_inr": 100, "amenities": "no covered parking; balcony", "car_parking": "No"},
            {"property_id": "b", "title": "Second home", "price_inr": 7000000, "city": "Chennai", "locality": "Anna Nagar", "property_type": "Flat", "bedrooms": 3, "listing_status": "Existing sale", "source_status": "saved", "price_per_sqm_inr": 200, "amenities": "fitness centre; garden", "car_parking": "Covered"},
            {"property_id": "c", "title": "Third home", "price_inr": 9000000, "city": "Chennai", "locality": "Adyar", "property_type": "Flat", "bedrooms": 2, "listing_status": "Existing sale", "source_status": "saved", "price_per_sqm_inr": 300, "amenities": "", "car_parking": "Not specified"},
        ]
        self.chat = [{"role": "assistant", "mode": "results", "records": self.records}]
        self.requirements = {"location": "Anna Nagar", "bedrooms": 3, "max_budget": 8000000}

    def test_selected_property_survives_followup(self):
        memory = update_buyer_memory("the second one", self.requirements, self.chat)
        self.assertEqual(memory["selected"]["property_id"], "b")
        memory = update_buyer_memory("does that have parking?", self.requirements, self.chat, memory)
        reply = record_detail_reply("does that have parking?", memory, self.records)
        self.assertIn("Second home", reply)
        self.assertIn("mentions parking", reply)

    def test_ambiguous_reference_asks(self):
        memory = update_buyer_memory("does that have parking?", {}, self.chat)
        self.assertEqual(record_detail_reply("does that have parking?", memory, self.records), "Which listing do you mean?")

    def test_comparison_reports_missing_fields(self):
        reply = record_detail_reply("compare these", {}, self.records)
        self.assertIn("Second home", reply)
        self.assertIn("area not reported", reply)
        self.assertIn("unknown", reply)

    def test_rejection_and_reconsider(self):
        memory = update_buyer_memory("skip the second one", self.requirements, self.chat)
        found = prepare_inventory(pd.DataFrame(self.records), memory)
        self.assertNotIn("b", found.property_id.tolist())
        memory = update_buyer_memory("reconsider the second one", self.requirements, self.chat, memory)
        self.assertEqual(memory["rejected"], [])

    def test_preferences_corrections_separate(self):
        memory = update_buyer_memory("I prefer a garden", self.requirements, self.chat)
        changed = {**self.requirements, "max_budget": 7000000}
        memory = update_buyer_memory("Actually 70 lakh", changed, self.chat, memory)
        self.assertEqual(memory["preferences"], {"garden": "prefer"})
        self.assertEqual(memory["requirements"]["bedrooms"], 3)
        self.assertEqual(memory["corrections"][-1]["after"], 7000000)

    def test_semantic_matching_and_unknown(self):
        self.assertEqual(feature_evidence(self.records[1], "gym"), "recorded")
        self.assertEqual(feature_evidence(self.records[0], "parking"), "absent")
        self.assertEqual(feature_evidence(self.records[2], "parking"), "unknown")
        self.assertEqual(feature_evidence(self.records[1], "schools"), "unknown")

    def test_preference_does_not_relax_hard_filters(self):
        memory = {"preferences": {"gym": "prefer"}}
        found = prepare_inventory(pd.DataFrame(self.records), memory)
        found = search_properties(found, location="Anna Nagar", bedrooms=3, max_budget=8000000)
        found = found.sort_values("_preference_score", ascending=False, kind="stable")
        self.assertEqual(found.property_id.tolist(), ["b", "a"])

    def test_tool_cannot_relax_requirements(self):
        args = enforce_search_args({"city": "", "bedrooms": 0, "max_budget_inr": 0}, self.requirements)
        self.assertEqual(args["city"], "Anna Nagar")
        self.assertEqual(args["bedrooms"], 3)
        self.assertEqual(args["max_budget_inr"], 8000000)

    def test_mandatory_amenity_excludes_unknown_and_absent(self):
        memory = update_buyer_memory("I must have parking", self.requirements, self.chat)
        self.assertEqual(memory["preferences"]["parking"], "required")
        found = prepare_inventory(pd.DataFrame(self.records), memory)
        self.assertEqual(found.property_id.tolist(), ["b"])

    def test_grounded_response_marks_unknown_preference(self):
        reply = grounded_search_reply({"records": self.records[:1]}, {"preferences": {"quiet": "prefer"}})
        self.assertIn("quiet: not confirmed", reply)
        self.assertIn("₹60 lakh", reply)

    def test_starting_price_is_not_presented_as_unit_price(self):
        record = {**self.records[0], "price_basis": "Starting price", "price_display": "₹60 lakh onwards", "listing_status": "Project reference"}
        reply = grounded_search_reply({"records": [record]}, {})
        self.assertIn("Starting price: ₹60 lakh onwards", reply)
        self.assertIn("Project reference", reply)

    def test_negative_type_and_new_conversation(self):
        self.assertEqual(parse_request("I want a flat, not a plot", pd.DataFrame(self.records)).property_type, "Flat")
        memory = update_buyer_memory("skip the second one", self.requirements, self.chat)
        memory = update_buyer_memory("start over", {}, [], memory)
        self.assertIsNone(memory["selected"])
        self.assertEqual(memory["rejected"], [])

    def test_runtime_corrects_relaxed_tool_filters_and_generated_claims(self):
        args = {"city": "", "property_type": "Any", "bedrooms": 0, "record_kind": "Any", "max_budget_inr": 0, "min_area_sqm": 0, "limit": 3}
        value = {"type": "function_call", "name": "search_saved_properties", "arguments": json.dumps(args), "call_id": "search-1"}
        call = SimpleNamespace(**value, model_dump=lambda **kwargs: value)
        responses = [SimpleNamespace(output=[call], output_text=""), SimpleNamespace(output=[], output_text="All homes are quiet and available now.")]
        with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=lambda **kwargs: object())}), patch("agent_runtime._groq_response", side_effect=responses):
            turn = run_openai_agent(text="Find homes", history=[], properties=pd.DataFrame(self.records), sources=pd.DataFrame(), api_key="test", provider="groq",
                buyer_context={"buyer_memory": {"requirements": self.requirements, "preferences": {"quiet": "prefer"}, "rejected": ["a"]}})
        self.assertEqual([row["property_id"] for row in turn.tool_results[0].data["records"]], ["b"])
        self.assertIn("quiet: not confirmed", turn.text)
        self.assertNotIn("available now", turn.text)

    def test_new_shortlist_and_invalid_ordinal_clear_selection(self):
        memory = update_buyer_memory("second one", {}, self.chat)
        memory = update_buyer_memory("third one", {}, [{"role": "assistant", "mode": "results", "records": self.records[:1]}], memory)
        self.assertIsNone(memory["selected"])
