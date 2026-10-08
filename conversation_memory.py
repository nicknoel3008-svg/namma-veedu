"""Small, explicit session memory shared by offline and AI conversations."""
from __future__ import annotations

import re
from agent import parse_request


def update_preferences(text, data, previous=None):
    """Merge only stated preferences; questions never erase existing constraints."""
    previous_context = dict(previous or {})
    remembered = dict(previous_context)
    normalized = text.casefold()
    if re.search(r"\b(?:start (?:over|again)|reset (?:my )?(?:search|preferences)|forget my preferences)\b", normalized):
        remembered = {}
    intent = parse_request(text, data)
    # ``parse_request`` infers Flat from a bare BHK phrase. Respect an
    # explicit property-type removal in the same message so that a later
    # ``2BHK`` or budget update cannot silently restore the removed type.
    explicit_property_type_removal = bool(re.search(
        r"\b(?:remove|ignore|forget|drop|no longer want|don't want|do not want)\b"
        r"[^.?!\n]{0,80}\b(?:flat|house|plot|property type)\b",
        normalized,
    ))
    property_type_was_cleared = bool(previous_context.get("_property_type_cleared"))
    for key in ("location", "property_type", "bedrooms", "status", "max_budget", "min_area_sqm"):
        value = getattr(intent, key)
        if key == "property_type" and (explicit_property_type_removal or property_type_was_cleared):
            continue
        if value not in (None, "", "Any"):
            remembered[key] = value
    if explicit_property_type_removal:
        remembered["_property_type_cleared"] = True
    elif re.search(r"\b(?:flat|apartment|house|plot)\b", normalized):
        # A later explicit type request is the deliberate way to restore the
        # type after the customer cleared it.
        remembered.pop("_property_type_cleared", None)
    for pattern, key in (
        (r"\b(?:any (?:area|location|city)|anywhere|(?:remove|ignore|forget) (?:the )?(?:location|area|city))\b", "location"),
        (r"\b(?:no budget (?:limit|cap)|(?:remove|ignore|forget) (?:the )?budget|any budget)\b", "max_budget"),
        (r"\b(?:any (?:bhk|bedroom count)|(?:remove|ignore|forget) (?:the )?(?:bhk|bedroom count))\b", "bedrooms"),
        (r"\b(?:any property type|(?:remove|ignore|forget) (?:the )?(?:property type|flat|house|plot))\b", "property_type"),
    ):
        if re.search(pattern, normalized):
            remembered.pop(key, None)
    # Understand named removals in the same turn as additions, for example
    # “keep 2BHK under 60 lakh but remove Velachery” or “drop the flat type”.
    removal = r"(?:remove|ignore|forget|drop|no longer want|don't want|do not want)"
    prior_location = str(remembered.get("location") or previous_context.get("location") or "").strip()
    prior_location_query = prior_location.casefold()
    if prior_location and re.search(rf"{removal}[^.?!\n]{{0,80}}{re.escape(prior_location_query)}|{re.escape(prior_location_query)}[^.?!\n]{{0,35}}{removal}", normalized):
        remembered.pop("location", None)
    if re.search(rf"{removal}[^.?!\n]{{0,45}}(?:\d+\s*bhk|bedroom(?:s)?|bhk)", normalized) and not re.search(r"\bkeep\b[^.?!\n]{0,25}(?:\d+\s*bhk|bedroom(?:s)?|bhk)", normalized):
        remembered.pop("bedrooms", None)
    if re.search(rf"{removal}[^.?!\n]{{0,45}}(?:budget|lakh|crore|price)", normalized) and not re.search(r"\bkeep\b[^.?!\n]{0,25}(?:budget|lakh|crore|price|\d+\s*(?:lakh|crore))", normalized):
        remembered.pop("max_budget", None)
    if re.search(rf"{removal}[^.?!\n]{{0,45}}(?:flat|house|plot|property type)", normalized):
        remembered.pop("property_type", None)
        remembered["_property_type_cleared"] = True
    # If a message names a replacement area, prefer that replacement over the
    # first locality found by the generic parser (which may be the area being
    # removed).
    if prior_location and re.search(rf"{removal}[^.?!\n]{{0,80}}{re.escape(prior_location_query)}", normalized):
        candidates = sorted({
            str(value).strip() for column in ("locality", "city", "district")
            for value in data.get(column, []) if str(value).strip()
        }, key=len, reverse=True)
        replacement = next((value for value in candidates
            if value.casefold() != prior_location_query
                            and re.search(rf"(?:add|instead|replace|switch to|use)\s+(?:the\s+)?{re.escape(value.casefold())}\b", normalized)), None)
        if replacement:
            remembered["location"] = replacement
        else:
            # Keep an area the customer explicitly supplied even when it is
            # absent from the saved catalogue; it can still guide the next
            # clarification or search-widening question.
            raw_replacement = re.search(
                r"\b(?:add|instead|replace|switch to)\s+(?:the\s+)?([a-z][a-z-]*)\b",
                normalized,
            )
            if raw_replacement:
                candidate = raw_replacement.group(1).strip()
                if candidate not in {"instead", "the", "area", "location"}:
                    remembered["location"] = candidate.upper()
    # A type word such as "Flat" is never a location. If a generic parser
    # promoted it, recover an actual locality named in the same message.
    if str(remembered.get("location") or "").casefold() in {"flat", "apartment", "house", "plot"}:
        remembered.pop("location", None)
        place_values = sorted({
            str(value).strip() for column in ("locality", "city", "district")
            for value in data.get(column, []) if str(value).strip()
        }, key=len, reverse=True)
        actual_place = next((value for value in place_values
            if value.casefold() not in {"flat", "apartment", "house", "plot"}
            and re.search(rf"(?<!\w){re.escape(value.casefold())}(?!\w)", normalized)), None)
        if actual_place:
            remembered["location"] = actual_place
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
