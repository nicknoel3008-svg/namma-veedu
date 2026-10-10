"""Grounded handling of ambiguous requests observed in Mira's chat logs."""
import re
import pandas as pd

from agent import parse_request
from buyer_memory import shown_records, prepare_inventory, update_buyer_memory, feature_evidence
from property_search import search_properties, rank_matches, format_price_for_card


def normalize_request(text):
    text = text.replace("’", "'")
    for wrong, right in (("preferance", "preference"), ("amenites", "amenities"), ("list ot", "list of"), ("list of properly", "list of property")):
        text = re.sub(re.escape(wrong), right, text, flags=re.I)
    return text


def website_context(data):
    """Describe actual portal capabilities and the complete saved-data schema."""
    return {
        "saved_record_count": len(data), "saved_fields": list(data.columns),
        "record_categories": sorted(data["listing_status"].dropna().unique().tolist()) if "listing_status" in data else [],
        "capabilities": ["Sidebar filters and three chat recommendations", "Saved sale listings, project references and bank auctions",
                         "CMDA approval references", "Area and price conversion", "Illustrative EMI and official lender links",
                         "Follow-ups: browser-session reminder or consented email if SMTP/public URL/worker configured",
                         "Owner dashboard: sign-in, structured customer summaries and date-filtered Excel downloads",
                         "End chat clears displayed messages; Start a new conversation opens a fresh chat"],
        "limitations": "Saved snapshots, not live availability. Missing amenities or prices are unknown. Project prices may be starting prices; approvals are not sale listings. Never claim email or advisor contact completed without portal confirmation.",
    }


def understand_request(text, data, chat, context=None, memory=None, tamil=False):
    """Return a grounded reply/search for known failure cases, else defer."""
    text = normalize_request(text)
    query = text.casefold()
    context = dict(context or {})
    memory = dict(memory or {})
    for key, default in (("requirements", {}), ("preferences", {}), ("rejected", []), ("corrections", []), ("selected", None)):
        memory.setdefault(key, default)
    records = shown_records(chat)
    if re.fullmatch(r"[\W_]*(?:hi|hello|hey|good morning|good afternoon|good evening|vanakkam|வணக்கம்|ஹாய்)(?:[\s,]+mira)?[\W_]*", query):
        return {"reply": "வணக்கம்! Namma Veedu-க்கு வரவேற்கிறேன். நான் Mira, உங்கள் AI சொத்து வழிகாட்டி. நீங்கள் எதைத் தேடுகிறீர்கள் என்று சொல்லுங்கள்; உங்களுக்கான வாய்ப்புகளைப் பார்க்க உதவுகிறேன்." if tamil else "Welcome to Namma Veedu! I’m Mira, your AI property guide. Tell me what you’re looking for, and I’ll help you explore your options.",
                "context": context, "memory": memory, "greeting": True}
    reply = None
    search = False
    exclusions = list(memory.get("excluded_terms", []))
    cheapest = bool(re.search(r"cheapest|lowest (?:price|value)|minimum (?:price|value)|least expensive", query))
    if cheapest and re.search(r"(?:your|the) website|across (?:the )?(?:website|inventory)|all (?:the )?listings", query):
        context = {}
    broad = bool(re.search(r"(?:no|don't have any|do not have any) (?:other )?preferences?|anywhere|all locations", query))
    remove_place = re.search(r"(?:ignore|forget|exclude|not in|other than|outside)\s+([\w -]+)", query)
    if remove_place and not re.search(r"ignore .*instructions", query):
        place = remove_place.group(1).strip()
        known = {str(value).casefold() for column in ("locality", "city", "district") for value in data[column].dropna() if str(value).strip()}
        if place in known or place == str(context.get("location", "")).casefold():
            exclusions.append(place)
            if str(context.get("location", "")).casefold() == place:
                context["location"] = ""
            search = True
    excluded_brand = re.search(r"\b(?:not|no|exclude|without)\s+(vgn|stepsstone|wisdom)\b", query)
    if excluded_brand:
        exclusions.append(excluded_brand.group(1))
        search = True
    other_location = bool(re.search(r"other location|another (?:area|location)|different (?:area|location)|anywhere else", query))
    too_far = bool(re.search(r"(?:is|are) (?:too )?far|too far|far from my", query))
    if other_location or too_far:
        for record in records:
            place = str(record.get("locality") or record.get("city") or "").strip()
            if place:
                exclusions.append(place)
        context["location"] = ""
        if too_far:
            reply = "அந்தப் பகுதியைத் தவிர்க்கிறேன். எந்த நகரம் அல்லது பகுதி உங்களுக்கு அருகில் உள்ளது?" if tamil else "I’ll exclude that area and keep your other preferences. Which city or locality would be convenient for you?"
        else:
            search = True
    if broad:
        context = {key: value for key, value in context.items() if key not in {"location", "property_type", "bedrooms", "status", "min_area_sqm"}}
        if not re.search(r"show|find|search|list|do you have|is there|cheapest|minimum", query):
            reply = "சரி, பகுதி மற்றும் சொத்து வகைக்கான விருப்பங்களை நீக்குகிறேன். பட்டியல்களைக் காட்டவா?" if tamil else "Got it—I’ll clear the area and property-type preferences and keep any budget you gave me. Would you like to see the saved options?"
    parsed = parse_request(text, data)
    # "No, just Porur" is a correction: search that area alone instead of
    # carrying a previous BHK, budget, or property type into a zero-result
    # search.
    location_only_correction = bool(
        parsed.location
        and re.fullmatch(r"\s*(?:no\s*,?\s*)?(?:just|only)\s+.+?\s*", query)
    )
    if location_only_correction:
        context = {"location": parsed.location}
        search = True
    amount = re.search(r"(?:around|about|budget is|budget of|for|under|up to)\s*₹?\s*(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr)\b", query)
    if re.search(r"\b(?:loan|emi|convert|reminder|follow.up)\b", query):
        amount = None
    if amount:
        parsed.max_budget = float(amount.group(1)) * (10000000 if amount.group(2).startswith("cr") else 100000)
    if re.search(
        r"\b(?:do you have|is there|are there)\b.*\b(?:property|properties|flats?|houses?|plots?|apartments?|options?|suggestions?)\b"
        r"|\b(?:property|home|flat|house) (?:suggestion|recommendation)s?\b",
        query,
    ):
        search = True
    # Direct requests such as "find a 2BHK" or "show homes near Velachery"
    # must search immediately, even when a budget phrase is also present.
    if re.search(
        r"\b(?:find|search|show|list|browse|recommend|suggest)\b.{0,80}"
        r"(?:\b(?:property|properties|home|homes|house|houses|flat|flats|apartment|apartments|plot|plots|land|listing|listings)\b|\b[1-9]\s*bhk\b)",
        query,
    ):
        search = True
    if cheapest and not re.search(r"why|no price|not listed", query):
        search = True
    if search or amount or broad:
        for key in ("location", "property_type", "bedrooms", "status", "min_budget", "max_budget", "min_area_sqm"):
            value = getattr(parsed, key)
            if key == "location" and remove_place and context.get("location") and str(value).casefold() in exclusions:
                continue
            if value not in (None, "", "Any"):
                context[key] = value
        # An explicitly rejected location must not be reintroduced by parsing.
        if str(context.get("location", "")).casefold() in {value.casefold() for value in exclusions}:
            context["location"] = ""
        memory = update_buyer_memory(text, context, chat, memory)
        memory["excluded_terms"] = list(dict.fromkeys(exclusions))
        if amount and not search and not broad:
            budget = f"₹{parsed.max_budget/100000:g} lakh"
            reply = (f"பட்ஜெட்டை {budget} ஆக வைத்திருக்கிறேன். இந்த வரம்பில் தேடவா?" if tamil else f"I’ll keep your budget at {budget}. Would you like me to search within that amount?")
    if re.search(r"doesn't suit|does not suit|not my preference|not suitable|not what i want", query) and not search:
        reply = "மன்னிக்கவும், அந்தப் பரிந்துரை பொருந்தவில்லை. பகுதி, பட்ஜெட் அல்லது சொத்து வகை—எது மாற வேண்டும்?" if tamil else "Sorry, that suggestion missed what you need. Is the mismatch the area, budget, or property type?"
    if reply:
        memory["excluded_terms"] = list(dict.fromkeys(exclusions))
        memory["requirements"] = context
        return {"reply": reply, "context": context, "memory": memory}
    if search:
        memory["excluded_terms"] = list(dict.fromkeys(exclusions))
        inventory = prepare_inventory(data, memory)
        status = context.get("listing_statuses", context.get("status", "Any"))
        if status == "Any":
            status = ["Existing sale", "Project reference"]
        found = search_properties(inventory, location=context.get("location", ""), property_type=context.get("property_types", context.get("property_type", "Any")),
                                  bedrooms=context.get("bedrooms"), min_budget=context.get("min_budget"), max_budget=context.get("max_budget"), min_area_sqm=context.get("min_area_sqm"), status=status)
        if cheapest:
            # Unknown or rate-only prices cannot establish the lowest total price.
            prices = pd.to_numeric(found["price_inr"], errors="coerce")
            found = found[prices.notna() & (prices > 0)]
            found = found[[format_price_for_card(row)[0] not in {"Reported rate", "Exact price"} for row in found.to_dict("records")]] if not found.empty else found
            found = found.sort_values("price_inr", kind="stable")
            context["sort"] = "price"
        else:
            found = rank_matches(found, location=context.get("location", ""), max_budget=context.get("max_budget"))
        return {"results": found, "context": context, "memory": memory}
    if records and re.search(r"amenit(?:y|ies)|basic facilities", query) and re.search(r"these|properties|all|they|them", query):
        lines = []
        for row in records:
            details = str(row.get("amenities") or "").strip()
            parking = feature_evidence(row, "parking")
            lines.append(f"**{row['title']}** — {details or ('வசதிகள் குறிப்பிடப்படவில்லை' if tamil else 'amenities not stated in the saved record')}; parking: {parking}.")
        return {"reply": "\n\n".join(lines), "context": context, "memory": memory}
    if re.search(r"(?:verify|check|validate|confirm).*(?:property|listing)|how should i verify", query):
        reply = (
            "பட்டியலைச் சரிபார்க்க: (1) அதிகாரப்பூர்வ source link-ல் தற்போதைய விலை மற்றும் கிடைப்பை உறுதிப்படுத்துங்கள், "
            "(2) title, approval/RERA விவரங்கள் மற்றும் உரிமையாளர் அடையாளத்தைச் சரிபாருங்கள், (3) இடத்தை நேரில் பார்த்து "
            "ஆவணங்கள், நிலுவைகள், possession மற்றும் maintenance கட்டணங்களை கேளுங்கள், (4) எழுத்துப்பூர்வ terms இல்லாமல் "
            "advance அனுப்பாதீர்கள். சேமித்த பதிவு ஒரு தொடக்கக் குறிப்பு மட்டுமே."
            if tamil else
            "To verify a listing: (1) open the saved source link and confirm current price and availability, (2) check title, approval/RERA details and the owner’s identity, (3) visit the property and ask for documents, possession terms, encumbrances and maintenance charges, and (4) don’t send an advance without written terms. The saved record is only a starting point."
        )
        return {"reply": reply, "context": context, "memory": memory}
    if re.search(r"what can (?:you|mira) do|how (?:do i|to) use (?:this|the) (?:website|portal)|what features", query):
        return {"reply": "சேமித்த விற்பனை மற்றும் ஏலப் பதிவுகளை உங்கள் பகுதி, பட்ஜெட், அளவு மற்றும் BHK-க்கு ஏற்ப தேடலாம்; பட்டியலின் விவரங்கள், ஆதாரங்கள், பரப்பளவு மாற்றம், EMI மற்றும் follow-up வசதிகளிலும் உதவலாம். இவை நேரடி கிடைப்பு அல்லது கடன் ஒப்புதலை உறுதிப்படுத்தாது." if tamil else "I can search saved sale listings and auctions by area, budget, property type, size and BHK, explain recorded property details and source links, and help with area conversion, illustrative EMI and follow-ups. Saved records don’t confirm live availability or loan approval. What would you like help with?", "context": context, "memory": memory}
    if re.search(r"(?:no|not|missing|why).*price|price.*(?:missing|not listed|not provided)", query):
        return {"reply": "விலை காலியாக இருந்தால் மூலத்தில் விலை வெளியிடப்படவில்லை. திட்டப் பதிவு குறிப்பிட்ட வீட்டின் விற்பனை விலையை உறுதிப்படுத்தாது." if tamil else "A blank price means the saved source did not publish a usable price. Project references may describe a project without giving a specific unit’s sale price; I won’t guess it.", "context": context, "memory": memory}
    # Find a named property anywhere in the dataset, even if it is not in the shortlist.
    named = [row for row in data.to_dict("records") if len(str(row.get("title") or "")) >= 5 and str(row["title"]).casefold() in query]
    selected = memory.get("selected")
    if selected and re.search(r"official portal|source (?:link|portal)|guide me.*portal", query):
        url = str(selected.get("source_url") or "")
        reply = f"The saved source for **{selected.get('title')}** is [{selected.get('source_name') or 'the source portal'}]({url}). Confirm current prices and availability there." if url.startswith(("http://", "https://")) else "This saved record has no source URL. I can help check another recorded detail."
        return {"reply": reply, "context": context, "memory": memory}
    if not named and records and re.search(r"recommend me one|choose one|pick one", query):
        named = [records[0]]
    if named:
        row = max(named, key=lambda item: len(str(item["title"])))
        memory["selected"] = row
        fields = [("property_type", "Type"), ("locality", "Location"), ("price_display", "Published price"), ("area_display", "Area"), ("bedrooms", "BHK"), ("amenities", "Amenities"), ("car_parking", "Parking"), ("availability", "Saved availability"), ("possession_type", "Possession"), ("facing", "Facing"), ("floor_number", "Floor"), ("furnished_status", "Furnishing"), ("approval_number", "Approval reference"), ("rera_number", "RERA"), ("auction_end", "Auction end"), ("emd_deadline", "EMD deadline"), ("source_date", "Source date")]
        details = [f"{label}: {row[field]}" for field, label in fields if str(row.get(field) or "").strip() and str(row.get(field)).lower() != "nan"]
        reply = f"**{row['title']}** ({row.get('listing_status', '')}) — " + "; ".join(details) + "."
        url = str(row.get("source_url") or "")
        if url.startswith(("http://", "https://")):
            reply += f" [Saved source]({url})."
        reply += " Current availability must be verified with the source."
        return {"reply": reply, "context": context, "memory": memory}
    return None
