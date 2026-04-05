"""Build 3D meshes by extruding building footprints."""

from dataclasses import dataclass, field

import numpy as np
from shapely.ops import triangulate
from shapely.geometry import MultiPoint, Polygon

from .osm_fetcher import BuildingFootprint


@dataclass
class BuildingMesh:
    osm_id: int
    building_type: str
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    # Each face: (list_of_1based_indices, material_name)
    faces: list[tuple[list[int], str]] = field(default_factory=list)


def _ring_coords(polygon_ring) -> list[tuple[float, float]]:
    """Extract (x, y) coords from a shapely ring, dropping the closing duplicate."""
    coords = list(polygon_ring.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [(float(x), float(y)) for x, y in coords]


def _triangulate_polygon(polygon: Polygon) -> list[list[tuple[float, float]]]:
    """
    Triangulate a Shapely Polygon using Delaunay triangulation.
    Returns a list of triangles, each as 3 (x, y) tuples.
    Only keeps triangles whose centroid is inside the polygon.
    """
    pts = MultiPoint(list(polygon.exterior.coords))
    tris = triangulate(pts)
    result = []
    for tri in tris:
        if polygon.contains(tri.centroid):
            coords = list(tri.exterior.coords)[:3]
            result.append([(float(x), float(y)) for x, y in coords])
    return result


def _find_nearest_index(
    target: tuple[float, float],
    ring: list[tuple[float, float]],
) -> int:
    """Return 0-based index of the ring vertex nearest to target (by L2 distance)."""
    tx, ty = target
    best_i, best_d2 = 0, float("inf")
    for i, (x, y) in enumerate(ring):
        d2 = (x - tx) ** 2 + (y - ty) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_i = i
    return best_i


def _extrude_ring(
    ring: list[tuple[float, float]],
    height: float,
    base_offset: int,
    reverse_winding: bool = False,
) -> tuple[list[tuple[float, float, float]], list[tuple[list[int], str]]]:
    """
    Extrude a 2D ring to a 3D wall mesh.

    Args:
        ring:            List of (x, y) coords (no closing duplicate).
        height:          Building height in metres.
        base_offset:     1-based global vertex offset applied to all face indices.
        reverse_winding: If True, reverse face winding (for courtyard inner rings).

    Returns:
        (vertices, faces) where vertices are (x, y, z) and faces are
        (index_list, material).
    """
    n = len(ring)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[list[int], str]] = []

    # Bottom ring: indices base_offset + 1 .. base_offset + n
    for x, y in ring:
        vertices.append((x, y, 0.0))
    # Top ring: indices base_offset + n + 1 .. base_offset + 2n
    for x, y in ring:
        vertices.append((x, y, float(height)))

    # Wall quads → 2 triangles each
    for i in range(n):
        i_next = (i + 1) % n
        b_i   = base_offset + i + 1
        b_i1  = base_offset + i_next + 1
        t_i   = base_offset + n + i + 1
        t_i1  = base_offset + n + i_next + 1

        if reverse_winding:
            tri_a = [b_i, t_i1, b_i1]
            tri_b = [b_i, t_i,  t_i1]
        else:
            tri_a = [b_i, b_i1, t_i1]
            tri_b = [b_i, t_i1, t_i]

        faces.append((tri_a, "mat_wall"))
        faces.append((tri_b, "mat_wall"))

    return vertices, faces


def build_mesh(footprint: BuildingFootprint) -> BuildingMesh:
    """
    Extrude a BuildingFootprint polygon to a 3D BuildingMesh.
    Handles concave polygons (Delaunay roof triangulation) and
    courtyards (inner ring wall extrusion with reversed winding).
    """
    mesh = BuildingMesh(osm_id=footprint.osm_id, building_type=footprint.building_type)
    base_offset = 0  # local offset within this mesh (0-based for accumulation)

    polygon = footprint.polygon
    height = footprint.height_m

    # --- Outer ring ---
    outer_ring = _ring_coords(polygon.exterior)
    if len(outer_ring) < 3:
        raise ValueError(f"Building {footprint.osm_id}: outer ring has fewer than 3 vertices")

    wall_verts, wall_faces = _extrude_ring(outer_ring, height, base_offset)
    mesh.vertices.extend(wall_verts)
    mesh.faces.extend(wall_faces)
    n_outer = len(outer_ring)
    base_offset += 2 * n_outer

    # --- Roof triangulation ---
    try:
        triangles = _triangulate_polygon(polygon)
    except Exception:
        # Fallback: simple n-gon roof face using top ring indices
        top_start = n_outer + 1  # 1-based index of first top vertex (offset 0)
        roof_face = list(range(top_start, top_start + n_outer))
        mesh.faces.append((roof_face, "mat_roof"))
        triangles = []

    if triangles:
        # Map triangle vertices to top-ring indices (offset 0 top ring starts at n_outer+1)
        top_ring = [(x, y) for x, y in outer_ring]
        for tri in triangles:
            indices = []
            for pt in tri:
                nearest = _find_nearest_index(pt, top_ring)
                # top ring: 1-based at (n_outer + nearest + 1) within local base=0
                indices.append(n_outer + nearest + 1)
            if len(set(indices)) == 3:  # skip degenerate triangles
                mesh.faces.append((indices, "mat_roof"))

    # --- Inner rings (courtyards) ---
    for interior in polygon.interiors:
        inner_ring = _ring_coords(interior)
        # Shapely holes are CW; reverse to get CCW for consistent orientation
        inner_ring = list(reversed(inner_ring))
        if len(inner_ring) < 3:
            continue
        i_wall_verts, i_wall_faces = _extrude_ring(
            inner_ring, height, base_offset, reverse_winding=True
        )
        mesh.vertices.extend(i_wall_verts)
        mesh.faces.extend(i_wall_faces)
        base_offset += 2 * len(inner_ring)

    return mesh


def build_all_meshes(
    footprints: list[BuildingFootprint],
    verbose: bool = False,
) -> list[BuildingMesh]:
    """
    Build 3D meshes for all footprints.
    Skips degenerate footprints with a warning rather than aborting.
    """
    meshes = []
    skipped = 0
    for fp in footprints:
        try:
            mesh = build_mesh(fp)
            if mesh.vertices and mesh.faces:
                meshes.append(mesh)
            else:
                skipped += 1
        except Exception as exc:
            if verbose:
                print(f"  Warning: skipping building {fp.osm_id}: {exc}")
            skipped += 1

    if verbose and skipped:
        print(f"  Skipped {skipped} degenerate buildings")

    return meshes
