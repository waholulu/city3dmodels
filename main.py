#!/usr/bin/env python3
"""
city3dmodels — Download and generate 1:10000 3D city models from OpenStreetMap.

Usage:
    python main.py "New York" --radius 1000 --output ./output --verbose
    python main.py "Paris, France" --radius 2000
    python main.py "Tokyo" --radius 1500 --output /tmp/tokyo_model
"""

import argparse
import sys

from src.exceptions import City3DError, ValidationError
from src.geocoder import geocode_city
from src.osm_fetcher import fetch_buildings
from src.model_builder import build_all_meshes
from src.exporter import export
from src.validator import validate_footprints, validate_meshes, validate_output_files, merge_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="city3dmodels",
        description=(
            "Download 1:10000 3D building models for a city's central area "
            "from OpenStreetMap and export as OBJ+MTL files.\n\n"
            "Example: python main.py \"New York\" --radius 1000 --verbose"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "city",
        help='City name to model, e.g. "New York" or "Berlin, Germany"',
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=2000.0,
        metavar="METRES",
        help="Radius of the area to model around the city centre (default: 2000 m)",
    )
    parser.add_argument(
        "--output",
        default="./output",
        metavar="DIR",
        help="Output directory for OBJ and MTL files (default: ./output)",
    )
    parser.add_argument(
        "--min-buildings",
        type=int,
        default=5,
        dest="min_buildings",
        metavar="N",
        help="Minimum number of buildings required to proceed (default: 5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed progress information",
    )
    return parser.parse_args()


def run_pipeline(
    city: str,
    radius: float,
    output: str,
    min_buildings: int,
    verbose: bool,
) -> int:
    """
    Run the full pipeline: geocode → fetch → validate → build → export → validate.
    Returns 0 on success, 1 on failure.
    """
    print(f"City 3D Model Generator")
    print(f"  City:   {city}")
    print(f"  Radius: {radius:.0f} m")
    print(f"  Output: {output}")
    print()

    # ── Step 1: Geocode ──────────────────────────────────────────────────────
    print("[1/5] Geocoding city...")
    try:
        lat, lon = geocode_city(city)
    except City3DError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"      → lat={lat:.6f}, lon={lon:.6f}")

    # ── Step 2: Fetch buildings ──────────────────────────────────────────────
    print("[2/5] Fetching buildings from OpenStreetMap...")
    try:
        footprints = fetch_buildings(lat, lon, radius, verbose=verbose)
    except City3DError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"      → {len(footprints)} buildings fetched")

    # ── Step 3: Validate footprints ──────────────────────────────────────────
    print("[3/5] Validating footprint data...")
    fp_report = validate_footprints(footprints, min_buildings=min_buildings)
    if verbose and fp_report.warnings:
        for w in fp_report.warnings:
            print(f"      [WARN] {w}")
    if not fp_report.passed:
        for e in fp_report.errors:
            print(f"      [ERROR] {e}", file=sys.stderr)
        print("ERROR: Footprint validation failed. Aborting.", file=sys.stderr)
        return 1

    # ── Step 4: Build 3D meshes ──────────────────────────────────────────────
    print("[4/5] Building 3D meshes...")
    meshes = build_all_meshes(footprints, verbose=verbose)
    print(f"      → {len(meshes)} meshes built")

    if not meshes:
        print("ERROR: No 3D meshes could be built. Aborting.", file=sys.stderr)
        return 1

    mesh_report = validate_meshes(meshes)
    if verbose and mesh_report.warnings:
        for w in mesh_report.warnings:
            print(f"      [WARN] {w}")
    if not mesh_report.passed:
        for e in mesh_report.errors:
            print(f"      [ERROR] {e}", file=sys.stderr)
        print("ERROR: Mesh validation failed. Aborting.", file=sys.stderr)
        return 1

    # ── Step 5: Export OBJ + MTL ─────────────────────────────────────────────
    print("[5/5] Exporting OBJ + MTL...")
    try:
        obj_path, mtl_path = export(
            meshes,
            output_dir=output,
            city_name=city,
            radius_m=radius,
            lat=lat,
            lon=lon,
        )
    except Exception as exc:
        print(f"ERROR: Export failed: {exc}", file=sys.stderr)
        return 1
    print(f"      → {obj_path}")
    print(f"      → {mtl_path}")

    # ── Final validation: check output files ─────────────────────────────────
    file_report = validate_output_files(obj_path, mtl_path, radius_m=radius)
    combined = merge_reports(fp_report, mesh_report, file_report)
    combined.print_summary(verbose=verbose)

    if not combined.passed:
        print("ERROR: Output validation failed.", file=sys.stderr)
        return 1

    print(f"Done. Model saved to: {output}")
    return 0


def main() -> None:
    args = parse_args()
    sys.exit(
        run_pipeline(
            city=args.city,
            radius=args.radius,
            output=args.output,
            min_buildings=args.min_buildings,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    main()
