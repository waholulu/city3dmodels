# city3dmodels

从 OpenStreetMap 抓取建筑并导出 OBJ/MTL 模型，默认比例尺 **1:50000**。

## 安装

```bash
pip install -r requirements.txt
```

## CLI 用法（兼容原有流程）

```bash
python main.py "New York" --radius 1000 --output ./output --verbose
```

### 主要参数

- `--scale`：比例尺分母，默认 `50000`（即 1:50000，可手动修改）。
- `--radius`：抓取半径（米）。为空时会按 4×6 英寸长边 + 当前 scale 自动换算。
- `--crop W_CM H_CM`：按打印尺寸（厘米）做中心矩形裁切并导出。
- `--tile W_CM H_CM`：按所选比例尺下的打印尺寸切片导出多 OBJ/MTL。
- `--base-mm`：底板厚度（毫米）。当 `0` 时不生成底板；大于 `0` 时在模型底部增加底板。

## 打印尺寸与真实世界换算

核心换算关系：

- `real_m = print_cm * scale / 100`
- `print_cm = real_m * 100 / scale`

示例：

- 4×6 inch（10.16 × 15.24 cm）
- 在 1:50000 时，约对应真实世界 `5.08 km × 7.62 km`

这意味着 UI/CLI 应始终把 `crop` 视为“最终成品尺寸”，而把 `radius` 视为“抓取缓冲范围”。

## OBJ 单位与比例

导出的 OBJ 坐标单位为 **英寸（inch）**，文件头也会写出单位说明（`1 OBJ unit = 1 inch`）。

导入 Blender/3D 软件时应按 inch 解释。

## Streamlit UI（推荐）

```bash
streamlit run app.py
```

功能（v1）：

- 城市输入与中心点选择
- 标准照片尺寸（含自定义）+ 横竖方向
- 比例尺 / 底板厚度 / fetch buffer
- 地图预览（红色最终 crop，灰色 fetch buffer）
- 一键调用 pipeline 生成 OBJ/MTL
- 输出日志展示与 OBJ/MTL/ZIP 下载按钮

## FastAPI + Leaflet UI（已有）

```bash
python server.py
# 打开 http://127.0.0.1:8000
```

## 测试

```bash
pytest -q
```
