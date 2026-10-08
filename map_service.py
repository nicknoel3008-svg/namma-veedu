"""Safe, cached map points for saved property suggestions."""

from __future__ import annotations

from typing import Any
import requests
import streamlit as st


@st.cache_data(ttl=86400, show_spinner=False)
def _mapbox_point(query: str, token: str) -> tuple[float, float] | None:
    """Resolve a locality to an approximate point, never an invented address."""
    if not query.strip() or not token.strip():
        return None
    try:
        response = requests.get(
            "https://api.mapbox.com/geocoding/v5/mapbox.places/" + requests.utils.quote(query),
            params={
                "access_token": token,
                "country": "IN",
                "bbox": "76.0,8.0,80.5,13.6",
                "limit": 1,
                "types": "place,locality,neighborhood",
            },
            headers={"User-Agent": "Namma-Illam/1.0 property-guide"},
            timeout=8,
        )
        response.raise_for_status()
        features = response.json().get("features") or []
        coordinates = features[0].get("center") if features else None
        if not coordinates or len(coordinates) < 2:
            return None
        return float(coordinates[1]), float(coordinates[0])
    except Exception:
        return None


def map_points(records: list[dict[str, Any]], token: str) -> tuple[list[dict[str, Any]], bool]:
    """Return points and whether any point is exact in the source data."""
    points: list[dict[str, Any]] = []
    has_exact = False
    for record in records:
        latitude = record.get("latitude", record.get("lat"))
        longitude = record.get("longitude", record.get("lon", record.get("lng")))
        try:
            lat, lon = float(latitude), float(longitude)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
            label = "Exact source coordinates"
            has_exact = True
        except (TypeError, ValueError):
            locality = str(record.get("locality") or record.get("city") or "").strip()
            place = ", ".join(value for value in (locality, str(record.get("district") or "").strip(), "Tamil Nadu") if value)
            resolved = _mapbox_point(place, token)
            if not resolved:
                continue
            lat, lon = resolved
            label = "Approximate locality"
        points.append({"lat": lat, "lon": lon, "Property": str(record.get("title") or record.get("property_id") or "Property"), "Location confidence": label})
    return points, has_exact
