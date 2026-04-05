"""Geocode a city name to (latitude, longitude) using Nominatim."""

import time
import requests

from .exceptions import GeocoderError

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "city3dmodels/1.0"


def geocode_city(city_name: str) -> tuple[float, float]:
    """
    Resolve city_name to (latitude, longitude) using Nominatim.

    Args:
        city_name: Human-readable city name, e.g. "New York" or "Berlin, Germany".

    Returns:
        (lat, lon) as floats in WGS84 decimal degrees.

    Raises:
        GeocoderError: city not found, rate-limited, or network failure.
    """
    # Nominatim ToS: max 1 request/second
    time.sleep(1)

    # Try geopy first; fall back to direct requests if unavailable
    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderServiceError

        geolocator = Nominatim(user_agent=_USER_AGENT)
        try:
            location = geolocator.geocode(city_name, exactly_one=True, timeout=10)
        except GeocoderServiceError as exc:
            raise GeocoderError(f"Geocoding service error: {exc}") from exc

        if location is None:
            raise GeocoderError(f"City not found: '{city_name}'")
        return float(location.latitude), float(location.longitude)

    except ImportError:
        return _nominatim_fallback(city_name)


def _nominatim_fallback(city_name: str) -> tuple[float, float]:
    """Direct requests call to Nominatim JSON API (fallback if geopy unavailable)."""
    params = {
        "q": city_name,
        "format": "json",
        "limit": 1,
    }
    headers = {"User-Agent": _USER_AGENT}
    try:
        resp = requests.get(_NOMINATIM_URL, params=params, headers=headers, timeout=10)
    except requests.exceptions.ConnectionError as exc:
        raise GeocoderError("Network error; check internet connection.") from exc
    except requests.exceptions.Timeout as exc:
        raise GeocoderError("Geocoding request timed out.") from exc

    if resp.status_code != 200:
        raise GeocoderError(
            f"Nominatim returned HTTP {resp.status_code} for '{city_name}'"
        )

    results = resp.json()
    if not results:
        raise GeocoderError(f"City not found: '{city_name}'")

    return float(results[0]["lat"]), float(results[0]["lon"])
