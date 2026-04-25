"""Reusable model-generation pipeline shared by CLI and web server."""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .exceptions import City3DError
from .exporter import export, export_cropped, export_tiled, print_cm_to_real_m
from .geocoder import geocode_city
from .model_builder import build_all_meshes
from .osm_fetcher import (
    bbox_size_m,
    clip_footprints_to_rect,
    fetch_buildings,
    fetch_buildings_bbox,
    filter_footprints_to_rect,
)
from .validator import (
    merge_reports,
    validate_footprints,
    validate_meshes,
    validate_output_files,
)


@dataclass
class GenerationResult:
    success: bool
    city: str | None
    center_lat: float
    center_lon: float
    scale: int
    mode: str
    output_dir: str
    obj_files: list[str] = field(default_factory=list)
    mtl_files: list[str] = field(default_factory=list)
    zip_path: str | None = None
    metadata_path: str | None = None
    logs_path: str | None = None
    building_count: int = 0
    bbox: tuple[float, float, float, float] | None = None
    real_size_m: tuple[float, float] | None = None
    print_size_cm: tuple[float, float] | None = None
    message: str = ""


Logger = Callable[[str], None]


def _default_logger(message: str) -> None:
    print(message)


def _make_zip(zip_path: str, files: list[str]) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            if os.path.exists(path):
                zf.write(path, arcname=os.path.basename(path))


def generate_model(
    city: str | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    scale: int = 50000,
    output: str = "./output",
    mode: str = "clip",
    crop_cm: tuple[float, float] | None = None,
    tile_cm: tuple[float, float] | None = None,
    base_mm: float = 1.0,
    min_buildings: int = 5,
    verbose: bool = False,
    radius_m: float | None = None,
    logger: Logger | None = None,
) -> GenerationResult:
    """Generate city models via shared pipeline for CLI and web."""
    log = logger or _default_logger
    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)

    logs: list[str] = []

    def _log(msg: str) -> None:
        logs.append(msg)
        log(msg)

    mode = mode.lower().strip()
    if mode not in {"none", "filter", "clip", "tile"}:
        raise ValueError(f"Unsupported mode: {mode}")

    if center_lat is None or center_lon is None:
        if not city:
            raise ValueError("city or center_lat/center_lon is required")
        _log("[1/5] Geocoding city...")
        center_lat, center_lon = geocode_city(city)
    else:
        _log("[1/5] Using provided center coordinates...")

    _log(f"      -> lat={center_lat:.6f}, lon={center_lon:.6f}")

    if bbox is not None:
        south, west, north, east = bbox
        _log("[2/5] Fetching buildings from explicit bbox...")
        footprints = fetch_buildings_bbox(
            south=south,
            west=west,
            north=north,
            east=east,
            origin_lat=center_lat,
            origin_lon=center_lon,
            verbose=verbose,
        )
        real_size = bbox_size_m(south, west, north, east, center_lat, center_lon)
    else:
        if radius_m is None:
            radius_m = round(scale * 15.24 / 200, -2)
        _log("[2/5] Fetching buildings by radius...")
        footprints = fetch_buildings(center_lat, center_lon, radius_m=radius_m, verbose=verbose)
        real_size = None

    _log(f"      -> {len(footprints)} buildings fetched")

    _log("[3/5] Validating footprint data...")
    fp_report = validate_footprints(footprints, min_buildings=min_buildings)
    if not fp_report.passed:
        raise City3DError("Footprint validation failed")

    if mode in {"clip", "filter", "tile"}:
        if bbox is not None:
            width_m, height_m = real_size
            x_half_m = width_m / 2
            y_half_m = height_m / 2
        elif crop_cm:
            x_half_m = print_cm_to_real_m(crop_cm[0], scale) / 2
            y_half_m = print_cm_to_real_m(crop_cm[1], scale) / 2
        else:
            x_half_m = y_half_m = None

        if x_half_m is not None and y_half_m is not None:
            if mode in {"clip", "tile"}:
                footprints = clip_footprints_to_rect(footprints, x_half_m, y_half_m)
            elif mode == "filter":
                footprints = filter_footprints_to_rect(footprints, x_half_m, y_half_m)
            _log(f"      -> {len(footprints)} footprints after {mode}")

    _log("[4/5] Building 3D meshes...")
    meshes = build_all_meshes(footprints, verbose=verbose)
    if not meshes:
        raise City3DError("No meshes built")
    mesh_report = validate_meshes(meshes)
    if not mesh_report.passed:
        raise City3DError("Mesh validation failed")

    _log("[5/5] Exporting files...")
    obj_files: list[str] = []
    mtl_files: list[str] = []

    if mode == "tile":
        tile_w_cm, tile_h_cm = tile_cm if tile_cm else (10.0, 15.0)
        pairs = export_tiled(
            meshes,
            output_dir=str(out_dir),
            city_name=city or "city",
            tile_w_cm=tile_w_cm,
            tile_h_cm=tile_h_cm,
            radius_m=radius_m or 0.0,
            lat=center_lat,
            lon=center_lon,
            scale=scale,
        )
        for obj_path, mtl_path in pairs:
            obj_files.append(obj_path)
            mtl_files.append(mtl_path)
        file_reports = [
            validate_output_files(obj_path, mtl_path, radius_m=radius_m or 0.0, is_tile=True, scale=scale)
            for obj_path, mtl_path in pairs
        ]
        combined = merge_reports(fp_report, mesh_report, *file_reports)
    elif mode == "clip" and (bbox is not None or crop_cm is not None):
        if bbox is not None:
            crop_cm = (
                (real_size[0] * 100 / scale),
                (real_size[1] * 100 / scale),
            )
        crop_w_cm, crop_h_cm = crop_cm
        obj_path, mtl_path = export_cropped(
            meshes,
            output_dir=str(out_dir),
            city_name=city or "city",
            crop_w_cm=crop_w_cm,
            crop_h_cm=crop_h_cm,
            base_thickness_mm=base_mm,
            radius_m=radius_m or 0.0,
            lat=center_lat,
            lon=center_lon,
            scale=scale,
        )
        obj_files.append(obj_path)
        mtl_files.append(mtl_path)
        combined = merge_reports(
            fp_report,
            mesh_report,
            validate_output_files(obj_path, mtl_path, radius_m=radius_m or 0.0, is_tile=True, scale=scale),
        )
    else:
        obj_path, mtl_path = export(
            meshes,
            output_dir=str(out_dir),
            city_name=city or "city",
            radius_m=radius_m or 0.0,
            lat=center_lat,
            lon=center_lon,
            scale=scale,
        )
        obj_files.append(obj_path)
        mtl_files.append(mtl_path)
        combined = merge_reports(
            fp_report,
            mesh_report,
            validate_output_files(obj_path, mtl_path, radius_m=radius_m or 0.0, scale=scale),
        )

    if not combined.passed:
        raise City3DError("Output validation failed")

    print_size_cm = None
    if real_size is not None:
        print_size_cm = (real_size[0] * 100 / scale, real_size[1] * 100 / scale)

    metadata = {
        "city": city,
        "center": {"lat": center_lat, "lon": center_lon},
        "bbox": None if bbox is None else {
            "south": bbox[0],
            "west": bbox[1],
            "north": bbox[2],
            "east": bbox[3],
        },
        "scale": scale,
        "mode": mode,
        "print_size_cm": print_size_cm,
        "building_count": len(footprints),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
    }

    metadata_path = out_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    logs_path = out_dir / "logs.txt"
    logs_path.write_text("\n".join(logs), encoding="utf-8")

    zip_path = out_dir / "model.zip"
    _make_zip(str(zip_path), obj_files + mtl_files + [str(metadata_path), str(logs_path)])

    return GenerationResult(
        success=True,
        city=city,
        center_lat=center_lat,
        center_lon=center_lon,
        scale=scale,
        mode=mode,
        output_dir=str(out_dir),
        obj_files=obj_files,
        mtl_files=mtl_files,
        zip_path=str(zip_path),
        metadata_path=str(metadata_path),
        logs_path=str(logs_path),
        building_count=len(footprints),
        bbox=bbox,
        real_size_m=real_size,
        print_size_cm=print_size_cm,
        message="ok",
    )
