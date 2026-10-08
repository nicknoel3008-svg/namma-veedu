import tempfile
import unittest
from pathlib import Path

from mira_learning_library import active_learning_guidance, load_learning_rules, merge_suggested_drafts, save_learning_rules, suggested_draft_rules


class MiraLearningLibraryTests(unittest.TestCase):
    def test_first_load_creates_editable_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            rules = load_learning_rules(path)
            self.assertTrue(path.exists())
            self.assertGreaterEqual(len(rules), 5)
            self.assertTrue(active_learning_guidance(rules))

    def test_only_approved_rules_reach_mira(self):
        with tempfile.TemporaryDirectory() as directory:
            rules = save_learning_rules([
                {"Scenario": "Approved case", "Guidance": "Use the helpful response.", "Status": "Approved"},
                {"Scenario": "Draft case", "Guidance": "Do not use this yet.", "Status": "Draft"},
            ], Path(directory) / "library.json")
            guidance = active_learning_guidance(rules)
            self.assertEqual(len(guidance), 1)
            self.assertIn("Approved case", guidance[0])

    def test_recurring_quality_cues_create_a_draft_only_once(self):
        rows = [
            {"User inquiry": "You are not helpful", "Assistant response": "Here is an answer.", "Response type": "welcome"},
            {"User inquiry": "This is not helpful", "Assistant response": "Here is another answer.", "Response type": "welcome"},
        ]
        drafts = suggested_draft_rules(rows)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["Status"], "Draft")
        merged, added = merge_suggested_drafts([], drafts)
        self.assertEqual(added, 1)
        merged, added = merge_suggested_drafts(merged, drafts)
        self.assertEqual(added, 0)
