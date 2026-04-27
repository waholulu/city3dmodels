# City 3D Models UI Design Work Plan

## 1. 背景

`city3dmodels` 当前主要是 CLI 工具，已经支持 `--scale`、`--crop`、`--tile`、`--base-mm`。第一版 UI 目标是让用户从“打印成品尺寸”出发配置模型，而不是直接组合底层参数。

## 2. 产品目标

1. 明确最终打印尺寸。
2. 明确打印尺寸对应的真实世界范围。
3. 在地图上预览并调整截取范围。

## 3. 推荐技术路线

- Streamlit
- Folium
- streamlit-folium

新增文件：

- `app.py`
- `src/print_layout.py`
- `docs/ui-design-plan.md`

## 4. 核心流程（v1）

1. 输入城市。
2. 选择标准照片尺寸。
3. 选择横向/竖向。
4. 选择打印比例尺。
5. 调整底板厚度。
6. 查看地图截取范围。
7. 生成并导出 OBJ/MTL。

## 5. 核心计算逻辑

- `crop` 决定最终打印成品范围。
- `radius` 仅用于抓取 OSM 数据。
- `fetch_radius_m = max(crop_width_m, crop_height_m) / 2 * (1 + fetch_buffer_pct)`。

## 6. 与 pipeline 关系

UI 调用现有 pipeline：

- 使用 `scale` + `crop_cm` 控制最终成品尺寸。
- 使用 `radius_m` 控制抓取范围。
- 使用 `base_mm` 控制底板厚度。

## 7. 第一版验收标准

- 可通过 UI 完整生成 OBJ/MTL。
- 选择不同照片尺寸/比例尺/方向时，地图框大小实时变化。
- README 与 UI 在比例尺、OBJ 单位、参数含义上保持一致。
