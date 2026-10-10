"""Bounded production-scale QA using only generated records and temporary storage."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime import INDIA_TZ
from inquiry_log import customer_summary_rows
from purchase_assessment import assess
from purchase_confirmation import confirm_purchase, reports
from visit_journey import owner_journeys, record_purchase_outcome
from visit_service import request_visit, update_visit_status


def run() -> dict:
    timings = {}
    inquiry_rows = []
    for index in range(10_000):
        conversation = f"scale-{index}"
        inquiry_rows.extend((
            {
                "Conversation ID": conversation,
                "User ID": f"user-{index}",
                "Timestamp (Asia/Kolkata)": f"2026-10-11T10:{index % 60:02d}:00+05:30",
                "Customer interest signal": "Interested" if index % 3 == 0 else "Not stated",
                "Follow-up method": "Email" if index % 2 == 0 else "In-app reminder",
                "Follow-up consent timestamp (Asia/Kolkata)": "2026-10-11T10:00:00+05:30" if index % 2 == 0 else "",
                "User inquiry": "Generated scale test inquiry",
            },
            {
                "Conversation ID": conversation,
                "User ID": f"user-{index}",
                "Timestamp (Asia/Kolkata)": f"2026-10-11T11:{index % 60:02d}:00+05:30",
                "Assistant response": "Generated scale test response",
            },
        ))
    started = perf_counter()
    summaries = customer_summary_rows(inquiry_rows)
    timings["summarize_20000_inquiry_rows_seconds"] = round(perf_counter() - started, 3)
    assert len(summaries) == 10_000

    with TemporaryDirectory() as folder:
        database = Path(folder) / "scale.sqlite3"
        visit_ids = []
        visit_at = datetime.now(INDIA_TZ) + timedelta(days=5)
        started = perf_counter()
        for index in range(1_000):
            visit_id = request_visit(
                record={"property_id": f"property-{index}", "title": f"Generated property {index}"},
                user_id=f"journey-user-{index}",
                conversation_id=f"journey-conversation-{index}",
                visit_at=visit_at + timedelta(minutes=index),
                slot_kind="Custom time",
                customer_name=f"Generated customer {index}",
                contact_method="Email",
                contact_value=f"qa{index}@example.com",
                consent=True,
                email_reminders=True,
                db_path=database,
            )
            update_visit_status(visit_id, "Confirmed", db_path=database)
            visit_ids.append(visit_id)
        timings["create_and_confirm_1000_visits_seconds"] = round(perf_counter() - started, 3)

        started = perf_counter()
        for index, visit_id in enumerate(visit_ids[:100]):
            confirm_purchase(visit_id, user_id=f"journey-user-{index}", confirmed=True, db_path=database)
        for visit_id in visit_ids[:50]:
            record_purchase_outcome(visit_id, "Purchased", "Verified generated QA outcome", db_path=database)
        for visit_id in visit_ids[100:150]:
            record_purchase_outcome(visit_id, "Did not purchase", "Verified generated QA outcome", db_path=database)
        timings["record_200_purchase_events_seconds"] = round(perf_counter() - started, 3)

        started = perf_counter()
        journeys = owner_journeys(database)
        receipts = reports(database)
        timings["load_1000_dashboard_journeys_seconds"] = round(perf_counter() - started, 3)
        assert len(journeys) == 1_000
        assert len(receipts) == 100
        assert sum(row["purchase_outcome"] == "Purchased" for row in journeys) == 50
        assert sum(row["purchase_outcome"] == "Did not purchase" for row in journeys) == 50
        verified = assess(
            [{"User ID": "journey-user-0", "Conversation ID": "journey-conversation-0"}], journeys
        )
        pending = assess(
            [{"User ID": "journey-user-75", "Conversation ID": "journey-conversation-75"}], journeys
        )
        assert verified["Purchase likelihood"] == "Purchase recorded by owner"
        assert pending["Purchase likelihood"] == "Purchase reported—verification pending"
    return {
        "generated_inquiry_rows": 20_000,
        "conversation_summaries": 10_000,
        "visit_journeys": 1_000,
        "customer_purchase_confirmations": 100,
        "owner_verified_purchases": 50,
        "owner_verified_non_purchases": 50,
        "timings": timings,
        "production_records_changed": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
