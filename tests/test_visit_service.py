import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from agent_runtime import INDIA_TZ
from visit_service import request_visit, list_visit_requests, update_visit_status, confirmed_visit_times


class VisitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "visits.sqlite3"
        self.when = (datetime.now(INDIA_TZ) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        self.record = {"property_id": "test-property", "title": "Test home", "source_url": "https://example.com/home"}
        self.args = dict(record=self.record, user_id="customer", visit_at=self.when, slot_kind="Predefined slot", customer_name="Test", contact_method="Email", contact_value="test@example.com", consent=True, db_path=self.db)

    def test_fixed_and_custom_requests_are_pending_and_private(self):
        first = request_visit(**self.args)
        self.assertEqual(request_visit(**self.args), first)
        second = request_visit(**{**self.args, "visit_at": self.when + timedelta(hours=1), "slot_kind": "Custom time", "contact_method": "WhatsApp", "contact_value": "+91 9876543210"})
        rows = list_visit_requests("customer", self.db)
        self.assertEqual({r["slot_kind"] for r in rows}, {"Predefined slot", "Custom time"})
        self.assertTrue(all(r["status"] == "Requested" for r in rows))
        self.assertEqual(list_visit_requests("other", self.db), [])
        self.assertFalse(update_visit_status(second, "Cancelled", user_id="other", db_path=self.db))
        with self.assertRaises(ValueError):
            update_visit_status(first, "Confirmed", user_id="customer", db_path=self.db)

    def test_confirmation_blocks_conflicts_and_cancellation_releases_slot(self):
        first = request_visit(**self.args)
        second = request_visit(**{**self.args, "user_id": "other"})
        update_visit_status(first, "Confirmed", db_path=self.db)
        self.assertEqual(confirmed_visit_times(self.record, self.when.date(), self.db), {"10:00"})
        with self.assertRaises(ValueError):
            update_visit_status(second, "Confirmed", db_path=self.db)
        with self.assertRaises(ValueError):
            request_visit(**{**self.args, "user_id": "third"})
        update_visit_status(first, "Cancelled", user_id="customer", db_path=self.db)
        self.assertEqual(confirmed_visit_times(self.record, self.when.date(), self.db), set())
        self.assertTrue(update_visit_status(second, "Confirmed", db_path=self.db))

    def test_invalid_contact_consent_and_past_time_are_rejected(self):
        for changes in ({"consent": False}, {"customer_name": ""}, {"visit_at": self.when - timedelta(days=5)}, {"contact_value": "invalid"}, {"contact_method": "WhatsApp", "contact_value": "9876543210"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                request_visit(**{**self.args, **changes})

    def test_customer_dialog_supports_both_slot_types(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).parent / "website_sandbox.py"), default_timeout=60).run()
        app.session_state["visit_property"] = self.record
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(x.label == "Slot (IST)" for x in app.selectbox))
        next(x for x in app.radio if x.label == "Choose a visit time").set_value("Custom time").run()
        self.assertFalse(app.exception)
        self.assertTrue(any(x.label == "Requested time (IST)" for x in app.time_input))
        next(x for x in app.text_input if x.key == "visit_customer_name").set_value("Test customer")
        next(x for x in app.text_input if x.key == "visit_contact_value").set_value("qa@example.com")
        next(x for x in app.checkbox if x.key == "visit_consent").check()
        next(x for x in app.button if x.label == "Request visit").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("pending owner confirmation" in x.value for x in app.success))
