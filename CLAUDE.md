# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Downloads building footprints from OpenStreetMap, extrudes them into 3D meshes, and exports OBJ + MTL files at 1:10000 scale (1 OBJ unit = 1 mm, so models import at the correct print size when the unit is set to mm).

## Setup

```bash
pip install -r requirements.txt
# Dependencies: overpy shapely pyproj numpy geopy requests
```

## Running

```bash
# Basic
python main.py "New York" --radius 1000 --output ./output --verbose

# Crop to a single printable rectangle with a base plate
python main.py "New York" --radius 1000 --crop 10 15 --base-mm 1.0 --output ./output

# Split into tiles (10 cm × 15 cm each at 1:10000)
python main.py "New York" --radius 1000 --tile 10 15 --output ./output

# Full option reference
python main.py <city> [--radius M] [--output DIR] [--min-buildings N]
               [--crop W_CM H_CM] [--base-mm MM]
               [--tile W_CM H_CM] [-v]
```

## Architecture

```
main.py              # CLI entry point; run_pipeline() chains all stages
src/
  exceptions.py      # City3DError base + subclasses (GeocoderError, OSMFetchError, ValidationError)
  geocoder.py        # geocode_city() → (lat, lon) via Nominatim
  osm_fetcher.py     # fetch_buildings() → list[BuildingFootprint] (Overpass API)
  overture_fetcher.py# fetch_buildings() → list[BuildingFootprint] (Overture GeoParquet on S3)
  pipeline.py        # generate_model(); _select_fetcher() dispatches on source="osm"|"overture"
  model_builder.py   # build_all_meshes() → list[BuildingMesh]
  exporter.py        # export() / export_tiled() / export_cropped() → OBJ + MTL
  validator.py       # Three-stage validation returning ValidationReport
scripts/
  compare_sources.py # Side-by-side OSM vs Overture coverage report for a city
```

Default building source is **Overture** (monthly refresh, fuses OSM + ML
footprints, ~24× more buildings globally; better height coverage).
Requires `duckdb`. Pass `--source osm` to fall back to Overpass. The
Overture release is set by `_DEFAULT_RELEASE` in
`src/overture_fetcher.py` and can be overridden with the `OVERTURE_RELEASE`
env var.

## Data flow

```
geocode_city(city)
  → fetch_buildings(lat, lon, radius)   # Overpass API, exponential-backoff retry
  → validate_footprints(footprints)     # Stage A: polygon geometry + height range
  → build_all_meshes(footprints)        # Shapely Delaunay triangulation + wall extrusion
  → validate_meshes(meshes)             # Stage B: NaN/Inf, face index bounds
  → export*(meshes, output_dir)         # Write OBJ + MTL
  → validate_output_files(obj, mtl)     # Stage C: file size, bbox, material consistency
```

## Key design decisions

| Concern | Decision |
|---------|----------|
| Projection | Auto-select UTM zone from longitude (EPSG:326xx/327xx); accuracy < 0.04% |
| Height source | `building:height` → `height` → `levels×3 m` → default 9 m |
| Roof triangulation | Shapely Delaunay; falls back to n-gon face if triangulation fails |
| Courtyards | Inner rings extruded with reversed winding; no roof face generated |
| OBJ scale | `_PRINT_SCALE = 50_000`; `coord_scale = 1000 / _PRINT_SCALE = 0.02` (m → OBJ **mm** at 1:50000); most slicers and CAD apps import OBJ as mm by default, so the model lands at the correct print size with no unit override |
| Network retry | Overpass: 3 attempts, 5 s / 10 s / 20 s backoff |
| Face indices | `BuildingMesh.faces` stores **1-based local** indices; `global_vertex_offset` is accumulated in `_write_obj()` and must never be reset between buildings |

## Making changes

### Add a new export format (e.g., glTF)
Create `src/exporter_gltf.py` accepting `list[BuildingMesh]`; add `--format` to `main.py`.

### Add a new building data source
Add a new module under `src/` exposing `fetch_buildings()` and
`fetch_buildings_bbox()` with the same signatures as `osm_fetcher`/`overture_fetcher`,
returning `list[BuildingFootprint]`. Then extend `_select_fetcher()` in
`src/pipeline.py` and the `--source` choices in `main.py`.

### Change material colours
Edit `_MTL_CONTENT` in `src/exporter.py`; adjust `Kd` (diffuse RGB) values.

### Tune validation thresholds
Constants at the top of `src/validator.py`:
- `_MIN_HEIGHT_M` / `_MAX_HEIGHT_M` — valid building height range
- `_OBJ_MIN_SIZE_BYTES` / `_OBJ_MAX_SIZE_BYTES` — OBJ file size limits (default 10 KB – 50 MB)
- `_MTL_MAX_SIZE_BYTES` — MTL size cap (default 1 MB)
- `_PRINT_MIN_EXTENT_CM` / `_PRINT_MAX_EXTENT_CM` — footprint side length at print scale (default 5–50 cm)
- `_PRINT_MAX_HEIGHT_CM` — tallest building at print scale (default 10 cm)
- `validate_footprints()` `min_buildings` parameter
- `_obj_unit_cm = 0.1` — conversion factor OBJ mm → cm used in print-size stats

## Gotchas

- **Nominatim rate limit**: `sleep(1)` is called before each geocode request; never call `geocode_city()` concurrently.
- **Overpass timeout**: radii > 3 km may hit the 60 s server limit; increase `timeout` in `_overpass_query()`.
- **`make_valid()` side-effects**: can return a `GeometryCollection`; always check `geom_type == "Polygon"` after repair and extract the largest polygon.
- **Global vertex offset**: `global_vertex_offset` in `_write_obj()` must accumulate across all buildings; resetting it corrupts every subsequent face.
- **No test suite**: there are currently no automated tests. Manual validation is done by running the pipeline and inspecting `ValidationReport` output.
- **Attribution**: output models must credit © OpenStreetMap contributors (ODbL 1.0).
