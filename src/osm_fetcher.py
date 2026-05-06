"""Fetch building footprints from OpenStreetMap via Overpass API."""

import math
import time
from dataclasses import dataclass, field

import overpy
import pyproj
from shapely.geometry import Polygon, box as shapely_box
from shapely.validation import make_valid

from .exceptions import OSMFetchError

# Overpass API endpoint (uses the main instance)
_OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"

# Default building height when no tags provide it (3 floors × 3 m)
_DEFAULT_HEIGHT_M = 9.0
_METRES_PER_FLOOR = 3.0


@dataclass
class BuildingFootprint:
    osm_id: int | str           # OSM ID (int) or Overture GERS ID (str)
    osm_type: str               # "way" / "relation" / "overture"
    polygon: Polygon            # Shapely polygon in local metres (origin-centred)
    height_m: float             # Building height in metres
    building_type: str          # OSM building= tag, or Overture class
    levels: int | None          # Number of floors, if known
    raw_tags: dict = field(default_factory=dict)


def compute_bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """
    Compute (south, west, north, east) bounding box in decimal degrees.
    Uses simple degree-per-metre conversion; accurate enough for ≤5 km radius.
    """
    delta_lat = radius_m / 111_320.0
    delta_lon = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return (lat - delta_lat, lon - delta_lon, lat + delta_lat, lon + delta_lon)


def _select_utm_epsg(lat: float, lon: float) -> int:
    """Return the EPSG code for the UTM zone covering (lat, lon)."""
    zone = int((lon + 180.0) / 6.0) + 1
    return 32600 + zone if lat >= 0 else 32700 + zone


def _make_transformer(lat: float, lon: float) -> pyproj.Transformer:
    """Create a WGS84 → UTM transformer for the given location."""
    epsg = _select_utm_epsg(lat, lon)
    return pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)


def _resolve_height(tags: dict) -> tuple[float, int | None]:
    """
    Extract building height from OSM tags.
    Priority: building:height > height > building:levels*3 > levels*3 > default.
    Returns (height_m, levels_or_None).
    """
    def _parse_length(value: str) -> float | None:
        """Parse a length string like '15', '15 m', '50 ft' to metres."""
        v = value.strip().lower()
        try:
            if v.endswith("ft") or v.endswith("'"):
                return float(v.rstrip("ft '")) * 0.3048
            return float(v.rstrip("m "))
        except ValueError:
            return None

    for key in ("building:height", "height"):
        raw = tags.get(key)
        if raw:
            parsed = _parse_length(raw)
            if parsed and parsed > 0:
                return parsed, None

    for key in ("building:levels", "levels"):
        raw = tags.get(key)
        if raw:
            try:
                lvl = int(float(raw.split(";")[0].strip()))
                if lvl > 0:
                    return lvl * _METRES_PER_FLOOR, lvl
            except ValueError:
                pass

    return _DEFAULT_HEIGHT_M, None


def _nodes_to_coords(
    nodes: list,
    transformer: pyproj.Transformer,
    origin_x: float,
    origin_y: float,
) -> list[tuple[float, float]]:
    """Convert a list of overpy.Node objects to local (x, y) in metres."""
    coords = []
    for node in nodes:
        x, y = transformer.transform(float(node.lon), float(node.lat))
        coords.append((x - origin_x, y - origin_y))
    return coords


def _get_way_nodes(way: overpy.Way, result: overpy.Result) -> list[overpy.Node] | None:
    """
    Return a way's nodes across overpy versions.
    Newer overpy returns populated `way.nodes`; older patterns used `get_node_ids()+result.get_node`.
    """
    try:
        if getattr(way, "nodes", None):
            return list(way.nodes)
    except Exception:
        pass

    try:
        node_ids = way.get_node_ids()
        return [result.get_node(nid) for nid in node_ids]
    except Exception:
        return None


def _parse_way(
    way: overpy.Way,
    result: overpy.Result,
    transformer: pyproj.Transformer,
    origin_x: float,
    origin_y: float,
) -> BuildingFootprint | None:
    """Build a BuildingFootprint from a single OSM way."""
    nodes = _get_way_nodes(way, result)
    if not nodes:
        return None

    coords = _nodes_to_coords(nodes, transformer, origin_x, origin_y)
    # Need at least 3 unique points (4 with closing duplicate)
    unique = list(dict.fromkeys(coords))
    if len(unique) < 3:
        return None

    try:
        polygon = Polygon(coords)
        if not polygon.is_valid:
            polygon = make_valid(polygon)
        if polygon.is_empty or not polygon.is_valid:
            return None
        # make_valid may return GeometryCollection; extract largest polygon
        if polygon.geom_type != "Polygon":
            polys = [g for g in polygon.geoms if g.geom_type == "Polygon"]
            if not polys:
                return None
            polygon = max(polys, key=lambda p: p.area)
    except Exception:
        return None

    tags = way.tags or {}
    height_m, levels = _resolve_height(tags)
    return BuildingFootprint(
        osm_id=way.id,
        osm_type="way",
        polygon=polygon,
        height_m=height_m,
        building_type=tags.get("building", "yes"),
        levels=levels,
        raw_tags=dict(tags),
    )


def _assemble_ring(
    member_ways: list[overpy.Way],
    result: overpy.Result,
) -> list[overpy.Node] | None:
    """
    Assemble an ordered ring from a list of way members.
    Returns ordered list of nodes, or None if assembly fails.
    """
    if not member_ways:
        return None

    # Build segments: list of (start_node_id, end_node_id, nodes)
    segments = []
    for way in member_ways:
        nodes = _get_way_nodes(way, result)
        if not nodes:
            continue
        if len(nodes) >= 2:
            segments.append(nodes)

    if not segments:
        return None

    # Greedy chain assembly
    ring: list[overpy.Node] = list(segments[0])
    used = {0}
    for _ in range(len(segments) - 1):
        tail_id = ring[-1].id
        found = False
        for i, seg in enumerate(segments):
            if i in used:
                continue
            if seg[0].id == tail_id:
                ring.extend(seg[1:])
                used.add(i)
                found = True
                break
            elif seg[-1].id == tail_id:
                ring.extend(reversed(seg[:-1]))
                used.add(i)
                found = True
                break
        if not found:
            break

    return ring if len(ring) >= 3 else None


def _parse_relation(
    rel: overpy.Relation,
    result: overpy.Result,
    transformer: pyproj.Transformer,
    origin_x: float,
    origin_y: float,
) -> BuildingFootprint | None:
    """Build a BuildingFootprint from a multipolygon relation."""
    outer_ways = []
    inner_ways = []
    for member in rel.members:
        if not isinstance(member, overpy.RelationWay):
            continue
        try:
            way = result.get_way(member.ref)
        except Exception:
            continue
        role = (member.role or "outer").lower()
        if role == "inner":
            inner_ways.append(way)
        else:
            outer_ways.append(way)

    outer_nodes = _assemble_ring(outer_ways, result)
    if outer_nodes is None:
        return None

    outer_coords = _nodes_to_coords(outer_nodes, transformer, origin_x, origin_y)
    if len(outer_coords) < 3:
        return None

    holes = []
    inner_nodes = _assemble_ring(inner_ways, result)
    if inner_nodes:
        inner_coords = _nodes_to_coords(inner_nodes, transformer, origin_x, origin_y)
        if len(inner_coords) >= 3:
            holes.append(inner_coords)

    try:
        polygon = Polygon(outer_coords, holes)
        if not polygon.is_valid:
            polygon = make_valid(polygon)
        if polygon.is_empty or not polygon.is_valid:
            return None
        if polygon.geom_type != "Polygon":
            polys = [g for g in polygon.geoms if g.geom_type == "Polygon"]
            if not polys:
                return None
            polygon = max(polys, key=lambda p: p.area)
    except Exception:
        return None

    tags = rel.tags or {}
    height_m, levels = _resolve_height(tags)
    return BuildingFootprint(
        osm_id=rel.id,
        osm_type="relation",
        polygon=polygon,
        height_m=height_m,
        building_type=tags.get("building", "yes"),
        levels=levels,
        raw_tags=dict(tags),
    )


def _overpass_query_bbox(south: float, west: float, north: float, east: float) -> str:
    """Build the Overpass QL query string from an explicit bbox."""
    bbox = f"{south},{west},{north},{east}"
    return (
        f"[out:json][timeout:60];\n"
        f"(\n"
        f'  way["building"]({bbox});\n'
        f'  relation["building"]["type"="multipolygon"]({bbox});\n'
        f");\n"
        f"out body;\n"
        f">;\n"
        f"out skel qt;\n"
    )


def _overpass_query(lat: float, lon: float, radius_m: float) -> str:
    """Build the Overpass QL query string."""
    s, w, n, e = compute_bbox(lat, lon, radius_m)
    return _overpass_query_bbox(s, w, n, e)


def _run_overpass(query: str, max_retries: int = 3) -> overpy.Result:
    """Execute Overpass query with exponential backoff retry."""
    api = overpy.Overpass(url=_OVERPASS_URL)
    for attempt in range(max_retries):
        try:
            return api.query(query)
        except overpy.exception.OverPyException as exc:
            if attempt == max_retries - 1:
                raise OSMFetchError(
                    f"Overpass API failed after {max_retries} attempts: {exc}"
                ) from exc
            wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
            time.sleep(wait)
        except Exception as exc:
            raise OSMFetchError(f"Unexpected error querying Overpass: {exc}") from exc
    raise OSMFetchError("Overpass query failed (unreachable)")


def _parse_overpass_result(
    result: overpy.Result,
    origin_lat: float,
    origin_lon: float,
    verbose: bool = False,
) -> list[BuildingFootprint]:
    """Parse Overpass result into BuildingFootprint entries in local metres."""
    if verbose:
        print(f"  Received {len(result.ways)} ways, {len(result.relations)} relations")

    transformer = _make_transformer(origin_lat, origin_lon)
    origin_x, origin_y = transformer.transform(origin_lon, origin_lat)
    footprints: list[BuildingFootprint] = []

    for way in result.ways:
        fp = _parse_way(way, result, transformer, origin_x, origin_y)
        if fp is not None:
            footprints.append(fp)

    for rel in result.relations:
        fp = _parse_relation(rel, result, transformer, origin_x, origin_y)
        if fp is not None:
            footprints.append(fp)

    if verbose:
        print(f"  Parsed {len(footprints)} valid building footprints")

    return footprints


def fetch_buildings_bbox(
    south: float,
    west: float,
    north: float,
    east: float,
    origin_lat: float,
    origin_lon: float,
    verbose: bool = False,
) -> list[BuildingFootprint]:
    """Fetch building footprints from OSM for an explicit bounding box."""
    query = _overpass_query_bbox(south, west, north, east)
    if verbose:
        print(f"  Querying Overpass API (bbox: {south:.4f},{west:.4f} → {north:.4f},{east:.4f}) ...")

    result = _run_overpass(query)
    return _parse_overpass_result(result, origin_lat=origin_lat, origin_lon=origin_lon, verbose=verbose)


def bbox_size_m(
    south: float,
    west: float,
    north: float,
    east: float,
    origin_lat: float,
    origin_lon: float,
) -> tuple[float, float]:
    """Return bbox width/height in metres using local UTM coordinates."""
    transformer = _make_transformer(origin_lat, origin_lon)
    sw_x, sw_y = transformer.transform(west, south)
    se_x, _ = transformer.transform(east, south)
    _, nw_y = transformer.transform(west, north)
    return abs(se_x - sw_x), abs(nw_y - sw_y)


def fetch_buildings(
    lat: float,
    lon: float,
    radius_m: float,
    verbose: bool = False,
) -> list[BuildingFootprint]:
    """
    Fetch building footprints from OSM for the given area.

    Args:
        lat, lon:  City centre in WGS84 decimal degrees.
        radius_m:  Radius of the area to fetch, in metres.
        verbose:   Print progress messages.

    Returns:
        List of BuildingFootprint objects with coordinates in local metres
        (origin at city centre).

    Raises:
        OSMFetchError: on network failure or Overpass error.
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
    )




def clip_footprints_to_rect(
    footprints: list[BuildingFootprint],
    x_half_m: float,
    y_half_m: float,
) -> list[BuildingFootprint]:
    """
    Clip footprint polygons to a rectangle centred at the origin.

    Buildings that straddle the boundary are sliced exactly at the edge —
    the cut face becomes a vertical wall when extruded, giving a clean
    "knife-cut" boundary rather than a staircase of whole buildings.

    Args:
        footprints:  Footprints in local metres (origin at city centre).
        x_half_m:    Half-width of the crop rectangle in metres.
        y_half_m:    Half-height of the crop rectangle in metres.

    Returns:
        New list of BuildingFootprint with clipped polygons.
        Buildings entirely outside are dropped; buildings split into
        multiple pieces each become a separate footprint.
    """
    _MIN_AREA_M2 = 1.0  # discard slivers smaller than 1 m²
    crop_rect = shapely_box(-x_half_m, -y_half_m, x_half_m, y_half_m)
    result: list[BuildingFootprint] = []

    for fp in footprints:
        clipped = fp.polygon.intersection(crop_rect)
        if clipped.is_empty:
            continue
        geom_type = clipped.geom_type
        polys = (
            [clipped] if geom_type == "Polygon"
            else [g for g in clipped.geoms if g.geom_type == "Polygon" and not g.is_empty]
        )
        for poly in polys:
            if poly.area < _MIN_AREA_M2:
                continue
            result.append(BuildingFootprint(
                osm_id=fp.osm_id,
                osm_type=fp.osm_type,
                polygon=poly,
                height_m=fp.height_m,
                building_type=fp.building_type,
                levels=fp.levels,
                raw_tags=fp.raw_tags,
            ))

    return result


def filter_footprints_to_rect(
    footprints: list[BuildingFootprint],
    x_half_m: float,
    y_half_m: float,
) -> list[BuildingFootprint]:
    """Keep footprints whose centroid is inside a rectangle centred at origin."""
    result: list[BuildingFootprint] = []
    for fp in footprints:
        centroid = fp.polygon.centroid
        if -x_half_m <= centroid.x <= x_half_m and -y_half_m <= centroid.y <= y_half_m:
            result.append(fp)
    return result
