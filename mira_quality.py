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
    if not response.strip():
        flags.append("Missing Mira response")
    return flags
