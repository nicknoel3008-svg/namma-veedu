import unittest
from pathlib import Path
from io import BytesIO
from openpyxl import load_workbook
from purchase_assessment import assess
from inquiry_log import customer_summary_rows, build_inquiry_export


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"Conversation ID": "c", "User ID": "u", "User inquiry": "private text"}]

    def test_silence_is_unknown(self):
        result = assess(self.rows)
        self.assertEqual(result["Actual purchase outcome"], "Unknown")
        self.assertEqual(result["Purchase likelihood"], "Insufficient evidence")
        self.assertNotIn("private text", str(result))

    def test_strict_identity_and_property_rejection(self):
        visit = dict(conversation_id="c", user_id="other", purchase_intent="Interested", attended="Yes", satisfied="Yes")
        self.assertEqual(assess(self.rows, [visit])["Purchase likelihood"], "Insufficient evidence")
        visit.update(user_id="u", purchase_intent="Not interested")
        result = assess(self.rows, [visit])
        self.assertEqual(result["Actual purchase outcome"], "Unknown")
        self.assertNotEqual(result["Purchase likelihood"], "High interest")

    def test_verified_outcomes_separate_from_customer_reports(self):
        visit = dict(conversation_id="c", user_id="u", customer_purchase_confirmed_at="today")
        self.assertEqual(assess(self.rows, [visit])["Actual purchase outcome"], "Unknown")
        visit.update(purchase_outcome="Purchased", purchase_intent="Interested", attended="Yes", satisfied="Yes")
        result = assess(self.rows, [visit])
        self.assertIn("owner recorded", result["Actual purchase outcome"])
        self.assertIn("unvalidated", result["Prediction status"])

    def test_previous_conversation_for_same_user_is_linked(self):
        visit = dict(conversation_id="earlier", user_id="u", purchase_intent="Interested")
        self.assertEqual(assess(self.rows, [visit])["Purchase likelihood"], "Interest expressed")

    def test_export_contains_assessment_without_internal_payload(self):
        self.rows[0]["_assessment_choices"] = [dict(user_id="u", conversation_id="c", status="Selected")]
        row, = customer_summary_rows(self.rows)
        self.assertEqual(row["Purchase likelihood"], "Engaged—intent unknown")
        book = load_workbook(BytesIO(build_inquiry_export(self.rows, "All", "", "")))
        headers = [cell.value for cell in book["Inquiries"][1]]
        self.assertIn("Prediction status", headers)
        self.assertNotIn("_assessment_choices", headers)
        book.close()

    def test_owner_dashboard_links_history_and_shows_assessment(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).with_name("owner_dashboard_sandbox.py")), default_timeout=30)
        app.session_state.qa_inquiry_rows = [dict(self.rows[0], **{"Inquiry ID": "i", "Timestamp (Asia/Kolkata)": "2026-10-10T10:00:00+05:30"})]
        app.session_state.qa_journeys = [dict(user_id="u", conversation_id="older", property_title="Test home", purchase_intent="Interested", attended="Yes", satisfied="Yes")]
        app.run()
        self.assertFalse(app.exception)
        frames = [frame.value for frame in app.dataframe if "Purchase likelihood" in frame.value.columns]
        self.assertTrue(frames)
        self.assertEqual(frames[0].iloc[0]["Purchase likelihood"], "High interest")
