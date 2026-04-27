#!/usr/bin/env python3
"""city3dmodels CLI wrapper."""

import argparse
import sys

from src.exceptions import City3DError
from src.pipeline import generate_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="city3dmodels",
        description=(
            "Download 3D building models for a city's central area "
            "from OpenStreetMap and export as OBJ+MTL files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("city", help='City name to model, e.g. "New York" or "Berlin, Germany"')
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
    parser.add_argument("--output", default="./output", metavar="DIR", help="Output directory")
    parser.add_argument("--min-buildings", type=int, default=5, metavar="N", dest="min_buildings")
    parser.add_argument("--crop", nargs=2, type=float, metavar=("W_CM", "H_CM"), default=None)
    parser.add_argument(
        "--tile",
        nargs=2,
        type=float,
        metavar=("W_CM", "H_CM"),
        default=None,
        help="Tile size in cm at the selected print scale (W_CM H_CM)",
    )
    parser.add_argument("--base-mm", type=float, default=1.0, dest="base_mm", metavar="MM")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    radius = args.radius if args.radius is not None else round(args.scale * 15.24 / 200, -2)

    mode = "none"
    if args.tile:
        mode = "tile"
    elif args.crop:
        mode = "clip"

    try:
        generate_model(
            city=args.city,
            scale=args.scale,
            output=args.output,
            mode=mode,
            crop_cm=tuple(args.crop) if args.crop else None,
            tile_cm=tuple(args.tile) if args.tile else None,
            base_mm=args.base_mm,
            min_buildings=args.min_buildings,
            verbose=args.verbose,
            radius_m=radius,
        )
    except City3DError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
