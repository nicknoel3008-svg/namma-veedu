"""Explainable engagement assessment; never an unvalidated probability."""
from datetime import datetime
from agent_runtime import INDIA_TZ

HEADERS = ("Purchase likelihood", "Supporting evidence", "Prediction status",
           "Prediction last updated", "Actual purchase outcome")


def assess(turns, journeys=(), selections=(), *, evaluated_at=None):
    """Assess a linked conversation using structured signals, never raw chat text."""
    latest = turns[-1] if turns else {}
    user = latest.get("User ID")
    def linked(row):
        return bool(user and row.get("user_id") == user)
    visits = [r for r in journeys if linked(r)]
    chosen = [r for r in selections if linked(r) and r.get("status") == "Selected"]
    evidence = []
    outcomes = []
    positive = False
    for visit in visits:
        title = str(visit.get("property_title") or "Selected property")
        outcome = visit.get("purchase_outcome")
        if outcome in ("Purchased", "Did not purchase"):
            outcomes.append(f"{title}: {outcome} (owner recorded)")
        if visit.get("customer_purchase_confirmed_at"):
            evidence.append(f"{title}: customer reports purchase; owner verification required")
        if visit.get("purchase_intent") == "Not interested":
            evidence.append(f"{title}: not interested in this property")
            continue
        for field, description in (("purchase_intent", "Interested"), ("attended", "Yes"),
                                   ("satisfied", "Yes"), ("advisor_consent", "Yes")):
            if visit.get(field) == description:
                evidence.append(f"{title}: " + {"purchase_intent": "purchase interest stated",
                    "attended": "visit completed", "satisfied": "preferences satisfied",
                    "advisor_consent": "advisor assistance consented"}[field])
        positive |= visit.get("purchase_intent") == "Interested"
    interest = next((r.get("Customer interest (owner)") or r.get("Customer interest signal")
                     for r in reversed(turns) if (r.get("Customer interest (owner)") or r.get("Customer interest signal"))
                     not in (None, "", "Not updated", "Not stated", "Not recorded")), "")
    if interest in ("Interested", "Interested signal"):
        evidence.append("Chat: property interest stated")
        positive = True
    elif interest in ("Not interested", "Not interested signal"):
        evidence.append("Chat: property interest declined; overall buying intention unknown")
    if chosen:
        evidence.append(f"{len(chosen)} active property selection(s)")
    if any(r.get("Follow-up consent timestamp (Asia/Kolkata)") for r in turns):
        evidence.append("Follow-up consent recorded; does not prove a purchase")
    if any(r.get("Human handoff requested signal") == "Yes" for r in turns):
        evidence.append("Human assistance requested")
    outcome = next((row.get("Sale outcome (owner)") for row in reversed(turns)
                    if row.get("Sale outcome (owner)") in ("Purchased", "Did not purchase")), None)
    if outcome:
        outcomes.append(f"Conversation: {outcome} (owner recorded)")
    level = "High interest" if positive and any(v.get("attended") == "Yes" and v.get("satisfied") == "Yes" and v.get("purchase_intent") != "Not interested" for v in visits) else (
        "Interest expressed" if positive else "Engaged—intent unknown" if chosen else "Insufficient evidence")
    if any(v.get("purchase_outcome") == "Purchased" for v in visits):
        level = "Purchase recorded by owner"
    elif any(v.get("customer_purchase_confirmed_at") for v in visits):
        level = "Purchase reported—verification pending"
    return dict(zip(HEADERS, (level, "; ".join(dict.fromkeys(evidence)) or "No explicit buying intention recorded; silence is not rejection",
        "Provisional—unvalidated; no probability", evaluated_at or datetime.now(INDIA_TZ).isoformat(timespec="seconds"),
        "; ".join(dict.fromkeys(outcomes)) or "Unknown")))
