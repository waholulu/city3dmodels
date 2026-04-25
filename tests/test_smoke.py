from pathlib import Path

from shapely.geometry import Polygon

from src.exporter import export_tiled, print_cm_to_real_m
from src.model_builder import BuildingMesh
from src.osm_fetcher import BuildingFootprint, clip_footprints_to_rect, compute_bbox


def test_print_cm_to_real_m():
    assert print_cm_to_real_m(10, 50000) == 5000


def test_compute_bbox_ordering():
    south, west, north, east = compute_bbox(40.7128, -74.0060, 1000)
    assert south < north
    assert west < east


def test_clip_output_non_empty():
    fp = BuildingFootprint(
        osm_id=1,
        osm_type="way",
        polygon=Polygon([(-5, -5), (15, -5), (15, 15), (-5, 15), (-5, -5)]),
        height_m=10.0,
        building_type="yes",
        levels=None,
        raw_tags={},
    )
    clipped = clip_footprints_to_rect([fp], 10, 10)
    assert len(clipped) == 1
    assert not clipped[0].polygon.is_empty


def test_export_tiled_creates_output_directory(tmp_path: Path):
    output_dir = tmp_path / "nested" / "tiles"
    mesh = BuildingMesh(
        osm_id=1,
        building_type="yes",
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0)],
        faces=[([1, 2, 3], "mat_roof")],
    )
    pairs = export_tiled([mesh], output_dir=str(output_dir), city_name="Test", tile_w_cm=10, tile_h_cm=10)
    assert output_dir.exists()
    assert len(pairs) == 1
    assert Path(pairs[0][0]).exists()
    assert Path(pairs[0][1]).exists()
