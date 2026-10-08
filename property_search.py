"""Local CSV search, ranking, and filtering for property records."""

from __future__ import annotations

from pathlib import Path
import re
import pandas as pd
from area_utils import price_per_sqm

DATA_FILE = Path(__file__).parent / "data" / "properties.csv"


def _normalize_explicit_project_prices(data: pd.DataFrame) -> None:
    """Convert explicit crore/lakh source text to INR without changing the CSV."""
    for index, record in data.iterrows():
        display = str(record.get("price_display") or "").strip()
        folded = display.casefold()
        basis = str(record.get("price_basis") or "").casefold()
        source_status = str(record.get("source_status") or "").casefold()
        notes = str(record.get("notes") or "").casefold()
        if not display:
            continue
        # Estimated/comparable figures are useful context in the source file,
        # but they are not exact property prices and must not match a budget.
        if any(term in folded or term in basis or term in source_status or term in notes
               for term in ("estimate", "approx", "benchmark", "comparable")):
            data.at[index, "price_inr"] = float("nan")
            data.at[index, "price_per_sqm_inr"] = float("nan")
            continue
        # Multiple currency-tagged amounts usually describe different unit
        # configurations or a range; they cannot be reduced to one budget price.
        quoted_amounts = re.findall(r"₹\s*\d[\d,]*(?:\.\d+)?", display)
        if len(quoted_amounts) > 1:
            data.at[index, "price_inr"] = float("nan")
            data.at[index, "price_per_sqm_inr"] = float("nan")
            continue
        # A rate is not a total property price and must not feed price filters
        # or the total-price-per-area calculation.
        if re.search(r"(?:/|\bper\s*)(?:sq\.?\s*ft|sqft|square\s*feet|sq\.?\s*m|sqm|square\s*met(?:er|re)s?|acre|acres|cent|cents|ground|grounds)\b", folded):
            data.at[index, "price_inr"] = float("nan")
            data.at[index, "price_per_sqm_inr"] = float("nan")
            continue
        multiplier = 10_000_000 if re.search(r"\b(?:crore|crores|cr)\b", folded) else 100_000 if re.search(r"\b(?:lakh|lakhs|lac|lacs)\b", folded) else None
        if multiplier is None:
            continue
        amount = re.search(r"₹\s*(\d[\d,]*(?:\.\d+)?)", display)
        if not amount:
            amount = re.search(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:crore|crores|cr|lakh|lakhs|lac|lacs)\b", folded)
        if not amount:
            data.at[index, "price_inr"] = float("nan")
            data.at[index, "price_per_sqm_inr"] = float("nan")
            continue
        price_inr = round(float(amount.group(1).replace(",", "")) * multiplier, 2)
        data.at[index, "price_inr"] = price_inr
        area_value = pd.to_numeric(record.get("area_value"), errors="coerce")
        area_unit = str(record.get("area_unit") or "").strip()
        if pd.notna(area_value) and area_value > 0 and area_unit:
            try:
                data.at[index, "price_per_sqm_inr"] = price_per_sqm(price_inr, area_value, area_unit)
            except ValueError:
                data.at[index, "price_per_sqm_inr"] = float("nan")


def format_price_for_card(record: dict) -> tuple[str, str]:
    """Return a source-faithful price label and display string for a card."""
    raw_display = record.get("price_display")
    display = "" if raw_display is None or pd.isna(raw_display) else str(raw_display).strip()
    folded = display.casefold()
    basis = str(record.get("price_basis") or "").casefold()
    rate_pattern = r"(?:/|\bper\s*)(?:sq\.?\s*ft|sqft|square\s*feet|sq\.?\s*m|sqm|square\s*met(?:er|re)s?|acre|acres|cent|cents|ground|grounds)\b"
    if display and re.search(rate_pattern, folded):
        return "Reported rate", display

    if any(term in folded or term in basis for term in ("estimate", "approx", "benchmark", "comparable")):
        return "Exact price", "Not provided"

    if len(re.findall(r"₹\s*\d[\d,]*(?:\.\d+)?", display)) > 1:
        return "Published prices", display

    price = pd.to_numeric(record.get("price_inr"), errors="coerce")
    label = "Starting price" if basis == "starting price" or "onwards" in folded else "Price / reserve"
    if re.search(r"\b(?:crore|crores|cr)\b", folded) and pd.notna(price):
        amount = f"{price / 10_000_000:,.2f}".rstrip("0").rstrip(".")
        suffix = " onwards" if "onwards" in folded else ""
        return label, f"₹{amount} Cr{suffix}"
    if re.search(r"\b(?:lakh|lakhs|lac|lacs)\b", folded) and pd.notna(price):
        amount = f"{price / 100_000:,.2f}".rstrip("0").rstrip(".")
        suffix = " onwards" if "onwards" in folded else ""
        return label, f"₹{amount} lakh{suffix}"
    if pd.notna(price):
        return label, f"₹{price:,.0f}"
    return "Price / reserve", "Price not provided"


def load_properties(path: str | Path = DATA_FILE) -> pd.DataFrame:
    data = pd.read_csv(path, keep_default_na=False)
    if "bedrooms" in data:
        # Keep source wording such as "2 & 3 BHK" for accurate filtering; the
        # numeric field remains available for calculations and display.
        data["_bedrooms_text"] = data["bedrooms"].astype(str).str.strip()
    for column in ("price_inr", "area_value", "area_sqm", "price_per_sqm_inr", "bedrooms"):
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    _normalize_explicit_project_prices(data)
    data["is_auction_open"] = data["auction_end"].apply(_is_future_date)
    auction_rows = data["listing_status"].isin(("Auction", "Auction ended"))
    data.loc[auction_rows, "listing_status"] = data.loc[auction_rows, "is_auction_open"].map(
        {True: "Auction", False: "Auction ended"}
    )
    return data


def _is_future_date(value: str) -> bool:
    if not value:
        return False
    try:
        return pd.Timestamp(value).date() >= pd.Timestamp.now().date()
    except (TypeError, ValueError):
        return False


def search_properties(
    data: pd.DataFrame,
    *,
    location: str | list[str] | tuple[str, ...] = "",
    property_type: str | list[str] | tuple[str, ...] = "Any",
    bedrooms: int | None = None,
    status: str | list[str] | tuple[str, ...] = "Any",
    min_budget: float | None = None,
    max_budget: float | None = None,
    min_area_sqm: float | None = None,
    max_area_sqm: float | None = None,
    include_ended_auctions: bool = False,
) -> pd.DataFrame:
    result = data.copy()
    def selected_values(value: str | list[str] | tuple[str, ...]) -> list[str]:
        values = [value] if isinstance(value, str) else list(value)
        return [str(item).strip() for item in values if str(item).strip() and str(item).strip() != "Any"]

    locations = selected_values(location)
    if locations:
        columns = ["city", "district", "locality", "location"]
        present = [c for c in columns if c in result]
        mask = pd.Series(False, index=result.index)
        for selected_location in locations:
            needle = selected_location.casefold()
            # Match a locality as words, so Porur does not accidentally match
            # Thiruporur. This still includes compound localities such as
            # Kattupakkam Porur.
            location_pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
            for column in present:
                mask |= result[column].astype(str).str.casefold().str.contains(location_pattern, regex=True, na=False)
        result = result[mask]
    property_types = selected_values(property_type)
    if property_types:
        result = result[result["property_type"].isin(property_types)]
    if bedrooms is not None:
        bedroom_count = int(bedrooms)
        numeric_match = pd.to_numeric(result.get("bedrooms", pd.Series(index=result.index, dtype="float64")), errors="coerce").eq(bedroom_count)
        searchable_bedrooms = result.get("_bedrooms_text", pd.Series("", index=result.index)).astype(str)
        searchable_title = result.get("title", pd.Series("", index=result.index)).astype(str)
        pattern = rf"(?<!\d){bedroom_count}\s*[- ]?BHK\b"
        text_match = searchable_bedrooms.str.contains(pattern, case=False, regex=True, na=False) | searchable_title.str.contains(pattern, case=False, regex=True, na=False)
        result = result[numeric_match | text_match]
    statuses = selected_values(status)
    if statuses:
        selected_statuses = set(statuses)
        if "Auction" in selected_statuses and include_ended_auctions:
            selected_statuses.add("Auction ended")
        result = result[result["listing_status"].isin(selected_statuses)]
    else:
        # Approval register rows and records with no auction date are not
        # confirmed offers. The latter are available only by explicitly
        # requesting their separate status after Mira asks the user.
        result = result[~result["listing_status"].isin(("Approval record", "Auction date not listed"))]
    if not include_ended_auctions:
        result = result[result["listing_status"].ne("Auction ended")]
        if "is_auction_open" in result:
            result = result[~((result["listing_status"] == "Auction") & ~result["is_auction_open"])]
    if min_budget is not None:
        result = result[result["price_inr"].notna() & (result["price_inr"] >= min_budget)]
    if max_budget is not None:
        result = result[result["price_inr"].notna() & (result["price_inr"] <= max_budget)]
    if min_area_sqm is not None:
        result = result[result["area_sqm"].notna() & (result["area_sqm"] >= min_area_sqm)]
    if max_area_sqm is not None:
        result = result[result["area_sqm"].notna() & (result["area_sqm"] <= max_area_sqm)]
    return result.sort_values(
        ["source_status", "price_per_sqm_inr"], ascending=[True, True], na_position="last"
    ).reset_index(drop=True)


def rank_matches(data: pd.DataFrame, *, location: str = "", max_budget: float | None = None) -> pd.DataFrame:
    """A simple explainable ranking; it is not an investment forecast."""
    result = data.copy()
    result["match_reasons"] = "Property type and available details"
    if location:
        location_fields = result.reindex(columns=["city", "district", "locality", "location"], fill_value="")
        location_fields = location_fields.fillna("").astype(str)
        location_match = pd.Series(
            [location.casefold() in " ".join(location_fields.iloc[row].tolist()).casefold()
             for row in range(len(location_fields))],
            index=location_fields.index,
            dtype=bool,
        )
        result.loc[location_match, "match_reasons"] = "Matches your area; " + result.loc[location_match, "match_reasons"]
    if max_budget is not None:
        within = result["price_inr"].notna() & (result["price_inr"] <= max_budget)
        result.loc[within, "match_reasons"] = "Within budget; " + result.loc[within, "match_reasons"]
    return result

