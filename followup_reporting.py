"""Conversation-level follow-up metrics shared by the dashboard and tests."""


def followup_metrics(rows):
    grouped = {}
    for row in sorted(rows, key=lambda item: str(item.get("Timestamp (Asia/Kolkata)") or "")):
        key = row.get("Conversation ID") or row.get("Inquiry ID")
        if key:
            grouped.setdefault(key, []).append(row)
    counts = dict(saved=0, open=0, completed=0)
    for turns in grouped.values():
        def latest(field):
            return next((str(row.get(field) or "").strip().casefold() for row in reversed(turns)
                         if str(row.get(field) or "").strip().casefold() not in {"", "not updated"}), "")
        status = latest("Follow-up schedule status")
        owner = latest("Follow-up status (owner)")
        counts["saved"] += bool(latest("Follow-up method") or status)
        counts["completed"] += owner == "completed" or (owner not in {"needed", "scheduled", "not needed"} and status in {"complete", "completed", "done"})
        counts["open"] += owner in {"needed", "scheduled"} or (owner not in {"completed", "not needed"} and status in {"scheduled", "saved (email delivery off)", "saved (whatsapp delivery off)", "saved_pending_activation", "sending", "needs review", "accepted by whatsapp; delivery unconfirmed"})
    return counts
