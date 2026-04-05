"""Custom exception hierarchy for city3dmodels pipeline."""


class City3DError(Exception):
    """Base class for all pipeline errors."""


class GeocoderError(City3DError):
    """Raised when a city cannot be geocoded."""


class OSMFetchError(City3DError):
    """Raised on Overpass API network or query failure."""


class ValidationError(City3DError):
    """Raised when validation finds critical errors in data or output."""
