from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.geocoder import geocode_city
from src.pipeline import run_pipeline
from src.print_layout import PHOTO_SIZE_PRESETS_CM, compute_print_layout, resolve_print_size_cm

PRESET_SCALES = [10000, 25000, 50000, 100000]


@st.cache_data(show_spinner=False)
def cached_geocode_city(city: str) -> tuple[float, float]:
    return geocode_city(city)


def meters_to_latlon_offsets(lat: float, width_m: float, height_m: float) -> tuple[float, float]:
    lat_offset = height_m / 2 / 111_320.0
    lon_offset = width_m / 2 / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return lat_offset, lon_offset


def rectangle_bounds(lat: float, lon: float, width_m: float, height_m: float) -> tuple[list[float], list[float]]:
    lat_offset, lon_offset = meters_to_latlon_offsets(lat, width_m, height_m)
    sw = [lat - lat_offset, lon - lon_offset]
    ne = [lat + lat_offset, lon + lon_offset]
    return sw, ne


def try_read_bytes(path: str | None) -> bytes | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    return file_path.read_bytes()


st.set_page_config(page_title="City 3D Print Preview", layout="wide")

st.title("City 3D Print Preview")
st.caption(
    "Select a standard photo size, preview the real-world crop area, and export a print-ready 3D city model."
)
st.caption("选择标准照片尺寸，预览真实截取范围，并导出适合实际打印的城市三维模型。")

left, center, right = st.columns([1.1, 1.7, 1.1])

# Persistent map-click center (None = use geocoded city center).
if "map_center_lat" not in st.session_state:
    st.session_state.map_center_lat = None
if "map_center_lon" not in st.session_state:
    st.session_state.map_center_lon = None
if "last_city" not in st.session_state:
    st.session_state.last_city = ""
if "custom_lat" not in st.session_state:
    st.session_state.custom_lat = 40.7128
if "custom_lon" not in st.session_state:
    st.session_state.custom_lon = -74.0060

# Apply any pending map click before widgets are instantiated. Streamlit forbids
# writing to a widget-keyed session state slot after the widget renders, so the
# click handler stages the new coords here and reruns; we flush them here on the
# next run, before custom_lat/custom_lon widgets are created.
_pending_click = st.session_state.pop("_pending_click", None)
if _pending_click is not None:
    _p_lat, _p_lon = _pending_click
    st.session_state.custom_lat = _p_lat
    st.session_state.custom_lon = _p_lon
    st.session_state.map_center_lat = _p_lat
    st.session_state.map_center_lon = _p_lon

# Defaults used by both sidebar logic and generation logic.
fetch_buffer_pct = 0.10
min_buildings = 5
output_folder = "./output/ui"
verbose = False
override_radius = False
custom_radius = 4000.0

with left:
    st.subheader("City settings")
    city = st.text_input("City name", value="New York, NY")

    # Reset map-click override whenever the city name changes.
    if city != st.session_state.last_city:
        st.session_state.map_center_lat = None
        st.session_state.map_center_lon = None
        st.session_state.last_city = city

    use_custom_center = st.checkbox("Use custom center", value=False)

    if use_custom_center:
        lat = st.number_input("Latitude", key="custom_lat", format="%.6f")
        lon = st.number_input("Longitude", key="custom_lon", format="%.6f")
    else:
        try:
            geocoded_lat, geocoded_lon = cached_geocode_city(city)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Geocode failed, fallback to default center: {exc}")
            geocoded_lat, geocoded_lon = 40.7128, -74.0060
        lat = st.session_state.map_center_lat if st.session_state.map_center_lat is not None else geocoded_lat
        lon = st.session_state.map_center_lon if st.session_state.map_center_lon is not None else geocoded_lon
        _lbl, _btn = st.columns([3, 1])
        _lbl.caption(f"Center: {lat:.6f}, {lon:.6f}")
        if st.session_state.map_center_lat is not None:
            if _btn.button("Reset", help="Reset to geocoded city center"):
                st.session_state.map_center_lat = None
                st.session_state.map_center_lon = None
                st.rerun()

    st.subheader("Building source")
    source = st.radio(
        "Data source",
        options=["overture", "osm"],
        index=0,
        horizontal=True,
        help=(
            "Overture (default): monthly GeoParquet release on S3, fuses OSM "
            "+ ML footprints (~24× more buildings globally; better height "
            "coverage). Requires duckdb. "
            "OSM: live Overpass API query — no extra deps."
        ),
    )

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
    scale = (
        int(st.number_input("Custom scale", min_value=1000, value=50000, step=1000))
        if scale_choice == "Custom"
        else int(scale_choice)
    )

    st.subheader("Base plate")
    base_mm = st.slider("Base plate thickness (mm)", min_value=0.0, max_value=5.0, step=0.1, value=1.0)
    st.caption("Base thickness is added below model; building heights are unchanged.")

    with st.expander("Advanced settings", expanded=False):
        fetch_buffer_pct = st.slider("Fetch buffer (%)", min_value=0, max_value=50, value=10, step=1) / 100.0
        min_buildings = st.number_input("Minimum buildings", min_value=1, value=5, step=1)
        output_folder = st.text_input("Output folder", value="./output/ui")
        verbose = st.checkbox("Verbose logs", value=False)
        override_radius = st.checkbox("Override fetch radius", value=False)
        custom_radius = st.number_input(
            "Fetch radius (m)",
            min_value=100.0,
            value=4000.0,
            step=100.0,
            disabled=not override_radius,
        )

layout = compute_print_layout(
    print_width_cm=print_w_cm,
    print_height_cm=print_h_cm,
    scale=scale,
    base_thickness_mm=base_mm,
    fetch_buffer_pct=fetch_buffer_pct,
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

    folium.Rectangle(
        bounds=[crop_sw, crop_ne],
        color="red",
        fill=False,
        weight=2,
        tooltip="Final crop",
    ).add_to(m)
    folium.Rectangle(
        bounds=[fetch_sw, fetch_ne],
        color="gray",
        fill=False,
        weight=2,
        dash_array="5, 5",
        tooltip="Fetch buffer",
    ).add_to(m)
    folium.Marker(
        [lat, lon],
        tooltip="City center",
        icon=folium.Icon(color="blue", icon="info-sign"),
    ).add_to(m)
    m.fit_bounds([fetch_sw, fetch_ne])
    map_data = st_folium(m, width=780, height=480, key="city_map")
    st.caption("Click anywhere on the map to move the crop center. | 点击地图可移动截取中心点。")
    st.caption("Red rectangle = final model area.  Gray dashed = data-fetch buffer.")
    st.caption("红色框 = 最终打印范围。灰色虚线框 = 数据抓取范围。")

    # Reposition crop center on map click. Stage the new coords as a pending
    # update; the top-of-script handler flushes them before widgets render,
    # which is the only safe time to write widget-keyed session state.
    if map_data and map_data.get("last_clicked"):
        clicked_lat = map_data["last_clicked"]["lat"]
        clicked_lon = map_data["last_clicked"]["lng"]
        if (clicked_lat, clicked_lon) != (lat, lon):
            st.session_state._pending_click = (clicked_lat, clicked_lon)
            st.rerun()

with right:
    st.subheader("Output")
    st.write("Ready to generate")

    if st.button("Generate model", type="primary"):
        logs: list[str] = []

        def logger(message: str) -> None:
            logs.append(message)

        target = Path(output_folder) / datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        target.mkdir(parents=True, exist_ok=True)

        with st.status("Generating model...", expanded=True) as status:
            try:
                result = run_pipeline(
                    city=city,
                    center_lat=lat,
                    center_lon=lon,
                    scale=layout.scale,
                    output=str(target),
                    mode="clip",
                    crop_cm=(layout.print_width_cm, layout.print_height_cm),
                    base_mm=layout.base_thickness_mm,
                    min_buildings=int(min_buildings),
                    verbose=bool(verbose),
                    radius_m=float(custom_radius if override_radius else layout.fetch_radius_m),
                    source=source,
                    logger=logger,
                )
                status.update(label="Generated successfully", state="complete")
            except Exception as exc:  # noqa: BLE001
                status.update(label="Generation failed", state="error")
                st.error(f"Generation failed: {exc}")
                result = None

        if logs:
            st.text_area("Generation logs", value="\n".join(logs), height=180)

        if result is not None:
            st.success("Generated successfully")
            st.write(f"Building count: {result.building_count}")
            st.write(f"Output folder: `{result.output_dir}`")

            first_obj = result.obj_files[0] if result.obj_files else None
            first_mtl = result.mtl_files[0] if result.mtl_files else None
            obj_bytes = try_read_bytes(first_obj)
            mtl_bytes = try_read_bytes(first_mtl)
            zip_bytes = try_read_bytes(result.zip_path)

            if first_obj:
                st.write(f"OBJ file: `{first_obj}`")
            if first_mtl:
                st.write(f"MTL file: `{first_mtl}`")
            if result.zip_path:
                st.write(f"ZIP file: `{result.zip_path}`")

            if obj_bytes and first_obj:
                st.download_button("Download OBJ", data=obj_bytes, file_name=Path(first_obj).name)
            if mtl_bytes and first_mtl:
                st.download_button("Download MTL", data=mtl_bytes, file_name=Path(first_mtl).name)
            if zip_bytes and result.zip_path:
                st.download_button("Download ZIP", data=zip_bytes, file_name=Path(result.zip_path).name)
