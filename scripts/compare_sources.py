"""Compare OSM and Overture building coverage for the same area.

Usage:
    python scripts/compare_sources.py "Berlin" --radius 1000

Prints a side-by-side table of building count, total footprint area,
mean / max height, and percentage of buildings without an explicit height tag.
Use this to decide whether to switch a particular city from OSM to Overture
(or vice versa).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from src.geocoder import geocode_city
from src.osm_fetcher import fetch_buildings as fetch_osm
from src.overture_fetcher import fetch_buildings as fetch_overture


@dataclass
class Stats:
    source: str
    count: int
    total_area_m2: float
    mean_height_m: float
    max_height_m: float
    default_height_pct: float
    elapsed_s: float


def _summarize(source: str, footprints, elapsed: float) -> Stats:
    if not footprints:
        return Stats(source, 0, 0.0, 0.0, 0.0, 0.0, elapsed)
    heights = [fp.height_m for fp in footprints]
    n_default = sum(
        1 for fp in footprints
        if fp.raw_tags.get("building:height") is None and fp.raw_tags.get("height") is None
    )
    return Stats(
        source=source,
        count=len(footprints),
        total_area_m2=sum(fp.polygon.area for fp in footprints),
        mean_height_m=sum(heights) / len(heights),
        max_height_m=max(heights),
        default_height_pct=100 * n_default / len(footprints),
        elapsed_s=elapsed,
    )


def _print_table(rows: list[Stats]) -> None:
    fmt = "{:<12} {:>10} {:>14} {:>14} {:>12} {:>18} {:>12}"
    print(fmt.format("source", "count", "total_area_m2", "mean_height_m",
                     "max_height_m", "default_height_pct", "elapsed_s"))
    print("-" * 96)
    for r in rows:
        print(fmt.format(
            r.source,
            r.count,
            f"{r.total_area_m2:,.0f}",
            f"{r.mean_height_m:.1f}",
            f"{r.max_height_m:.1f}",
            f"{r.default_height_pct:.1f}",
            f"{r.elapsed_s:.1f}",
        ))


def main() -> int:
    p = argparse.ArgumentParser(description="Compare OSM vs Overture building coverage")
    p.add_argument("city", help='City name, e.g. "Berlin"')
    p.add_argument("--radius", type=float, default=1000.0, help="Radius in metres (default 1000)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    print(f"Geocoding {args.city!r} ...")
    lat, lon = geocode_city(args.city)
    print(f"  -> lat={lat:.4f}, lon={lon:.4f}, radius={args.radius:.0f} m")

    rows: list[Stats] = []

    for label, fn in [("osm", fetch_osm), ("overture", fetch_overture)]:
        print(f"\nFetching from {label} ...")
        t0 = time.time()
        try:
            fps = fn(lat, lon, radius_m=args.radius, verbose=args.verbose)
        except Exception as exc:
            print(f"  {label} failed: {exc}")
            continue
        rows.append(_summarize(label, fps, time.time() - t0))

    print()
    _print_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
