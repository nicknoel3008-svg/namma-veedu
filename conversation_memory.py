"""Small, explicit session memory shared by offline and AI conversations."""
from __future__ import annotations

import re
from agent import parse_request


def update_preferences(text, data, previous=None):
    """Merge only stated preferences; questions never erase existing constraints."""
    remembered = dict(previous or {})
    normalized = text.casefold()
    if re.search(r"\b(?:start (?:over|again)|reset (?:my )?(?:search|preferences)|forget my preferences)\b", normalized):
        remembered = {}
    intent = parse_request(text, data)
    for key in ("location", "property_type", "bedrooms", "status", "max_budget", "min_area_sqm"):
        value = getattr(intent, key)
        if value not in (None, "", "Any"):
            remembered[key] = value
    for pattern, key in (
        (r"\b(?:any (?:area|location|city)|anywhere|(?:remove|ignore|forget) (?:the )?(?:location|area|city))\b", "location"),
        (r"\b(?:no budget (?:limit|cap)|(?:remove|ignore|forget) (?:the )?budget|any budget)\b", "max_budget"),
        (r"\b(?:any (?:bhk|bedroom count)|(?:remove|ignore|forget) (?:the )?(?:bhk|bedroom count))\b", "bedrooms"),
        (r"\b(?:any property type|(?:remove|ignore|forget) (?:the )?(?:property type|flat|house|plot))\b", "property_type"),
    ):
        if re.search(pattern, normalized):
            remembered.pop(key, None)
    return remembered


def preference_summary(preferences):
    parts = []
    if preferences.get("bedrooms"):
        parts.append(f"{preferences['bedrooms']} BHK")
    if preferences.get("property_type") not in (None, "Any"):
        parts.append(preferences["property_type"].lower())
    if preferences.get("location"):
        parts.append(f"in {preferences['location']}")
    if preferences.get("max_budget") is not None:
        parts.append(f"within ₹{preferences['max_budget'] / 100_000:g} lakh")
    return " ".join(parts)


def contextual_reply(text, preferences, language="English"):
    """Answer unsupported lifestyle follow-ups honestly with retained context."""
    if not re.search(r"\b(?:schools?|quiet(?:er|ness)?|commute|hospitals?)\b", text, re.I):
        return None
    if not re.search(r"\?|\b(?:what about|how about|nearby|is it|are there|can you|tell me)\b", text, re.I):
        return None
    if language == "Tamil":
        return "உங்கள் முந்தைய தேடல் விருப்பங்களை நினைவில் வைத்திருக்கிறேன். பள்ளிகள், பயண நேரம் அல்லது அமைதியான சூழலை இந்தப் பதிவுகளால் உறுதிப்படுத்த முடியாது. எந்தப் பகுதி அல்லது பட்டியலைச் சரிபார்க்க விரும்புகிறீர்கள்?"
    summary = preference_summary(preferences)
    lead = f"I’m still keeping your {summary} search in mind. " if summary else ""
    return lead + "The saved records don’t verify nearby schools, commute times or how quiet a street is. Which listing or area would you like to check more closely?"
