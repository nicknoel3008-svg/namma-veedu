"""Local dashboard response timings; no production writes or email delivery."""
from contextlib import ExitStack
from datetime import datetime
import json
from pathlib import Path
from time import perf_counter
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class DashboardPerformanceTests(unittest.TestCase):
    def test_mira_rating_uses_latest_per_conversation_and_excludes_invalid(self):
        app = AppTest.from_file(str(ROOT / "tests" / "owner_dashboard_sandbox.py"), default_timeout=60).run()
        app.session_state["qa_inquiry_rows"] = [
            {"Conversation ID": "a", "Mira performance rating (1-5)": 1},
            {"Conversation ID": "a", "Mira performance rating (1-5)": 5},
            {"Conversation ID": "b", "Mira performance rating (1-5)": 3},
            {"Conversation ID": "invalid", "Mira performance rating (1-5)": 9},
            {"Conversation ID": "unrated", "User satisfaction rating (1-5)": 1},
        ]
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(next(item.value for item in app.metric if item.label == "Mira rating"), "4.0 / 5")

    def test_saved_mira_followup_counts_once_in_dashboard(self):
        app = AppTest.from_file(str(ROOT / "tests" / "owner_dashboard_sandbox.py"), default_timeout=60).run()
        today = datetime.now().strftime("%Y-%m-%d")
        app.session_state["qa_inquiry_rows"] = [
            {"Inquiry ID": f"test-{i}", "Conversation ID": "qa-followup", "User ID": "qa-user",
             "Timestamp (Asia/Kolkata)": today + "T10:00:00+05:30", "Follow-up method": "In-app reminder",
             "Follow-up schedule status": "Scheduled", "Follow-up summary": "Check parking",
             "Customer interest (owner)": "Interested", "Matching records": 3, "User satisfaction rating (1-5)": 2,
             "Mira performance rating (1-5)": 4,
             "Next follow-up time (Asia/Kolkata)": today + "T18:00:00+05:30"} for i in range(2)]
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(next(item.value for item in app.metric if item.label == "Follow-ups open"), "1")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Conversations"), "1")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Confirmed interested leads"), "1")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Search match rate"), "100%")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Mira rating"), "4.0 / 5")
        self.assertTrue(any("Customer satisfaction: 2.0 / 5" in item.value for item in app.caption))
        self.assertEqual(next(item.value for item in app.selectbox if item.label == "Automatic snapshot date"), today)

    def test_owner_dashboard_flowchart_and_empty_counts(self):
        started = perf_counter()
        app = AppTest.from_file(str(ROOT / "tests" / "owner_dashboard_sandbox.py"), default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.value == "Mira Studio" for item in app.title))
        self.assertTrue(any(item.label == "Website Blueprint" for item in app.expander))
        self.assertGreaterEqual(len(app.get("image")), 1)
        self.assertFalse(any("blueprint-stage-grid" in str(item.value) for item in app.markdown))
        self.assertEqual(next(item.value for item in app.metric if item.label == "Follow-ups open"), "0")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Feedback received"), "0")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Follow-ups completed"), "0")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Search match rate"), "No searches")
        self.assertEqual(next(item.value for item in app.metric if item.label == "Mira rating"), "Not rated")
        self.assertFalse(any(item.label in {"Budget mentions", "Purchase values stated", "Saved follow-ups"} for item in app.metric))
        self.assertEqual(next(item.value for item in app.metric if item.label == "Conversations"), "0")
        self.assertFalse(app.error)
        output = ROOT / "data" / "private" / "continuous_qa" / "owner-dashboard-performance.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                     "load_seconds": round(perf_counter() - started, 3),
                                     "scope": "local QA owner fixture; empty inquiries and rules"}) + "\n")

    def test_dashboard_load_filters_panels_and_mira_timings(self):
        measurements = {}
        with ExitStack() as stack:
            for target, value in (
                ("ai_config.select_ai_config", ("offline", "", "")),
                ("storage_backend._database_url", ""),
                ("followup_service.cancel_user_followups", 0),
                ("followup_service.list_email_followups", []),
            ):
                stack.enter_context(patch(target, return_value=value))
            stack.enter_context(patch("inquiry_log.append_inquiry"))
            stack.enter_context(patch("inquiry_log.update_conversation_fields"))
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)

            def measure(name, action):
                started = perf_counter()
                action()
                measurements[name] = round(perf_counter() - started, 3)
                self.assertFalse(app.exception, name)

            def button(label):
                return next(item for item in app.button if item.label == label)

            measure("initial_dashboard_load", app.run)
            self.assertTrue(any(item.label == "Message Mira" for item in app.text_input))
            self.assertFalse(app.session_state["owner_dashboard_authenticated"])
            measure("flat_filter", lambda: next(item for item in app.checkbox if item.label == "Flat").check().run())
            cards = [str(item.value) for item in app.markdown if "grid-template-columns:repeat(auto-fit,minmax(145px,1fr))" in str(item.value)]
            self.assertGreater(len(cards), 0)
            self.assertTrue(all("Flat" in card for card in cards))
            for label in ("💰 Loans", "📐 Area & price", "🔎 Sources", "🔔 Follow-up"):
                measure("panel_" + label, lambda label=label: button(label).click().run())
                self.assertIsNotNone(app.session_state["active_info_panel"])
            next(item for item in app.text_input if item.label == "Message Mira").set_value("Remind me tomorrow at 6 PM")
            measure("mira_save_to_popup", lambda: button("Send").click().run())
            self.assertEqual([item.value for item in app.toast], ["Follow-up saved"])
            self.assertEqual(len(app.session_state["in_app_reminders"]), 1)
            measure("unchanged_dashboard_rerun", app.run)
            self.assertEqual(len(app.session_state["in_app_reminders"]), 1)
            self.assertFalse(app.toast)
            measure("empty_results_filter", lambda: next(item for item in app.number_input if item.label == "Preferred size (m²)").set_value(1_000_000_000.0).run())
            self.assertTrue(any("No records in this listing type match" in str(item.value) for item in app.info))
            self.assertTrue(any("0 matching" in str(item.value) for item in app.markdown))
            measure("clear_filter_recovery", lambda: next(item for item in app.number_input if item.label == "Preferred size (m²)").set_value(0.0).run())
            self.assertFalse(any("No records in this listing type match" in str(item.value) for item in app.info))

        output = ROOT / "data" / "private" / "continuous_qa" / "dashboard-performance.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {"at": datetime.now().isoformat(timespec="seconds"),
                  "scope": "local Streamlit AppTest; offline Mira; mocked external writes",
                  "seconds": measurements, "rendered_flat_cards": len(cards),
                  "slow_operations_over_5s": [name for name, elapsed in measurements.items() if elapsed > 5]}
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        print("Dashboard performance: " + json.dumps(report, ensure_ascii=True), flush=True)
