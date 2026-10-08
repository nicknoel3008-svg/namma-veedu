"""Owner-approved communication guidance that Mira can reuse across chats."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4
from typing import Any

from mira_quality import quality_flags


LIBRARY_PATH = Path(__file__).parent / "data" / "private" / "mira_learning_library.json"
ACTIVE_STATUSES = {"Approved", "Active"}

# These are concise, evidence-based service standards. They are editable and can
# be paused by the owner in the private dashboard; they are not customer data.
BASELINE_RULES = [
    {
        "Rule ID": "baseline-acknowledge-concern",
        "Scenario": "Customer is disappointed, frustrated, or says Mira missed the point",
        "Guidance": "Acknowledge the specific concern first, then answer the current request. Do not use a generic apology or make the customer repeat details already given.",
        "Status": "Approved",
        "Source": "Customer-service baseline: Intercom and Zendesk guidance",
    },
    {
        "Rule ID": "baseline-own-correction",
        "Scenario": "Mira gave a wrong, irrelevant, or unwanted suggestion",
        "Guidance": "Clearly own the mistake, remove or ignore the unwanted suggestion when asked, state the corrected understanding, then give one useful next step.",
        "Status": "Approved",
        "Source": "Customer-service baseline: Intercom and Zendesk guidance",
    },
    {
        "Rule ID": "baseline-appreciation",
        "Scenario": "Customer thanks, appreciates, or compliments Mira",
        "Guidance": "Thank the customer warmly and briefly. Acknowledge what helped, then offer the next relevant help without forcing a new task.",
        "Status": "Approved",
        "Source": "Customer-service baseline: Zendesk guidance",
    },
    {
        "Rule ID": "baseline-clear-next-step",
        "Scenario": "Any request Mira cannot complete or verify directly",
        "Guidance": "Say what is known, state the limit plainly, and offer the safest practical next step. Never invent availability, prices, contact details, guarantees, or a human response time.",
        "Status": "Approved",
        "Source": "Namma Illam property-safety policy",
    },
    {
        "Rule ID": "baseline-language-and-tone",
        "Scenario": "All customer conversations",
        "Guidance": "Match the customer's selected language and comfort level. Keep chat replies human, concise, respectful, and focused on the current request; acknowledge every explicit request before moving on.",
        "Status": "Approved",
        "Source": "Customer-service baseline: Zendesk guidance",
    },
]


def _clean_rule(rule: dict[str, Any]) -> dict[str, str]:
    return {
        "Rule ID": str(rule.get("Rule ID") or f"rule-{uuid4().hex[:10]}").strip(),
        "Scenario": str(rule.get("Scenario") or "").strip()[:220],
        "Guidance": str(rule.get("Guidance") or "").strip()[:700],
        "Status": str(rule.get("Status") or "Draft").strip(),
        "Source": str(rule.get("Source") or "Owner-created").strip()[:180],
    }


def load_learning_rules(path: Path = LIBRARY_PATH) -> list[dict[str, str]]:
    """Load the private library, creating the editable baseline on first run."""
    if not path.exists():
        save_learning_rules(BASELINE_RULES, path)
        return [_clean_rule(rule) for rule in BASELINE_RULES]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [_clean_rule(rule) for rule in BASELINE_RULES]
    if not isinstance(raw, list):
        return [_clean_rule(rule) for rule in BASELINE_RULES]
    rules = [_clean_rule(rule) for rule in raw if isinstance(rule, dict)]
    return rules or [_clean_rule(rule) for rule in BASELINE_RULES]


def save_learning_rules(rules: list[dict[str, Any]], path: Path = LIBRARY_PATH) -> list[dict[str, str]]:
    """Persist valid owner rules atomically and return the saved set."""
    cleaned = [_clean_rule(rule) for rule in rules]
    cleaned = [rule for rule in cleaned if rule["Scenario"] and rule["Guidance"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return cleaned


def active_learning_guidance(rules: list[dict[str, Any]] | None = None) -> list[str]:
    """Return bounded, approved guidance safe to include in an AI prompt."""
    rules = rules if rules is not None else load_learning_rules()
    guidance: list[str] = []
    for rule in rules:
        cleaned = _clean_rule(rule)
        if cleaned["Status"] in ACTIVE_STATUSES and cleaned["Guidance"]:
            guidance.append(f"When {cleaned['Scenario']}: {cleaned['Guidance']}")
    return guidance[:12]


_DRAFT_PATTERNS = (
    (
        "suggested-missed-search-intent",
        "Mira repeatedly treats a property-search request as general conversation instead of a search.",
        "Recognize the request as a property search. Confirm the stated location or preference, preserve explicit exclusions, and show matching saved listings or clearly state that none were found.",
        "Possible search intent not handled as a search",
    ),
    (
        "suggested-frustration-recovery",
        "Customers repeatedly express frustration or dissatisfaction after Mira's response.",
        "Acknowledge the specific missed point without becoming defensive. State the corrected understanding, answer the immediate request, and offer feedback or a human callback only when the issue remains unresolved.",
        "Customer frustration or dissatisfaction",
    ),
    (
        "suggested-no-result-recovery",
        "Mira repeatedly has no saved match for a customer search.",
        "State that no saved match was found for the stated criteria. Preserve the customer's important requirements, then ask one focused question about whether they want to adjust area, budget, property type, or BHK.",
        "No-result search",
    ),
    (
        "suggested-missing-response-recovery",
        "Mira repeatedly fails to return a response for a customer message.",
        "Acknowledge the request on the next available turn, briefly explain that the answer was not delivered, and answer the current request without asking the customer to repeat it.",
        "Missing Mira response",
    ),
)


def suggested_draft_rules(rows: list[dict[str, Any]], minimum_occurrences: int = 2) -> list[dict[str, str]]:
    """Turn recurring, explainable quality cues into inactive owner-review drafts."""
    cues = [cue for row in rows for cue in quality_flags(row)]
    drafts: list[dict[str, str]] = []
    for rule_id, scenario, guidance, cue in _DRAFT_PATTERNS:
        occurrences = cues.count(cue)
        if occurrences >= minimum_occurrences:
            drafts.append({
                "Rule ID": rule_id,
                "Scenario": scenario,
                "Guidance": guidance,
                "Status": "Draft",
                "Source": f"Automatic quality-review pattern ({occurrences} similar conversation cues)",
            })
    return drafts


def merge_suggested_drafts(existing: list[dict[str, Any]], suggestions: list[dict[str, Any]]) -> tuple[list[dict[str, str]], int]:
    """Add each automatic draft once; never overwrite an owner-edited rule."""
    merged = [_clean_rule(rule) for rule in existing]
    known_ids = {rule["Rule ID"] for rule in merged}
    added = 0
    for suggestion in suggestions:
        cleaned = _clean_rule(suggestion)
        if cleaned["Rule ID"] not in known_ids:
            merged.append(cleaned)
            known_ids.add(cleaned["Rule ID"])
            added += 1
    return merged, added
