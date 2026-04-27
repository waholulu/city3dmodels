"""Print layout helpers shared by UI and CLI-facing integrations."""

from __future__ import annotations

from dataclasses import dataclass


PHOTO_SIZE_PRESETS_CM: dict[str, tuple[float, float]] = {
    "4 × 6 inch": (10.16, 15.24),
    "5 × 7 inch": (12.70, 17.78),
    "8 × 10 inch": (20.32, 25.40),
    "A5": (14.80, 21.00),
    "A4": (21.00, 29.70),
}


@dataclass
class PrintLayout:
    print_width_cm: float
    print_height_cm: float
    scale: int
    crop_width_m: float
    crop_height_m: float
    fetch_radius_m: float
    base_thickness_mm: float



def resolve_print_size_cm(
    photo_size: str,
    orientation: str,
    custom_width_cm: float | None = None,
    custom_height_cm: float | None = None,
) -> tuple[float, float]:
    """Resolve print dimensions (cm) from preset/custom + orientation."""
    if photo_size == "Custom":
        if custom_width_cm is None or custom_height_cm is None:
            raise ValueError("Custom size requires width and height")
        width_cm, height_cm = custom_width_cm, custom_height_cm
    elif photo_size in PHOTO_SIZE_PRESETS_CM:
        width_cm, height_cm = PHOTO_SIZE_PRESETS_CM[photo_size]
    else:
        raise ValueError(f"Unknown photo size: {photo_size}")

    orientation_key = orientation.lower().strip()
    if orientation_key == "landscape":
        return max(width_cm, height_cm), min(width_cm, height_cm)
    if orientation_key == "portrait":
        return min(width_cm, height_cm), max(width_cm, height_cm)
    raise ValueError(f"Unknown orientation: {orientation}")



def compute_print_layout(
    print_width_cm: float,
    print_height_cm: float,
    scale: int,
    base_thickness_mm: float = 1.0,
    fetch_buffer_pct: float = 0.10,
) -> PrintLayout:
    crop_width_m = print_width_cm * scale / 100
    crop_height_m = print_height_cm * scale / 100
    fetch_radius_m = max(crop_width_m, crop_height_m) / 2 * (1 + fetch_buffer_pct)
    return PrintLayout(
        print_width_cm=print_width_cm,
        print_height_cm=print_height_cm,
        scale=scale,
        crop_width_m=crop_width_m,
        crop_height_m=crop_height_m,
        fetch_radius_m=fetch_radius_m,
        base_thickness_mm=base_thickness_mm,
    )
