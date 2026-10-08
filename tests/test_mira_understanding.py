import unittest
from property_search import load_properties
from mira_understanding import understand_request, website_context
from agent_runtime import dispatch_tool
import pandas as pd


class MiraUnderstandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_properties()

    def route(self, text, context=None, chat=None, memory=None):
        return understand_request(text, self.data, chat or [], context, memory)

    def test_budget_question_searches_without_reasking_budget(self):
        result = self.route("do you have any property around 20 lakhs, i don't have any other preferance", {"location": "Ambattur", "property_type": "Flat"})
        self.assertEqual(result["context"]["max_budget"], 2000000)
        self.assertNotIn("location", result["context"])
        self.assertTrue((result["results"]["price_inr"] <= 2000000).all())

    def test_greetings_never_search_with_existing_preferences(self):
        for text in ("Hi", "hi!", "Hello Mira", "vanakkam", "வணக்கம்"):
            result = self.route(text, {"location": "Avadi", "max_budget": 2000000})
            self.assertTrue(result["greeting"])
            self.assertNotIn("results", result)
            self.assertEqual(result["context"]["location"], "Avadi")
        result = self.route("Hi, do you have a flat in Avadi?")
        self.assertIn("results", result)

    def test_options_and_suggestions_are_search_requests(self):
        result = self.route("do you have any options near Porur")
        self.assertIn("results", result)
        self.assertEqual(result["context"]["location"].casefold(), "porur")
        result = self.route("I live in Porur; do you have any property suggestion")
        self.assertIn("results", result)
        self.assertEqual(result["context"]["location"].casefold(), "porur")

    def test_just_a_location_replaces_stale_search_constraints(self):
        result = self.route(
            "no, just Porur",
            {"location": "Chennai", "property_type": "Flat", "bedrooms": 3, "max_budget": 4_500_000},
        )
        self.assertIn("results", result)
        self.assertEqual(result["context"], {"location": "Porur"})

    def test_rejected_location_and_brand_are_excluded(self):
        result = self.route("ignore ambattur", {"location": "Ambattur", "max_budget": 3000000})
        self.assertEqual(result["context"]["location"], "")
        self.assertFalse(result["results"].astype(str).apply(lambda column: column.str.contains("ambattur", case=False)).any().any())
        result = self.route("not vgn")
        self.assertFalse(result["results"]["title"].str.contains("vgn", case=False).any())

    def test_cheapest_requires_a_known_positive_price(self):
        result = self.route("show me list ot properly with minimum value")
        prices = result["results"]["price_inr"]
        self.assertTrue(prices.notna().all())
        self.assertTrue((prices > 0).all())
        self.assertTrue(prices.is_monotonic_increasing)

    def test_plural_amenities_and_distance_concern(self):
        records = self.data.head(3).to_dict("records")
        chat = [{"role": "assistant", "mode": "results", "records": records}]
        result = self.route("what is the basic amenities these properties have", chat=chat)
        self.assertTrue(all(row["title"] in result["reply"] for row in records))
        result = self.route("sriperumbudur is far from my location", chat=chat)
        self.assertIn("Which city", result["reply"])
        self.assertNotIn("results", result)
        next_turn = self.route("is there a flat in Avadi for purchase?", context=result["context"], chat=chat, memory=result["memory"])
        self.assertIn("results", next_turn)

    def test_full_inventory_lookup_and_website_context(self):
        result = self.route("VGN Lily Pond")
        self.assertIn("VGN Lily Pond", result["reply"])
        source = self.route("guide me to the official portal", memory=result["memory"])
        self.assertIn(result["memory"]["selected"]["source_url"], source["reply"])
        self.assertIsNone(self.route("calculate EMI for 20 lakhs"))
        details = dispatch_tool("get_saved_property_details", {"query": "VGN Lily Pond"}, self.data, pd.DataFrame())
        self.assertGreater(details.data["count"], 0)
        self.assertIn("approval_number", details.data["records"][0])
        self.assertEqual(website_context(self.data)["saved_record_count"], len(self.data))
