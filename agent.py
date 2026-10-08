"""Small offline conversational parser. No paid API or external model required."""

from __future__ import annotations

from dataclasses import dataclass
import re
import pandas as pd


@dataclass
class SearchIntent:
    location: str = ""
    property_type: str = "Any"
    bedrooms: int | None = None
    status: str = "Any"
    max_budget: float | None = None
    min_area_sqm: float | None = None
    sort: str = "match"
    help_with_loan: bool = False
    compare: bool = False
    area_question: bool = False


TYPE_TERMS = {
    "Plot": ("plot", "plots", "land", "site", "sites"),
    "House": ("house", "houses", "home", "homes", "villa", "bungalow"),
    "Flat": ("flat", "flats", "apartment", "apartments"),
}


def parse_request(text: str, data: pd.DataFrame) -> SearchIntent:
    query = text.strip().lower()
    query = re.sub(r"([\d,.]+)\s*லட்ச(?:த்திற்குள்|க்குள்)", r"under \1 lakh", query)
    # A small local phrase map supports common Tamil and Tanglish searches.
    for source, target in {
        "வீடுகள்": " houses ", "வீடு": " house ", "வீட்டு": " house ", "வீட்டில்": " house ",
        "மனை": " plot ", "நிலம்": " land ", "அடுக்குமாடி": " apartment ",
        "குடியிருப்பு": " residential ", "ஏலம்": " auction ", "கடன்": " loan ",
        "சென்னை": " chennai ", "கோயம்புத்தூர்": " coimbatore ", "கோவை": " coimbatore ",
        "மதுரை": " madurai ", "திருச்சி": " trichy ", "திருச்சிராப்பள்ளி": " trichy ",
        "சேலம்": " salem ", "ஈரோடு": " erode ", "வேலூர்": " vellore ",
        "என்னிடம்": " ", "காட்டு": " show ", "வேண்டும்": " want ", "லட்சம்": " lakh ",
    }.items():
        query = query.replace(source, target)
    query = query.replace("veedu", "house").replace("manai", "plot").replace("nilam", "land")
    intent = SearchIntent()
    query = re.sub(r"\b(?:not|no|without|don't want|do not want)\s+(?:a\s+)?(?:plots?|flats?|apartments?|houses?|land)\b", "", query)
    for label, terms in TYPE_TERMS.items():
        if any(re.search(rf"\b{re.escape(term)}\b", query) for term in terms):
            intent.property_type = label
            break
    bedroom_match = re.search(r"\b([1-9])\s*[- ]?(?:bhk|bedrooms?|beds?)\b", query)
    if bedroom_match:
        intent.property_type = "Flat" if intent.property_type == "Any" else intent.property_type
        intent.bedrooms = int(bedroom_match.group(1))
    if any(word in query for word in ("auction", "bank sale", "reserve price", "emd")):
        intent.status = "Auction"
    elif any(word in query for word in ("resale", "previously owned", "pre-owned", "used", "owner sale")):
        intent.status = "Existing sale"
    elif any(word in query for word in ("new project", "promoter", "developer project")):
        intent.status = "Project reference"
    budget = re.search(r"(?:under|below|within|up to|max(?:imum)?|budget(?: of)?(?:\s+(?:around|about|approximately))?)\s*₹?\s*(\d+(?:,\d{2,3})*(?:\.\d+)?)\s*(crore|crores|cr|lakh|lakhs|lac|lacs|k)?", query)
    # Natural Tanglish often places the amount before the word "budget", for
    # example: "50 lakh budget". Keep this equivalent to "budget 50 lakh".
    if not budget:
        budget = re.search(r"\b(\d+(?:,\d{2,3})*(?:\.\d+)?)\s*(crore|crores|cr|lakh|lakhs|lac|lacs|k)\s+budget\b", query)
    if budget:
        amount = float(budget.group(1).replace(",", ""))
        unit = budget.group(2) or ""
        intent.max_budget = amount * (10_000_000 if unit.startswith(("crore", "cr")) else 100_000 if unit.startswith(("lakh", "lac")) else 1_000 if unit == "k" else 1)
    elif re.search(r"\b(?:instead|actually|make it|stretch|increase|reduce|only|can do|afford)\b", query):
        revised = re.search(r"\b(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?)\b", query)
        if revised:
            intent.max_budget = float(revised.group(1)) * (10_000_000 if revised.group(2).startswith("cr") else 100_000)
    size = re.search(r"(?:over|above|at least|minimum|min)\s*([\d,.]+)\s*(?:sq\s*m|sqm|square\s*met(?:er|re)s?)", query)
    if size:
        intent.min_area_sqm = float(size.group(1).replace(",", ""))
    intent.help_with_loan = any(word in query for word in ("loan", "finance", "emi", "home loan", "housing loan"))
    intent.compare = any(word in query for word in ("compare", "versus", " vs "))
    intent.area_question = any(word in query for word in ("square metre", "square meter", "per sqm", "per sq m", "convert", "area in"))
    if any(word in query for word in ("cheapest", "most affordable", "lowest price", "minimum value", "minimum price", "lowest value", "least expensive")):
        intent.sort = "price"
    elif any(word in query for word in ("largest", "biggest", "most spacious")):
        intent.sort = "area"
    # Resolve a locality exactly before considering a larger locality that
    # merely contains the same word (for example, Porur before Thiruporur).
    places_by_column = {
        column: {str(value).strip() for value in data.get(column, []) if str(value).strip()}
        for column in ("locality", "city", "district")
    }
    for column in ("locality", "city", "district"):
        exact = next((place for place in places_by_column[column] if place.casefold() == query.strip()), None)
        if exact:
            intent.location = exact
            break
        exact = next((place for place in places_by_column[column]
                      if re.search(r"(?<!\w)" + re.escape(place.casefold()) + r"(?!\w)", query)), None)
        if exact:
            intent.location = exact
            break
    # City names can also appear in locality cells with inconsistent casing.
    for city in sorted({str(x).strip() for x in data.get("city", []) if str(x).strip()}):
        if city.casefold() == intent.location.casefold():
            intent.location = city
            break
    # If the customer says an area in colloquial Tamil/Tanglish ("Taramani
    # pakkathula", "Velachery la"), retain the named area even when the
    # catalogue has no exact row for it. The UI can then explain that the
    # saved records need widening instead of silently dropping the request.
    if not intent.location:
        colloquial_area = re.search(
            r"\b([a-z][a-z-]{2,}(?:\s+[a-z][a-z-]{2,})?)\s+(?:pakkathula|pakathula|la|ile|il)\b",
            query,
        )
        if colloquial_area:
            candidate = colloquial_area.group(1).strip()
            if candidate not in {"budget", "office", "home", "work", "area", "city"}:
                intent.location = candidate.title()
    return intent


def friendly_reply(count: int, intent: SearchIntent) -> str:
    if count == 0:
        exact = f" {intent.bedrooms} BHK" if intent.bedrooms else ""
        return f"I couldn’t find a{exact} match in the saved listings. Would you like to widen the area or adjust the budget?"
    where = f" around {intent.location}" if intent.location else " across Tamil Nadu"
    kind = f" {intent.bedrooms} BHK {intent.property_type.lower()}" if intent.bedrooms else f" {intent.property_type.lower()}" if intent.property_type != "Any" else " property"
    return f"I found {count} saved{kind} option{'s' if count != 1 else ''}{where}, and put up to three in the results panel. Is there one you’d like to look at more closely?"

