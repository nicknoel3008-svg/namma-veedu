"""Area conversions and transparent property price calculations."""

SQFT_PER_SQM = 10.7639104167
SQFT_PER_CENT = 435.6
SQFT_PER_ACRE = 43_560
SQFT_PER_HECTARE = SQFT_PER_SQM * 10_000
SQFT_PER_GROUND = 2_400  # Common Tamil Nadu convention; verify the local deed.

TO_SQFT = {
    "sq ft": 1.0,
    "sqft": 1.0,
    "square feet": 1.0,
    "square foot": 1.0,
    "sq m": SQFT_PER_SQM,
    "sqm": SQFT_PER_SQM,
    "square metres": SQFT_PER_SQM,
    "square meters": SQFT_PER_SQM,
    "cent": SQFT_PER_CENT,
    "cents": SQFT_PER_CENT,
    "acre": SQFT_PER_ACRE,
    "acres": SQFT_PER_ACRE,
    "hectare": SQFT_PER_HECTARE,
    "hectares": SQFT_PER_HECTARE,
    "ha": SQFT_PER_HECTARE,
    "ground": SQFT_PER_GROUND,
    "grounds": SQFT_PER_GROUND,
}


def to_square_feet(value: float, unit: str) -> float:
    """Convert a known area unit to square feet; reject unknown units."""
    key = " ".join(str(unit).strip().lower().replace("²", "2").split())
    if key not in TO_SQFT:
        raise ValueError(f"Unsupported area unit: {unit}")
    return float(value) * TO_SQFT[key]


def convert_area(value: float, unit: str) -> dict[str, float]:
    sqft = to_square_feet(value, unit)
    return {
        "sq_ft": sqft,
        "sq_m": sqft / SQFT_PER_SQM,
        "cents": sqft / SQFT_PER_CENT,
        "acres": sqft / SQFT_PER_ACRE,
        "grounds": sqft / SQFT_PER_GROUND,
    }


def price_per_sqm(price_inr: float, area_value: float, area_unit: str) -> float:
    """Return INR per square metre from price and a reported area value."""
    sqm = to_square_feet(area_value, area_unit) / SQFT_PER_SQM
    if sqm <= 0:
        raise ValueError("Area must be greater than zero")
    return float(price_inr) / sqm

