"""Bounded, source-grounded recommendation snapshots for consented follow-ups."""
from urllib.parse import urlparse


def _text(value, fallback=""):
    text = str(value).strip() if value is not None else ""
    return fallback if text.casefold() in {"", "nan", "none", "<na>"} else text


def recommendation_snapshot(records, preferences=None):
    preferences = preferences or {}
    criteria = []
    for key, label in (("location", "Area"), ("property_type", "Type"), ("bedrooms", "BHK"), ("min_budget", "Minimum budget INR"), ("max_budget", "Maximum budget INR")):
        if preferences.get(key) is not None:
            criteria.append(f"{label}: {preferences[key]}")
    lead = "; ".join(criteria)[:220]
    parts = [lead] if lead else []
    if not records:
        parts.append("No matching saved listings were captured for this search. Mira suggests changing one preference while retaining the others.")
    for record in records[:3]:
        title = _text(record.get("title"), "Saved listing")[:100]
        location = _text(record.get("location"), _text(record.get("district")))[:60]
        price = _text(record.get("price_display"), "Price not reported")[:65]
        url = _text(record.get("source_url"), _text(record.get("url")))
        if urlparse(url).scheme not in {"https", "http"} or not urlparse(url).hostname:
            url = "Source link not recorded"
        line = f"{title} — {location}; recorded price: {price}; source: {url}"
        # Do not truncate URLs or make a larger unsourced recommendation list.
        if sum(len(p) for p in parts) + len(line) > 700:
            parts.append("More saved recommendations are available in the website search results.")
            break
        parts.append(line)
    parts.append("Next steps: confirm price and availability with each source. For finance, use Namma Veedu's Loans panel to compare official lender terms and illustrative EMI; eligibility, fees and rates can vary.")
    return " ".join(" ".join(part.split()) for part in parts)[:950]
