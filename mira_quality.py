"""Owner-review signals for conversations that may need Mira improvements."""

from __future__ import annotations

import re
from typing import Any


_FRUSTRATION = re.compile(
    r"\b(?:not helpful|not helping|not listening|useless|wrong|disappointed|frustrated|"
    r"going in circles|fed up|waste of time|didn't answer|did not answer)\b|"
    r"பயனில்லை|உதவவில்லை|ஏமாற்றம்|கேட்கவில்லை",
    re.IGNORECASE,
)
_SEARCH_LANGUAGE = re.compile(
    r"\b(?:find|search|show|list|options?|suggest(?:ion)?s?|recommend|property|flat|house|plot)\b|"
    r"தேடு|காட்டு|சொத்து|வீடு|மனை",
    re.IGNORECASE,
)
_CALLBACK_REQUEST = re.compile(
    r"\b(?:call\s*back|callback|human\s+(?:advisor|agent)|arrange\s+(?:a\s+)?call|contact\s+me)\b|"
    r"தொடர்பு|மீண்டும் அழைக்க",
    re.IGNORECASE,
)
_EMAIL_OR_SHARE_REQUEST = re.compile(
    r"\b(?:email|e-mail|mail|send|share)\b.*\b(?:details?|listing|property|confirmation|suggestion)\b|"
    r"\b(?:details?|listing|property|confirmation|suggestion)\b.*\b(?:email|e-mail|mail|send|share)\b",
    re.IGNORECASE,
)
_REMOVAL_REQUEST = re.compile(
    r"\b(?:remove|ignore|forget|drop|don't want|do not want|not interested in)\b.*"
    r"\b(?:preference|bhk|bedroom|budget|area|location|suggestion|option)\b|"
    r"\b(?:no longer|without)\b.*\b(?:bhk|bedroom|budget|area|location)\b",
    re.IGNORECASE,
)
_LOAN_REQUEST = re.compile(
    r"\b(?:loan|lender|borrow|finance|funds?|remaining cost|difference amount|short on funds?)\b|"
    r"கடன்|நிதி",
    re.IGNORECASE,
)
_APPRECIATION = re.compile(
    r"\b(?:thanks?|thank you|great|good job|well done|beautiful|helpful|appreciate)\b|"
    r"நன்றி|நல்ல வேலை|உதவி",
    re.IGNORECASE,
)


def quality_flags(row: dict[str, Any]) -> list[str]:
    """Return explainable review cues; they are not claims that Mira was wrong."""
    inquiry = str(row.get("User inquiry") or "")
    response = str(row.get("Assistant response") or "")
    response_type = str(row.get("Response type") or "").casefold()
    satisfaction = str(row.get("Customer satisfaction signal") or "").casefold()
    flags: list[str] = []
    if _FRUSTRATION.search(inquiry) or "dissatisfied" in satisfaction:
        flags.append("Customer frustration or dissatisfaction")
    if _SEARCH_LANGUAGE.search(inquiry) and response_type in {"welcome", "property_detail", "local_talk"}:
        flags.append("Possible search intent not handled as a search")
    if _SEARCH_LANGUAGE.search(inquiry) and re.search(r"couldn.t find|no saved|no match", response, re.IGNORECASE):
        flags.append("No-result search")
    if _CALLBACK_REQUEST.search(inquiry) and response_type in {"local_support", "property_detail", "welcome"}:
        flags.append("Callback request not completed")
    if _EMAIL_OR_SHARE_REQUEST.search(inquiry) and response_type in {"local_support", "welcome", "property_detail"}:
        flags.append("Email or sharing request not addressed")
    if _REMOVAL_REQUEST.search(inquiry) and re.search(r"(?:2\s*bhk|3\s*bhk|budget|area|location|preference|suggestion)", response, re.IGNORECASE):
        flags.append("Preference removal not reflected")
    if _LOAN_REQUEST.search(inquiry) and response_type in {"gather_budget", "property_detail", "local_support", "welcome"}:
        flags.append("Loan request lost in conversation")
    if _APPRECIATION.search(inquiry) and response_type in {"local_support", "property_detail", "welcome"}:
        flags.append("Appreciation not acknowledged")
    if not response.strip():
        flags.append("Missing Mira response")
    return flags
