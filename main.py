#!/usr/bin/env python3
"""
city3dmodels — Download and generate 1:10000 3D city models from OpenStreetMap.

Usage:
    python main.py "New York" --radius 1000 --output ./output --verbose
    python main.py "Paris, France" --radius 2000
    python main.py "Tokyo" --radius 1500 --output /tmp/tokyo_model
"""

import argparse
import os
import sys

from src.exceptions import City3DError, ValidationError
from src.geocoder import geocode_city
from src.osm_fetcher import fetch_buildings, clip_footprints_to_rect
from src.model_builder import build_all_meshes
from src.exporter import export, export_tiled, export_cropped, print_cm_to_real_m
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
        "--scale",
        type=int,
        default=50_000,
        metavar="N",
        help="Print scale denominator, e.g. 50000 for 1:50000 (default: 50000)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=None,
        metavar="METRES",
        help=(
            "Radius of the area to model in metres. "
            "Defaults to half the long side of a 4×6\" photo at the chosen scale "
            "(= scale × 15.24 / 200, e.g. 3810 m at 1:50000)."
        ),
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
        "--crop",
        nargs=2,
        type=float,
        metavar=("W_CM", "H_CM"),
        default=None,
        help=(
            "Crop to a single W_CM × H_CM cm rectangle centred at the city origin "
            "and add a 1 mm base plate (use --base-mm to change thickness). "
            "Example: --crop 10 15  →  10 × 15 cm print (= 1000 × 1500 m real)."
        ),
    )
    parser.add_argument(
        "--base-mm",
        type=float,
        default=1.0,
        dest="base_mm",
        metavar="MM",
        help="Base plate thickness in printed mm (only used with --crop, default: 1.0).",
    )
    parser.add_argument(
        "--tile",
        nargs=2,
        type=float,
        metavar=("W_CM", "H_CM"),
        default=None,
        help=(
            "Split the model into tiles of W_CM × H_CM centimetres (at 1:10000 print scale). "
            "Each tile is exported as a separate OBJ file. "
            "Example: --tile 10 15  →  10 cm × 15 cm tiles (= 1000 m × 1500 m real)."
        ),
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
    scale: int = 50_000,
    crop: tuple[float, float] | None = None,
    base_mm: float = 1.0,
    tile: tuple[float, float] | None = None,
) -> int:
    """
    Run the full pipeline: geocode → fetch → validate → build → export → validate.
    Returns 0 on success, 1 on failure.
    """
    print(f"City 3D Model Generator")
    print(f"  City:   {city}")
    print(f"  Scale:  1:{scale}")
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
    if crop:
        crop_w_cm, crop_h_cm = crop
        x_half_m = print_cm_to_real_m(crop_w_cm, scale) / 2
        y_half_m = print_cm_to_real_m(crop_h_cm, scale) / 2
        footprints = clip_footprints_to_rect(footprints, x_half_m, y_half_m)
        if verbose:
            print(f"      → {len(footprints)} footprints after knife-cut clip")

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
    if crop:
        crop_w_cm, crop_h_cm = crop
        print(
            f"[5/5] Exporting cropped OBJ + MTL "
            f"({crop_w_cm:.0f} × {crop_h_cm:.0f} cm, base plate {base_mm:.1f} mm)..."
        )
        try:
            obj_path, mtl_path = export_cropped(
                meshes,
                output_dir=output,
                city_name=city,
                crop_w_cm=crop_w_cm,
                crop_h_cm=crop_h_cm,
                base_thickness_mm=base_mm,
                radius_m=radius,
                lat=lat,
                lon=lon,
                scale=scale,
            )
        except Exception as exc:
            print(f"ERROR: Cropped export failed: {exc}", file=sys.stderr)
            return 1
        print(f"      → {obj_path}")
        print(f"      → {mtl_path}")

        file_report = validate_output_files(obj_path, mtl_path, radius_m=radius, is_tile=True, scale=scale)
        combined = merge_reports(fp_report, mesh_report, file_report)
    elif tile:
        tile_w_cm, tile_h_cm = tile
        print(
            f"[5/5] Exporting tiled OBJ + MTL "
            f"({tile_w_cm:.0f} cm × {tile_h_cm:.0f} cm per tile)..."
        )
        try:
            tile_pairs = export_tiled(
                meshes,
                output_dir=output,
                city_name=city,
                tile_w_cm=tile_w_cm,
                tile_h_cm=tile_h_cm,
                radius_m=radius,
                lat=lat,
                lon=lon,
                scale=scale,
            )
        except Exception as exc:
            print(f"ERROR: Tiled export failed: {exc}", file=sys.stderr)
            return 1
        print(f"      → {len(tile_pairs)} tile(s) written to {output}/")
        for obj_path, mtl_path in tile_pairs:
            print(f"         {os.path.basename(obj_path)}")

        file_reports = []
        for obj_path, mtl_path in tile_pairs:
            file_reports.append(validate_output_files(obj_path, mtl_path, radius_m=radius, is_tile=True, scale=scale))
        combined = merge_reports(fp_report, mesh_report, *file_reports)
    else:
        print("[5/5] Exporting OBJ + MTL...")
        try:
            obj_path, mtl_path = export(
                meshes,
                output_dir=output,
                city_name=city,
                radius_m=radius,
                lat=lat,
                lon=lon,
                scale=scale,
            )
        except Exception as exc:
            print(f"ERROR: Export failed: {exc}", file=sys.stderr)
            return 1
        print(f"      → {obj_path}")
        print(f"      → {mtl_path}")

        file_report = validate_output_files(obj_path, mtl_path, radius_m=radius, scale=scale)
        combined = merge_reports(fp_report, mesh_report, file_report)

    # ── Final validation ──────────────────────────────────────────────────────
    combined.print_summary(verbose=verbose)

    if not combined.passed:
        print("ERROR: Output validation failed.", file=sys.stderr)
        return 1

    print(f"Done. Model saved to: {output}")
    return 0


def main() -> None:
    args = parse_args()
    # Auto-compute radius: half the long side of a 4×6 photo at the chosen scale.
    # 15.24 cm × scale / 100 m/cm / 2 = scale × 0.0762 m
    radius = args.radius if args.radius is not None else round(args.scale * 15.24 / 200, -2)
    sys.exit(
        run_pipeline(
            city=args.city,
            radius=radius,
            output=args.output,
            min_buildings=args.min_buildings,
            verbose=args.verbose,
            scale=args.scale,
            crop=tuple(args.crop) if args.crop else None,
            base_mm=args.base_mm,
            tile=tuple(args.tile) if args.tile else None,
        )
    )


if __name__ == "__main__":
    main()
