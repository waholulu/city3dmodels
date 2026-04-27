from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.geocoder import geocode_city
from src.pipeline import generate_model
from src.print_layout import PHOTO_SIZE_PRESETS_CM, compute_print_layout, resolve_print_size_cm


PRESET_SCALES = [10000, 25000, 50000, 100000]


def meters_to_latlon_offsets(lat: float, width_m: float, height_m: float) -> tuple[float, float]:
    lat_offset = height_m / 2 / 111_320.0
    lon_offset = width_m / 2 / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return lat_offset, lon_offset


def rectangle_bounds(lat: float, lon: float, width_m: float, height_m: float) -> tuple[list[float], list[float]]:
    lat_offset, lon_offset = meters_to_latlon_offsets(lat, width_m, height_m)
    sw = [lat - lat_offset, lon - lon_offset]
    ne = [lat + lat_offset, lon + lon_offset]
    return sw, ne


st.set_page_config(page_title="City 3D Print Preview", layout="wide")

st.title("City 3D Print Preview")
st.caption(
    "Select a standard photo size, preview the real-world crop area, and export a print-ready 3D city model."
)
st.caption("选择标准照片尺寸，预览真实截取范围，并导出适合实际打印的城市三维模型。")

left, center, right = st.columns([1.1, 1.7, 1.1])

with left:
    st.subheader("City settings")
    city = st.text_input("City name", value="New York, NY")
    use_custom_center = st.checkbox("Use custom center", value=False)
    if use_custom_center:
        lat = st.number_input("Latitude", value=40.7128, format="%.6f")
        lon = st.number_input("Longitude", value=-74.0060, format="%.6f")
    else:
        lat, lon = geocode_city(city)
        st.caption(f"Resolved center: {lat:.6f}, {lon:.6f}")

    st.subheader("Print size")
    photo_size = st.selectbox("Photo size", [*PHOTO_SIZE_PRESETS_CM.keys(), "Custom"], index=0)
    orientation = st.radio("Orientation", ["Portrait", "Landscape"], horizontal=True, index=1)

    custom_w = custom_h = None
    if photo_size == "Custom":
        custom_w = st.number_input("Custom width cm", min_value=1.0, value=15.24, step=0.1)
        custom_h = st.number_input("Custom height cm", min_value=1.0, value=10.16, step=0.1)

    print_w_cm, print_h_cm = resolve_print_size_cm(photo_size, orientation, custom_w, custom_h)

    st.subheader("Scale")
    scale_choice = st.selectbox("Print scale", [*PRESET_SCALES, "Custom"], index=2)
    scale = int(st.number_input("Custom scale", min_value=1000, value=50000, step=1000)) if scale_choice == "Custom" else int(scale_choice)

    st.subheader("Base plate")
    base_mm = st.slider("Base plate thickness (mm)", min_value=0.0, max_value=5.0, step=0.1, value=1.0)
    st.caption("Base thickness is added below model; building heights are unchanged.")

    with st.expander("Advanced settings", expanded=False):
        fetch_buffer_pct = st.slider("Fetch buffer (%)", min_value=0, max_value=50, value=10, step=1) / 100.0
        min_buildings = st.number_input("Minimum buildings", min_value=1, value=5, step=1)
        output_folder = st.text_input("Output folder", value="./output/ui")
        verbose = st.checkbox("Verbose logs", value=False)
        override_radius = st.checkbox("Override fetch radius", value=False)
        custom_radius = st.number_input("Fetch radius (m)", min_value=100.0, value=4000.0, step=100.0, disabled=not override_radius)

layout = compute_print_layout(
    print_width_cm=print_w_cm,
    print_height_cm=print_h_cm,
    scale=scale,
    base_thickness_mm=base_mm,
    fetch_buffer_pct=fetch_buffer_pct if 'fetch_buffer_pct' in locals() else 0.10,
)

with center:
    st.subheader("Preview")
    c1, c2 = st.columns(2)
    c1.metric("Final print size", f"{layout.print_width_cm:.2f} cm × {layout.print_height_cm:.2f} cm")
    c2.metric("Real-world crop", f"{layout.crop_width_m/1000:.2f} km × {layout.crop_height_m/1000:.2f} km")
    c1.metric("Print scale", f"1 cm = {layout.scale/100:.0f} m")
    c2.metric("Estimated fetch radius", f"{layout.fetch_radius_m/1000:.2f} km")
    st.metric("Base thickness", f"{layout.base_thickness_mm:.1f} mm")

    m = folium.Map(location=[lat, lon], zoom_start=13, control_scale=True)
    crop_sw, crop_ne = rectangle_bounds(lat, lon, layout.crop_width_m, layout.crop_height_m)
    fetch_size = layout.fetch_radius_m * 2
    fetch_sw, fetch_ne = rectangle_bounds(lat, lon, fetch_size, fetch_size)

    folium.Rectangle(bounds=[crop_sw, crop_ne], color="red", fill=False, weight=2, tooltip="Final crop").add_to(m)
    folium.Rectangle(bounds=[fetch_sw, fetch_ne], color="gray", fill=False, weight=2, dash_array="5, 5", tooltip="Fetch buffer").add_to(m)
    folium.Marker([lat, lon], tooltip="City center", icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)
    m.fit_bounds([fetch_sw, fetch_ne])
    st_folium(m, width=780, height=480)
    st.caption("The red rectangle is the final printed model area. The gray rectangle is the larger data-fetch area.")

with right:
    st.subheader("Output")
    st.write("Ready to generate")
    if st.button("Generate model", type="primary"):
        target = Path(output_folder if 'output_folder' in locals() else './output/ui') / datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        target.mkdir(parents=True, exist_ok=True)
        with st.status("Generating model...", expanded=True) as status:
            status.write("Geocoding city")
            status.write("Fetching buildings")
            status.write("Clipping footprints")
            status.write("Building meshes")
            status.write("Exporting OBJ and MTL")
            result = generate_model(
                city=city,
                center_lat=lat if use_custom_center else None,
                center_lon=lon if use_custom_center else None,
                scale=layout.scale,
                output=str(target),
                mode="clip",
                crop_cm=(layout.print_width_cm, layout.print_height_cm),
                base_mm=layout.base_thickness_mm,
                min_buildings=int(min_buildings if 'min_buildings' in locals() else 5),
                verbose=bool(verbose if 'verbose' in locals() else False),
                radius_m=float(custom_radius if ('override_radius' in locals() and override_radius) else layout.fetch_radius_m),
            )
            status.update(label="Generated successfully", state="complete")

        st.success("Generated successfully")
        st.write(f"Building count: {result.building_count}")
        for p in result.obj_files:
            st.write(f"OBJ file: `{p}`")
        for p in result.mtl_files:
            st.write(f"MTL file: `{p}`")
        if result.zip_path:
            st.write(f"ZIP: `{result.zip_path}`")
