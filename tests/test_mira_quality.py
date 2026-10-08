import unittest

from mira_quality import quality_flags
from inquiry_log import HEADERS


class MiraQualityTests(unittest.TestCase):
    def test_flags_frustration_and_missed_search_intent(self):
        flags = quality_flags({
            "User inquiry": "Do you have any options near Porur? You are not helpful.",
            "Assistant response": "I will remember Porur.",
            "Response type": "welcome",
        })
        self.assertIn("Customer frustration or dissatisfaction", flags)
        self.assertIn("Possible search intent not handled as a search", flags)

    def test_flags_no_result_without_marking_a_normal_reply(self):
        flags = quality_flags({
            "User inquiry": "Find a flat near Porur",
            "Assistant response": "I couldn't find a saved match.",
            "Response type": "results",
        })
        self.assertIn("No-result search", flags)
        self.assertEqual(quality_flags({"User inquiry": "Thanks", "Assistant response": "You are welcome.", "Response type": "local_talk"}), [])

    def test_review_fields_are_saved_in_the_private_owner_log(self):
        self.assertIn("Mira review status (owner)", HEADERS)
        self.assertIn("Mira corrected intent (owner)", HEADERS)
        self.assertIn("Mira review notes (owner)", HEADERS)
