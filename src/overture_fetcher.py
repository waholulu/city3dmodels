"""Fetch building footprints from Overture Maps via DuckDB + S3 GeoParquet.

Overture Maps Foundation publishes monthly building releases that fuse
OpenStreetMap, Microsoft ML Building Footprints, Google Open Buildings, and
other sources into a single global GeoParquet dataset. We query it directly
from the public S3 bucket using DuckDB's httpfs extension with bbox pushdown,
so only the relevant rows are streamed back.

Reference: https://docs.overturemaps.org/schema/reference/buildings/building/
"""

from __future__ import annotations

import os
import time

from shapely import from_wkb
from shapely.geometry import Polygon
from shapely.validation import make_valid

from .exceptions import OSMFetchError
from .osm_fetcher import (
    BuildingFootprint,
    _make_transformer,
    compute_bbox,
    _DEFAULT_HEIGHT_M,
    _METRES_PER_FLOOR,
)

# Overture release to query. Releases are published roughly monthly;
# override with the OVERTURE_RELEASE env var if a newer one is desired.
_DEFAULT_RELEASE = os.environ.get("OVERTURE_RELEASE", "2026-04-15.0")
_S3_BUCKET = "overturemaps-us-west-2"
_S3_REGION = "us-west-2"


def _release_path(release: str) -> str:
    """Return the S3 glob path for a given Overture release's buildings layer."""
    return (
        f"s3://{_S3_BUCKET}/release/{release}"
        f"/theme=buildings/type=building/*"
    )


def _connect():
    """Open a DuckDB connection configured to read the public Overture bucket.

    Imported lazily so users who only ever use --source osm don't need duckdb.
    """
    try:
        import duckdb
    except ImportError as exc:
        raise OSMFetchError(
            "Overture source requires duckdb. Install with: pip install duckdb"
        ) from exc
    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_region='{_S3_REGION}';")
    return con


def _resolve_height(height: float | None, num_floors: int | None) -> tuple[float, int | None]:
    """Mirror osm_fetcher's height resolution priority."""
    if height is not None and height > 0:
        return float(height), num_floors if (num_floors and num_floors > 0) else None
    if num_floors is not None and num_floors > 0:
        return num_floors * _METRES_PER_FLOOR, int(num_floors)
    return _DEFAULT_HEIGHT_M, None


def _synthesize_raw_tags(height: float | None, num_floors: int | None, cls: str | None) -> dict:
    """Build a raw_tags dict that lets the existing validator stats stay meaningful.

    The validator counts buildings without explicit height by checking
    raw_tags['building:height'] / raw_tags['height'] — populate them when
    Overture supplies a value, leave empty when we fell back to the default.
    """
    tags: dict[str, str] = {}
    if height is not None and height > 0:
        tags["height"] = str(float(height))
    if num_floors is not None and num_floors > 0:
        tags["building:levels"] = str(int(num_floors))
    if cls:
        tags["building"] = str(cls)
    return tags


def _row_to_footprint(
    row: tuple,
    transformer,
    origin_x: float,
    origin_y: float,
) -> list[BuildingFootprint]:
    """Convert one DuckDB row into one or more BuildingFootprints.

    A row may carry a MultiPolygon geometry (rare for buildings); each
    component polygon becomes its own BuildingFootprint so downstream
    extrusion can treat them independently.
    """
    feature_id, wkb_bytes, height, num_floors, cls, subtype = row
    if wkb_bytes is None:
        return []

    try:
        geom = from_wkb(bytes(wkb_bytes))
    except Exception:
        return []

    if geom.is_empty:
        return []

    if not geom.is_valid:
        geom = make_valid(geom)
        if geom.is_empty or not geom.is_valid:
            return []

    if geom.geom_type == "Polygon":
        polygons = [geom]
    elif geom.geom_type == "MultiPolygon":
        polygons = [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    elif geom.geom_type == "GeometryCollection":
        polygons = [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    else:
        return []

    h_m, lvl = _resolve_height(height, num_floors)
    tags = _synthesize_raw_tags(height, num_floors, cls or subtype)
    building_type = (cls or subtype or "yes")

    out: list[BuildingFootprint] = []
    for poly in polygons:
        # Reproject from WGS84 (lon, lat) to local metres centred on origin
        local_coords = [
            (
                transformer.transform(x, y)[0] - origin_x,
                transformer.transform(x, y)[1] - origin_y,
            )
            for x, y in poly.exterior.coords
        ]
        if len(local_coords) < 4:
            continue

        local_holes = []
        for interior in poly.interiors:
            ring = [
                (
                    transformer.transform(x, y)[0] - origin_x,
                    transformer.transform(x, y)[1] - origin_y,
                )
                for x, y in interior.coords
            ]
            if len(ring) >= 4:
                local_holes.append(ring)

        try:
            local_poly = Polygon(local_coords, local_holes)
            if not local_poly.is_valid:
                local_poly = make_valid(local_poly)
            if local_poly.is_empty or not local_poly.is_valid:
                continue
            if local_poly.geom_type != "Polygon":
                parts = [g for g in local_poly.geoms if g.geom_type == "Polygon"]
                if not parts:
                    continue
                local_poly = max(parts, key=lambda p: p.area)
        except Exception:
            continue

        out.append(BuildingFootprint(
            osm_id=str(feature_id),
            osm_type="overture",
            polygon=local_poly,
            height_m=h_m,
            building_type=building_type,
            levels=lvl,
            raw_tags=tags,
        ))
    return out


def _query_overture(
    south: float,
    west: float,
    north: float,
    east: float,
    release: str,
    max_retries: int = 3,
) -> list[tuple]:
    """Run the bbox-filtered DuckDB query, with simple retry on transient errors.

    Connection setup (including the duckdb import) happens once outside the
    retry loop so missing-dependency errors surface immediately instead of
    being swallowed and retried for 35 seconds.
    """
    sql = f"""
        SELECT
            id,
            geometry,
            height,
            num_floors,
            class,
            subtype
        FROM read_parquet('{_release_path(release)}', filename=false, hive_partitioning=1)
        WHERE bbox.xmax >= ?
          AND bbox.xmin <= ?
          AND bbox.ymax >= ?
          AND bbox.ymin <= ?
    """
    con = _connect()
    try:
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return con.execute(sql, [west, east, south, north]).fetchall()
            except Exception as exc:
                last_exc = exc
                if attempt == max_retries - 1:
                    break
                time.sleep(5 * (2 ** attempt))  # 5s, 10s, 20s
        raise OSMFetchError(
            f"Overture query failed after {max_retries} attempts (release={release}): {last_exc}"
        ) from last_exc
    finally:
        con.close()


def fetch_buildings_bbox(
    south: float,
    west: float,
    north: float,
    east: float,
    origin_lat: float,
    origin_lon: float,
    verbose: bool = False,
    release: str = _DEFAULT_RELEASE,
) -> list[BuildingFootprint]:
    """Fetch Overture building footprints for an explicit bbox."""
    if verbose:
        print(
            f"  Querying Overture release {release} "
            f"(bbox: {south:.4f},{west:.4f} → {north:.4f},{east:.4f}) ..."
        )

    rows = _query_overture(south, west, north, east, release=release)
    if verbose:
        print(f"  Received {len(rows)} candidate buildings from Overture")

    transformer = _make_transformer(origin_lat, origin_lon)
    origin_x, origin_y = transformer.transform(origin_lon, origin_lat)

    footprints: list[BuildingFootprint] = []
    for row in rows:
        footprints.extend(_row_to_footprint(row, transformer, origin_x, origin_y))

    if verbose:
        print(f"  Parsed {len(footprints)} valid Overture footprints")
    return footprints


def fetch_buildings(
    lat: float,
    lon: float,
    radius_m: float,
    verbose: bool = False,
    release: str = _DEFAULT_RELEASE,
) -> list[BuildingFootprint]:
    """Fetch Overture building footprints within radius_m of (lat, lon).

    Args:
        lat, lon:  Centre in WGS84 decimal degrees.
        radius_m:  Radius of the area to fetch, in metres.
        verbose:   Print progress messages.
        release:   Overture release tag (default tracks _DEFAULT_RELEASE).

    Returns:
        List of BuildingFootprint with coordinates in local metres
        (origin at the supplied centre).

    Raises:
        OSMFetchError: on network failure or DuckDB error.
    """
    south, west, north, east = compute_bbox(lat, lon, radius_m)
    return fetch_buildings_bbox(
        south=south,
        west=west,
        north=north,
        east=east,
        origin_lat=lat,
        origin_lon=lon,
        verbose=verbose,
        release=release,
    )
