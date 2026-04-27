from src.print_layout import compute_print_layout, resolve_print_size_cm


def test_compute_print_layout_4x6_landscape_50000():
    w_cm, h_cm = resolve_print_size_cm("4 × 6 inch", "Landscape")
    layout = compute_print_layout(w_cm, h_cm, 50000, base_thickness_mm=1.0, fetch_buffer_pct=0.10)

    assert round(layout.print_width_cm, 2) == 15.24
    assert round(layout.print_height_cm, 2) == 10.16
    assert round(layout.crop_width_m) == 7620
    assert round(layout.crop_height_m) == 5080
    assert round(layout.fetch_radius_m) == 4191


def test_resolve_portrait_orientation_swaps_dimensions():
    w_cm, h_cm = resolve_print_size_cm("4 × 6 inch", "Portrait")
    assert w_cm == 10.16
    assert h_cm == 15.24
