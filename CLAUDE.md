# CLAUDE.md — city3dmodels

## 项目概述

从 OpenStreetMap 自动下载城市建筑轮廓，拉伸为三维网格，导出 OBJ + MTL 格式的 1:10000 比例模型。

## 安装依赖

```bash
pip install -r requirements.txt
```

依赖项：`overpy` `shapely` `pyproj` `numpy` `geopy` `requests`

## 运行

```bash
# 基本用法
python main.py "New York" --radius 1000 --output ./output --verbose

# 常用选项
python main.py <城市名> [--radius 米] [--output 目录] [--min-buildings N] [-v]
```

## 代码结构

```
main.py              # CLI 入口，run_pipeline() 串联所有阶段
src/
  exceptions.py      # 自定义异常：City3DError 及其子类
  geocoder.py        # geocode_city() → (lat, lon)，Nominatim
  osm_fetcher.py     # fetch_buildings() → list[BuildingFootprint]
  model_builder.py   # build_all_meshes() → list[BuildingMesh]
  exporter.py        # export() → (obj_path, mtl_path)
  validator.py       # 三阶段校验，返回 ValidationReport
```

## 数据流

```
geocode_city(city)
  → fetch_buildings(lat, lon, radius)   # Overpass API
  → validate_footprints(footprints)     # Stage A：轮廓校验
  → build_all_meshes(footprints)        # 拉伸建模
  → validate_meshes(meshes)             # Stage B：网格校验
  → export(meshes, output_dir)          # 写 OBJ + MTL
  → validate_output_files(obj, mtl)     # Stage C：文件校验
```

## 关键设计决策

| 问题 | 决策 |
|------|------|
| 坐标投影 | 按经度自动选择 UTM 带（EPSG:326xx/327xx），精度优于 0.04% |
| 高度来源 | `building:height` > `height` > `levels×3m` > 默认 9m |
| 屋顶三角化 | Shapely Delaunay，支持凹多边形；失败时退回 n 边形面 |
| 庭院（内环） | 反向绕序拉伸内环墙面，不生成屋顶面 |
| OBJ 单位 | 1 单位 = 1 米；1:10000 仅为文件头注释，不缩放坐标 |
| 网络重试 | Overpass 指数退避 3 次（5s / 10s / 20s） |

## 修改指南

### 新增数据源
在 `src/osm_fetcher.py` 中修改 `_overpass_query()` 的 Overpass QL 语句，或新增独立的 fetcher 模块并在 `main.py` 中切换。

### 新增输出格式（如 glTF）
在 `src/` 下新建 `exporter_gltf.py`，接收 `list[BuildingMesh]`，在 `main.py` 中增加 `--format` 参数按需调用。

### 修改材质
编辑 `src/exporter.py` 中的 `_MTL_CONTENT` 字符串，调整 `Kd`（漫反射色）即可。

### 调整校验阈值
`src/validator.py` 顶部的常量：
- `_MIN_HEIGHT_M` / `_MAX_HEIGHT_M`：高度合法范围
- `validate_footprints()` 的 `min_buildings` 参数：最少建筑数

## 注意事项

- **Nominatim 限速**：代码已在请求前 `sleep(1)`，不要并发调用 `geocode_city()`
- **Overpass 超时**：大半径（>3km）可能触发 60s 超时，可在 `_overpass_query()` 中调高 `timeout`
- **多边形修复**：`make_valid()` 会修改几何形状，修复后仍需检查 `is_valid`
- **OBJ 索引**：全局顶点表，导出时 `global_vertex_offset` 必须跨建筑累加，勿重置
- **数据许可**：输出模型须署名 © OpenStreetMap contributors（ODbL 1.0）
