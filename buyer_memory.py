"""Session buyer needs and deterministic evidence from saved records."""
from copy import deepcopy
import re
import pandas as pd

FEATURES = {
    "parking": r"parking|car park|பார்க்கிங்",
    "balcony": r"balcon(?:y|ies)|பால்கனி",
    "garden": r"garden|தோட்டம்",
    "pool": r"(?:swimming )?pool|நீச்சல்",
    "gym": r"gym|fitness|உடற்பயிற்சி",
    "lift": r"lift|elevator",
    "quiet": r"quiet|peaceful|calm|அமைதி",
    "schools": r"school|பள்ளி",
    "transit": r"metro|bus stop|public transport|transit",
}


def record_key(record):
    return str(record.get("property_id") or (str(record.get("title", "")) + "|" + str(record.get("source_url", ""))))


def shown_records(chat):
    for message in reversed(chat):
        if message.get("role") != "assistant":
            continue
        if message.get("mode") == "results":
            return message.get("records", [])[:3]
        for tool in reversed(message.get("tool_results", [])):
            if tool.get("kind") in ("properties", "auctions"):
                return tool.get("data", {}).get("records", [])[:3]
    return []


def resolve_reference(text, records, selected=None):
    query = text.casefold()
    ordinal = re.search(r"\b(first|1st|second|2nd|third|3rd)\b|முதலாவது|இரண்டாவது|மூன்றாவது", query)
    if ordinal:
        index = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
                 "முதலாவது": 0, "இரண்டாவது": 1, "மூன்றாவது": 2}[ordinal.group()]
        return records[index] if index < len(records) else None
    for record in records:
        if record.get("title") and str(record["title"]).casefold() in query:
            return record
    if re.search(r"\b(?:that|this|it|selected)\b|அதில்|அது", query):
        return selected or (records[0] if len(records) == 1 else None)
    return None


def no_match_reply(data, memory, tamil=False, filters=None):
    """Explain checked constraints without silently relaxing the user's search."""
    from property_search import search_properties

    context = memory.get("requirements", {})
    args = dict(filters) if filters is not None else {
        "location": context.get("location", ""),
        "property_type": context.get("property_types", context.get("property_type", "Any")),
        "status": context.get("listing_statuses", context.get("status", "Any")),
        "bedrooms": context.get("bedrooms"), "max_budget": context.get("max_budget"),
        "min_area_sqm": context.get("min_area_sqm"),
    }
    tamil = tamil or memory.get("response_language") == "Tamil"
    tanglish = memory.get("response_language") == "Tanglish"
    groups = []
    def translated(english, tamil_text):
        return tamil_text if tamil else english
    def joined(value):
        return ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
    for key, label, default in (("location", "Location", ""), ("property_type", "Property type", "Any"),
                                ("status", "Listing category", "Any"), ("bedrooms", "BHK", None)):
        value = args.get(key, default)
        if value not in (None, "", "Any") and value != []:
            label = ({"Location": "பகுதி", "Property type": "சொத்து வகை", "Listing category": "பதிவு வகை", "BHK": "BHK"}.get(label, label) if tamil else label)
            groups.append((f"{label}: {joined(value)}", {key: default}))
    budget = [f"{'minimum' if key == 'min_budget' else 'maximum'} ₹{args[key]/100000:g} lakh"
              for key in ("min_budget", "max_budget") if args.get(key) is not None]
    if budget:
        budget_text = ", ".join(budget)
        if tamil:
            budget_text = budget_text.replace("minimum", "குறைந்தபட்சம்").replace("maximum", "அதிகபட்சம்").replace("lakh", "லட்சம்")
        groups.append((translated("Budget: ", "பட்ஜெட்: ") + budget_text, {"min_budget": None, "max_budget": None}))
    area = [f"{'minimum' if key == 'min_area_sqm' else 'maximum'} {args[key]:g} m²"
            for key in ("min_area_sqm", "max_area_sqm") if args.get(key) is not None]
    if area:
        area_text = ", ".join(area)
        if tamil:
            area_text = area_text.replace("minimum", "குறைந்தபட்சம்").replace("maximum", "அதிகபட்சம்")
        groups.append((translated("Area: ", "பரப்பளவு: ") + area_text, {"min_area_sqm": None, "max_area_sqm": None}))
    inventory = prepare_inventory(data, memory)
    details = []
    baseline = {key: value for key, value in args.items() if key == "include_ended_auctions"}
    for label, relaxed in groups:
        candidates = search_properties(inventory, **(args | relaxed))
        if len(candidates):
            detail = translated(
                f"{label} — changing this filter leaves {len(candidates)} matching {'record' if len(candidates) == 1 else 'records'} for your other preferences.",
                f"{label} — இந்த விருப்பத்தை மாற்றினால், மற்ற விருப்பங்களுக்குப் பொருந்தும் {len(candidates)} பதிவுகள் உள்ளன.")
            if "max_budget" in relaxed:
                prices = pd.to_numeric(candidates["price_inr"], errors="coerce").dropna()
                if len(prices):
                    detail += translated(f" Lowest recorded price among those records: ₹{prices.min()/100000:g} lakh (may be a starting price).",
                                         f" அவற்றில் பதிவான குறைந்த விலை: ₹{prices.min()/100000:g} லட்சம் (தொடக்க விலையாக இருக்கலாம்).")
                else:
                    detail += translated(" Their prices are unreported, so I can’t confirm they fit your budget.", " அவற்றின் விலை பதிவாகவில்லை; உங்கள் பட்ஜெட்டுக்குப் பொருந்துவதை உறுதிப்படுத்த முடியாது.")
            details.append(detail)
        else:
            criterion = {key: args.get(key) for key in relaxed}
            if not len(search_properties(inventory, **(baseline | criterion))):
                details.append(translated(f"{label} — no eligible saved record confirms this preference, even before applying the other search filters.",
                                          f"{label} — மற்ற விருப்பங்களைச் சேர்ப்பதற்கு முன்பே, இதைப் பூர்த்தி செய்யும் உறுதிப்படுத்தப்பட்ட பதிவு இல்லை."))
    required = [feature for feature, desire in memory.get("preferences", {}).items()
                if desire == "required" and feature in FEATURES]
    hard = required + ([f"{memory['facing']} facing"] if memory.get("facing") else []) + (["above ground floor"] if memory.get("avoid_ground_floor") else [])
    if memory.get("excluded_terms"):
        hard.append("exclude " + ", ".join(memory["excluded_terms"]))
    if memory.get("rejected"):
        hard.append("previously rejected listings excluded")
    if hard:
        candidates = search_properties(data, **args)
        if len(candidates) and not len(prepare_inventory(candidates, memory)):
            details.append(translated("Required details: " + ", ".join(hard) + " — no remaining record confirms all these details; missing details are unverified.",
                                      "அவசியமான விவரங்கள்: " + ", ".join(hard) + " — இவை அனைத்தையும் உறுதிப்படுத்தும் பதிவு இல்லை; விடுபட்ட விவரங்கள் உறுதிப்படுத்தப்படவில்லை."))
    if not details:
        # Multiple conflicting constraints may need changing together.
        labels = [label for label, _ in groups] + hard
        details.append(translated("No saved record matches this combination: ", "இந்த விருப்பங்களின் சேர்க்கைக்குப் பொருத்தமான பதிவு இல்லை: ") + "; ".join(labels) + "." if labels
                       else translated("There are no eligible saved records in this search category.", "இந்தத் தேடல் வகையில் தகுதியான பதிவு இல்லை."))
    evidence = " Budget, BHK, area and required details can only be checked when the source reports them; missing values are unverified."
    if tamil:
        return "உங்கள் அனைத்து விருப்பங்களுக்கும் பொருந்தும் பதிவு இல்லை.\n\n" + "\n\n".join(details) + "\n\nவிடுபட்ட விவரங்களை உறுதிப்படுத்த முடியாது. எந்த விருப்பத்தை மாற்ற விரும்புகிறீர்கள்? நீங்கள் சொல்லும் வரை உங்கள் விருப்பங்களை மாற்ற மாட்டேன்."
    if tanglish:
        return "Ungal ella preferences-kum confirmed match kidaikkala.\n\n" + "\n\n".join(details) + evidence + "\n\nEndha preference-ai maatha virumbureenga? Neenga sollum varai preferences-ai maatha maatten."
    return "I couldn’t find a saved record matching all your preferences.\n\n" + "\n\n".join(details) + evidence + "\n\nWhich preference would you like to change? I’ll keep your preferences until you ask to change them."


def grounded_search_reply(result, memory, tamil=False, data=None):
    """Render recommendations from checked fields rather than model claims."""
    records = result.get("records", [])
    tanglish = memory.get("response_language") == "Tanglish"
    tamil = tamil or memory.get("response_language") == "Tamil"
    if not records:
        if data is not None:
            return no_match_reply(data, memory, tamil)
        if tanglish:
            return "Ungal requirements-ku saved records-la confirmed match kidaikkala. Area illa budget-ai maatha virumbureengala? Missing floor, lift, facing details-ai confirmed match-nu karudha maatten."
        return "உங்கள் நிபந்தனைகளுக்கு சேமித்த பதிவுகளில் பொருத்தம் இல்லை. பகுதியையோ பட்ஜெட்டையோ மாற்ற விரும்புகிறீர்களா?" if tamil else "I couldn’t find a match for your requirements in the saved records. Would you like to change the area or budget?"
    lines = []
    for record in records[:3]:
        price = pd.to_numeric(record.get("price_inr"), errors="coerce")
        price_text = f"₹{price/100000:g} lakh" if pd.notna(price) else "விலை குறிப்பிடப்படவில்லை" if tamil else "price not reported"
        features = []
        for feature, desire in memory.get("preferences", {}).items():
            status = feature_evidence(record, feature) if feature in FEATURES else "unknown"
            label = ({"recorded": "பதிவில் உள்ளது", "absent": "இல்லை என்று பதிவு உள்ளது", "unknown": "உறுதிப்படுத்தப்படவில்லை"} if tamil else
                     {"recorded": "mentioned in source", "absent": "source says absent", "unknown": "not confirmed"})[status]
            features.append(f"{feature}: {label}" + (" (avoid)" if desire == "avoid" else ""))
        location = record.get("locality") or record.get("city") or ""
        basis = str(record.get("price_basis") or "").strip()
        price_text = f"{basis}: {record.get('price_display') or price_text}" if basis else price_text
        kind = str(record.get("listing_status") or "").strip()
        lines.append(f"**{record.get('title', 'Listing')}** — {price_text}, {location}; {kind}. " + "; ".join(features))
    return "\n\n".join(lines) + ("\n\nIdhu saved source details; current availability confirm aagala." if tanglish else "\n\nசேமித்த ஆதார விவரங்கள்; தற்போதைய கிடைப்பை உறுதிப்படுத்தாது." if tamil else "\n\nThese details come from saved sources; current availability is unconfirmed.")


def update_buyer_memory(text, requirements, chat, previous=None):
    memory = deepcopy(previous or {"requirements": {}, "preferences": {}, "rejected": [], "corrections": [], "selected": None})
    query = text.casefold()
    if re.search(r"\b(?:start over|start again|reset (?:my )?(?:search|preferences)|forget my preferences)\b", query):
        memory = {"requirements": {}, "preferences": {}, "rejected": [], "corrections": [], "selected": None}
    old = memory["requirements"]
    for key in set(old) | set(requirements):
        if old.get(key) != requirements.get(key):
            memory["corrections"].append({"field": key, "before": old.get(key), "after": requirements.get(key)})
    memory["corrections"] = memory["corrections"][-12:]
    memory["requirements"] = dict(requirements)
    # Questions about amenities are not automatically buying requirements.
    if re.search(r"\b(?:need|want|prefer|must|looking for|important|priority|avoid)\b|வேண்டும்|விருப்பம்", query):
        for name, pattern in FEATURES.items():
            found = re.search(pattern, query)
            if found:
                prefix = query[max(0, found.start()-30):found.start()]
                if re.search(r"(?:don't need|do not need|no need for|not important|remove)\s*(?:a |the )?$", prefix):
                    memory["preferences"].pop(name, None)
                else:
                    if re.search(r"(?:avoid|don't want|do not want|without|no)\s*(?:a |the )?$", prefix):
                        memory["preferences"][name] = "avoid"
                    elif re.search(r"\b(?:must|mandatory|essential|non.negotiable)\b", prefix):
                        memory["preferences"][name] = "required"
                    else:
                        memory["preferences"][name] = "prefer"
    records = shown_records(chat)
    shortlist_ids = [record_key(record) for record in records]
    if memory.get("shortlist_ids") != shortlist_ids:
        memory["selected"] = None
    memory["shortlist_ids"] = shortlist_ids
    selected = resolve_reference(text, records, memory.get("selected"))
    if not selected and re.search(r"\b(?:first|1st|second|2nd|third|3rd)\b", query):
        memory["selected"] = None
    if selected:
        memory["selected"] = dict(selected)
    if re.search(r"\b(?:reject|skip|don't like|do not like|not interested in|not for me|none of these)\b|வேண்டாம்", query):
        targets = records if re.search(r"\b(?:all|these|none of these)\b", query) else [selected] if selected else []
        for record in targets:
            key = record_key(record)
            if key not in memory["rejected"]:
                memory["rejected"].append(key)
    if selected and re.search(r"\b(?:reconsider|bring back|include again)\b", query):
        memory["rejected"] = [key for key in memory["rejected"] if key != record_key(selected)]
    return memory


def feature_evidence(record, feature):
    text = str(record.get("amenities") or "")
    if feature == "parking":
        value = str(record.get("car_parking") or "").strip()
        if value.casefold() in ("no", "none", "0", "not available"):
            return "absent"
        if re.search(r"\b(?:no|not available|not provided)\b", value, re.I):
            return "absent"
        if re.search(r"\b(?:yes|available|covered|open|allotted|provided|[1-9]\d*)\b", value, re.I):
            return "recorded"
    pattern = FEATURES[feature]
    if re.search(r"\b(?:no|without|not available:?|not provided:?)\s+(?:(?:a|covered|car|private)\s+)?(?:" + pattern + r")|(?:" + pattern + r")\s*(?::|-)?\s*(?:no|not available|not provided)\b", text, re.I):
        return "absent"
    if re.search(pattern, text, re.I):
        return "recorded"
    return "unknown"


def prepare_inventory(data, memory):
    result = data.copy()
    if memory.get("avoid_ground_floor") and not result.empty:
        def upper_floor(row):
            value = str(row.get("floor_number") or "").strip().casefold()
            if value in {"ground", "ground floor", "g", "gf", "0", "0.0"}:
                return False
            if re.search(r"\b(?:first|second|third|fourth|fifth)\b", value):
                return True
            number = re.search(r"\d+", value)
            return bool(number and int(number.group()) > 0)
        result = result[[upper_floor(row) for row in result.to_dict("records")]]
    if memory.get("facing") and not result.empty:
        facing = result.get("facing", pd.Series("", index=result.index)).fillna("").astype(str)
        result = result[facing.str.fullmatch(r"\s*" + re.escape(memory["facing"]) + r"(?:[-\s]+facing)?\s*", case=False)]
    for term in memory.get("excluded_terms", []):
        columns = [column for column in ("title", "project_name", "source_name", "locality", "city", "district") if column in result]
        if columns:
            text = result[columns].fillna("").astype(str).agg(" ".join, axis=1)
            result = result[~text.str.contains(re.escape(str(term)), case=False, regex=True)]
    if memory.get("rejected"):
        result = result[[record_key(row) not in memory["rejected"] for row in result.to_dict("records")]]
    preferences = {feature: desire for feature, desire in memory.get("preferences", {}).items() if feature in FEATURES and desire != "verify"}
    for feature, desire in preferences.items():
        if desire == "required" and not result.empty:
            result = result[[feature_evidence(row, feature) == "recorded" for row in result.to_dict("records")]]
    if preferences and not result.empty:
        def score(row):
            return sum((1 if feature_evidence(row, feature) == "recorded" else -1 if feature_evidence(row, feature) == "absent" else 0)
                       * (-1 if desire == "avoid" else 1) for feature, desire in preferences.items())
        result["_preference_score"] = [score(row) for row in result.to_dict("records")]
    return result


def enforce_search_args(args, requirements):
    args = dict(args)
    for key, tool_key in (("location", "city"), ("property_type", "property_type"), ("bedrooms", "bedrooms"),
                          ("max_budget", "max_budget_inr"), ("min_area_sqm", "min_area_sqm")):
        if requirements.get(key) not in (None, "", "Any"):
            args[tool_key] = requirements[key]
    if requirements.get("status") in ("Existing sale", "Project reference"):
        args["record_kind"] = requirements["status"]
    return args


def record_detail_reply(text, memory, records, tamil=False):
    selected = memory.get("selected")
    if re.search(r"\bcompare (?:these|them|the|both)\b|ஒப்பிடு", text, re.I):
        if len(records) < 2:
            return "ஒப்பிட குறைந்தது இரண்டு பட்டியல்கள் தேவை." if tamil else "I need at least two displayed listings to compare."
        lines = []
        for record in records:
            price = pd.to_numeric(record.get("price_inr"), errors="coerce")
            price_text = f"₹{price/100000:g} lakh" if pd.notna(price) else "விலை குறிப்பிடப்படவில்லை" if tamil else "price not reported"
            basis = str(record.get("price_basis") or "").strip()
            price_text = f"{basis}: {record.get('price_display') or price_text}" if basis else price_text
            bhk = record.get("_bedrooms_text") or record.get("bedrooms") or ("குறிப்பிடப்படவில்லை" if tamil else "not reported")
            lines.append(f"**{record.get('title', 'Listing')}** — {price_text}; BHK: {bhk}; {record.get('area_display') or ('பரப்பளவு குறிப்பிடப்படவில்லை' if tamil else 'area not reported')}; parking: {feature_evidence(record, 'parking')}.")
        return "\n\n".join(lines) + ("\n\nஇவை சேமித்த ஆதார விவரங்கள்; தற்போதைய கிடைப்பை உறுதிப்படுத்தாது." if tamil else "\n\nThese are saved source details, not confirmation of current availability.")
    feature = next((name for name, pattern in FEATURES.items() if re.search(pattern, text, re.I)), None)
    detail = feature and re.search(r"\?|\b(?:does|has|have|what about|tell me)\b|உள்ளதா", text, re.I)
    if detail and (selected or re.search(r"\b(?:first|second|third|that|this|it)\b", text, re.I)):
        if not selected:
            return "எந்தப் பட்டியலைக் குறிப்பிடுகிறீர்கள்?" if tamil else "Which listing do you mean?"
        status = feature_evidence(selected, feature)
        if tamil:
            description = {"recorded": "சேமித்த பதிவில் குறிப்பிடப்பட்டுள்ளது", "absent": "இல்லை என்று சேமித்த பதிவில் உள்ளது", "unknown": "சேமித்த பதிவில் உறுதிப்படுத்தப்படவில்லை"}[status]
            return f"**{selected.get('title')}** — {feature}: {description}."
        description = {"recorded": f"mentions {feature}", "absent": f"explicitly says there is no {feature}", "unknown": f"doesn’t confirm {feature}"}[status]
        return f"The saved record for **{selected.get('title')}** {description}."
    return None
