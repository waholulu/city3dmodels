"""Validate building footprints, meshes, and output OBJ files."""

import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .osm_fetcher import BuildingFootprint
from .model_builder import BuildingMesh
from .exceptions import ValidationError


@dataclass
class ValidationReport:
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def print_summary(self, verbose: bool = False) -> None:
        status = "PASSED" if self.passed else "FAILED"
        print(f"\n{'='*50}")
        print(f"Validation: {status}")
        if self.stats:
            for k, v in self.stats.items():
                print(f"  {k}: {v}")
        if self.errors:
            print("Errors:")
            for e in self.errors:
                print(f"  [ERROR] {e}")
        if verbose and self.warnings:
            print("Warnings:")
            for w in self.warnings:
                print(f"  [WARN]  {w}")
        print(f"{'='*50}\n")


def merge_reports(*reports: ValidationReport) -> ValidationReport:
    """Merge multiple ValidationReport objects; passed=True only if all pass."""
    combined = ValidationReport()
    for r in reports:
        combined.warnings.extend(r.warnings)
        combined.errors.extend(r.errors)
        combined.stats.update(r.stats)
        if not r.passed:
            combined.passed = False
    return combined


# ---------------------------------------------------------------------------
# Stage A: Footprint validation
# ---------------------------------------------------------------------------

_MIN_HEIGHT_M = 1.5
_MAX_HEIGHT_M = 800.0


def validate_footprints(
    footprints: list[BuildingFootprint],
    min_buildings: int = 5,
) -> ValidationReport:
    """
    Validate OSM building footprints.

    Checks:
    - Minimum building count
    - All heights in plausible range
    - Polygon geometry validity
    - Vertex count per polygon
    - Coordinate plausibility (within reasonable bounds of origin)
    """
    report = ValidationReport()

    # --- Count check ---
    count = len(footprints)
    report.stats["building_count"] = count
    if count == 0:
        report.error("No buildings found in the specified area.")
        return report
    if count < min_buildings:
        report.error(
            f"Only {count} buildings found (minimum required: {min_buildings}). "
            "The city centre may have sparse OSM data or the radius is too small."
        )

    height_invalid = 0
    height_default = 0
    geom_invalid = 0
    coord_oob = 0
    heights = []

    for fp in footprints:
        # --- Height range check ---
        if not (_MIN_HEIGHT_M <= fp.height_m <= _MAX_HEIGHT_M):
            height_invalid += 1
            report.warn(
                f"Building {fp.osm_id}: height {fp.height_m:.1f} m out of range "
                f"[{_MIN_HEIGHT_M}, {_MAX_HEIGHT_M}]; clamped."
            )
            # Clamp in place
            fp.height_m = max(_MIN_HEIGHT_M, min(_MAX_HEIGHT_M, fp.height_m))
        heights.append(fp.height_m)

        if fp.raw_tags.get("building:height") is None and fp.raw_tags.get("height") is None:
            height_default += 1

        # --- Polygon validity check ---
        if not fp.polygon.is_valid:
            geom_invalid += 1
            report.warn(f"Building {fp.osm_id}: invalid polygon geometry (attempted auto-fix).")

        # --- Vertex count ---
        ext_coords = list(fp.polygon.exterior.coords)
        if len(ext_coords) < 4:  # shapely includes closing coord
            report.warn(f"Building {fp.osm_id}: exterior ring has only {len(ext_coords)} coords.")

        # --- Coordinate plausibility (should be within 50 km of origin) ---
        bounds = fp.polygon.bounds  # (minx, miny, maxx, maxy)
        max_coord = max(abs(c) for c in bounds)
        if max_coord > 50_000:
            coord_oob += 1
            report.warn(
                f"Building {fp.osm_id}: coordinates extend {max_coord:.0f} m from origin "
                "(expected < 50 km)."
            )

    # --- Summary stats ---
    if heights:
        report.stats["height_min_m"] = round(min(heights), 1)
        report.stats["height_max_m"] = round(max(heights), 1)
        report.stats["height_mean_m"] = round(sum(heights) / len(heights), 1)
        report.stats["default_height_pct"] = round(100 * height_default / count, 1)

    if height_invalid:
        report.warn(f"{height_invalid} buildings had heights clamped to [{_MIN_HEIGHT_M}, {_MAX_HEIGHT_M}] m.")
    if geom_invalid:
        report.warn(f"{geom_invalid} buildings had invalid polygon geometry.")
    if coord_oob:
        report.warn(f"{coord_oob} buildings had coordinates far from origin.")

    return report


# ---------------------------------------------------------------------------
# Stage B: Mesh validation
# ---------------------------------------------------------------------------

def validate_meshes(
    meshes: list[BuildingMesh],
) -> ValidationReport:
    """
    Validate 3D building meshes.

    Checks:
    - No empty meshes
    - Face indices within vertex bounds
    - No degenerate faces (< 3 indices)
    - No NaN or Inf coordinates
    """
    report = ValidationReport()
    report.stats["mesh_count"] = len(meshes)

    empty_count = 0
    bad_index_count = 0
    degenerate_face_count = 0
    nan_inf_count = 0

    for mesh in meshes:
        if not mesh.vertices or not mesh.faces:
            empty_count += 1
            report.warn(f"Building {mesh.osm_id}: empty mesh (no vertices or faces).")
            continue

        n_verts = len(mesh.vertices)

        # Check for NaN/Inf
        arr = np.array(mesh.vertices, dtype=float)
        if not np.all(np.isfinite(arr)):
            nan_inf_count += 1
            report.error(f"Building {mesh.osm_id}: NaN or Inf in vertex coordinates.")

        for indices, _ in mesh.faces:
            if len(indices) < 3:
                degenerate_face_count += 1
                continue
            for idx in indices:
                if idx < 1 or idx > n_verts:
                    bad_index_count += 1
                    report.error(
                        f"Building {mesh.osm_id}: face index {idx} out of range [1, {n_verts}]."
                    )

    if empty_count:
        report.warn(f"{empty_count} empty meshes skipped.")
    if degenerate_face_count:
        report.warn(f"{degenerate_face_count} degenerate faces (< 3 indices) found.")
    if bad_index_count:
        report.error(f"{bad_index_count} face index out-of-bounds errors.")
    if nan_inf_count:
        report.error(f"{nan_inf_count} meshes with NaN/Inf vertex coordinates.")

    return report


# ---------------------------------------------------------------------------
# Stage C: OBJ file validation
# ---------------------------------------------------------------------------

def _parse_obj_basic(obj_path: str) -> dict:
    """
    Minimal OBJ parser that counts vertices/faces, computes bounding box,
    and collects used material names.
    """
    vertex_count = 0
    face_count = 0
    used_materials = set()
    coords_x, coords_y, coords_z = [], [], []
    mtllib = None

    with open(obj_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("v "):
                parts = line.split()
                if len(parts) == 4:
                    try:
                        coords_x.append(float(parts[1]))
                        coords_y.append(float(parts[2]))
                        coords_z.append(float(parts[3]))
                        vertex_count += 1
                    except ValueError:
                        pass
            elif line.startswith("f "):
                face_count += 1
            elif line.startswith("usemtl "):
                used_materials.add(line.split(None, 1)[1].strip())
            elif line.startswith("mtllib "):
                mtllib = line.split(None, 1)[1].strip()

    bbox = None
    if coords_x:
        bbox = (
            min(coords_x), max(coords_x),
            min(coords_y), max(coords_y),
            min(coords_z), max(coords_z),
        )

    return {
        "vertex_count": vertex_count,
        "face_count": face_count,
        "used_materials": used_materials,
        "bbox": bbox,
        "mtllib": mtllib,
    }


def _parse_mtl_materials(mtl_path: str) -> set[str]:
    """Return set of material names defined in the MTL file."""
    materials = set()
    with open(mtl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("newmtl "):
                materials.add(line.split(None, 1)[1].strip())
    return materials


_OBJ_MIN_SIZE_BYTES = 10 * 1024        # 10 KB — below this the model is likely broken
_OBJ_MAX_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB — above this the file is impractically large
_MTL_MAX_SIZE_BYTES = 1 * 1024 * 1024   # 1 MB  — MTL should be tiny

_PRINT_SCALE = 50_000  # default; overridable via scale= on validate_output_files()
_PRINT_MIN_EXTENT_CM = 1.0   # print footprint smaller than 1 cm is too tiny to be useful
_PRINT_MAX_EXTENT_CM = 50.0  # print footprint larger than 50 cm exceeds a typical desk model
_PRINT_MAX_HEIGHT_CM = 10.0  # tallest building print height


def _human_size(n: int) -> str:
    """Format byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def validate_output_files(
    obj_path: str,
    mtl_path: str,
    radius_m: float,
    is_tile: bool = False,
    scale: int = _PRINT_SCALE,
) -> ValidationReport:
    """
    Validate the exported OBJ and MTL files.

    Checks:
    - Files exist and are non-empty
    - File sizes within plausible range (10 KB – 50 MB for OBJ; skipped for tiles)
    - OBJ references the correct MTL filename
    - OBJ re-parses correctly (vertex and face counts > 0)
    - Bounding box of model is within expected radius
    - Print-size plausibility checks (skipped for individual tiles)
    - All usemtl names exist in the MTL file
    """
    report = ValidationReport()

    # --- File existence & size plausibility ---
    for path, label in [(obj_path, "OBJ"), (mtl_path, "MTL")]:
        if not os.path.isfile(path):
            report.error(f"{label} file not found: {path}")
            return report
        size = os.path.getsize(path)
        if size == 0:
            report.error(f"{label} file is empty: {path}")
            return report
        report.stats[f"{label.lower()}_size_bytes"] = size
        report.stats[f"{label.lower()}_size_human"] = _human_size(size)

    obj_size = report.stats["obj_size_bytes"]
    mtl_size = report.stats["mtl_size_bytes"]

    if not is_tile and obj_size < _OBJ_MIN_SIZE_BYTES:
        report.error(
            f"OBJ file is suspiciously small ({_human_size(obj_size)}). "
            f"Expected at least {_human_size(_OBJ_MIN_SIZE_BYTES)}; "
            "the model likely contains too few buildings or is corrupt."
        )
    if obj_size > _OBJ_MAX_SIZE_BYTES:
        report.error(
            f"OBJ file is too large ({_human_size(obj_size)}). "
            f"Maximum allowed is {_human_size(_OBJ_MAX_SIZE_BYTES)}. "
            "Consider reducing --radius to cover a smaller area."
        )
    if mtl_size > _MTL_MAX_SIZE_BYTES:
        report.warn(
            f"MTL file is unexpectedly large ({_human_size(mtl_size)})."
        )

    # --- Parse OBJ ---
    try:
        obj_data = _parse_obj_basic(obj_path)
    except Exception as exc:
        report.error(f"Failed to parse OBJ file: {exc}")
        return report

    report.stats["obj_vertex_count"] = obj_data["vertex_count"]
    report.stats["obj_face_count"] = obj_data["face_count"]

    if obj_data["vertex_count"] == 0:
        report.error("OBJ file contains no vertices.")
    if obj_data["face_count"] == 0:
        report.error("OBJ file contains no faces.")

    # --- MTL reference ---
    expected_mtl_name = os.path.basename(mtl_path)
    if obj_data["mtllib"] != expected_mtl_name:
        report.error(
            f"OBJ mtllib reference '{obj_data['mtllib']}' does not match "
            f"actual MTL filename '{expected_mtl_name}'."
        )

    # --- Bounding box & print-size plausibility ---
    # OBJ coordinates are in inches (1 OBJ unit = 1 inch).
    _coord_scale = 1_000 / (scale * 25.4)  # real metres → OBJ inches
    _obj_unit_cm = 25.4 / 10               # 1 OBJ inch = 2.54 cm
    if obj_data["bbox"]:
        xmin, xmax, ymin, ymax, zmin, zmax = obj_data["bbox"]

        max_extent_obj = max(abs(xmin), abs(xmax), abs(ymin), abs(ymax))  # OBJ inches
        allowed_obj = radius_m * _coord_scale * 1.1                        # OBJ inches
        if max_extent_obj > allowed_obj:
            report.warn(
                f"Model bounding box extends {max_extent_obj * 25.4:.0f} mm from origin "
                f"(expected < {allowed_obj * 25.4:.0f} mm for radius {radius_m:.0f} m)."
            )
        if zmin < 0:
            report.warn(f"Model has vertices below z=0 (zmin={zmin * 25.4:.2f} mm).")

        report.stats["model_extent_mm"] = round(max_extent_obj * 25.4, 1)
        report.stats["model_height_max_mm"] = round(zmax * 25.4, 1)

        # OBJ coords are in inches — convert to cm for display
        print_w_cm = (xmax - xmin) * _obj_unit_cm
        print_d_cm = (ymax - ymin) * _obj_unit_cm
        print_h_cm = (zmax - max(zmin, 0.0)) * _obj_unit_cm
        print_max_side = max(print_w_cm, print_d_cm)

        report.stats["print_scale"] = f"1:{scale}"
        report.stats["print_width_cm"] = round(print_w_cm, 1)
        report.stats["print_depth_cm"] = round(print_d_cm, 1)
        report.stats["print_height_cm"] = round(print_h_cm, 1)
        report.stats["print_summary"] = (
            f"{print_w_cm:.1f} x {print_d_cm:.1f} x {print_h_cm:.1f} cm @ 1:{scale}"
        )

        if not is_tile and print_max_side < _PRINT_MIN_EXTENT_CM:
            report.error(
                f"Scaled model footprint is too small for printing "
                f"({print_w_cm:.1f} x {print_d_cm:.1f} cm at 1:{scale}). "
                f"Minimum side should be >= {_PRINT_MIN_EXTENT_CM} cm. "
                "Try increasing --radius."
            )
        if not is_tile and print_max_side > _PRINT_MAX_EXTENT_CM:
            report.warn(
                f"Scaled model footprint is very large "
                f"({print_w_cm:.1f} x {print_d_cm:.1f} cm at 1:{scale}). "
                f"Recommended max side is {_PRINT_MAX_EXTENT_CM} cm. "
                "Consider reducing --radius for a more manageable print."
            )
        if print_h_cm > _PRINT_MAX_HEIGHT_CM:
            report.warn(
                f"Tallest building prints at {print_h_cm:.1f} cm "
                f"(> {_PRINT_MAX_HEIGHT_CM} cm recommended max). "
                "This may look disproportionate in a desk-sized model."
            )

    # --- Material consistency ---
    try:
        defined_materials = _parse_mtl_materials(mtl_path)
    except Exception as exc:
        report.error(f"Failed to parse MTL file: {exc}")
        return report

    missing_mats = obj_data["used_materials"] - defined_materials
    if missing_mats:
        report.error(
            f"OBJ references undefined materials: {', '.join(sorted(missing_mats))}"
        )

    return report
