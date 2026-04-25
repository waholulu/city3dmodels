# city3dmodels

从 OpenStreetMap 抓取建筑并导出 OBJ/MTL 模型，默认比例尺 **1:50000**。

## 安装

```bash
pip install -r requirements.txt
```

## CLI 用法（保持兼容）

```bash
python main.py "New York" --radius 1000 --output ./output --verbose
```

### 主要参数

- `--scale`：比例尺分母，默认 `50000`（即 1:50000）。
- `--radius`：抓取半径（米）。为空时自动按 4×6 英寸长边换算。
- `--crop W_CM H_CM`：以中心矩形进行 knife-cut 裁切并导出带底板模型。
- `--tile W_CM H_CM`：按打印尺寸切片导出多 OBJ/MTL。
- `--base-mm`：`--crop` 模式下底板厚度（毫米）。

> 术语说明：
> - `none`：不裁切（仅按抓取结果导出）
> - `filter`：只保留重心在选区内的建筑
> - `clip`：对建筑面与选区做 intersection（推荐默认）
> - `tile`：先 clip，再按 tile 尺寸导出多个文件

## OBJ 单位与比例

导出的 OBJ 坐标单位为 **英寸（inch）**，并在文件头写入比例信息。

转换关系：

- `real_m = print_cm * scale / 100`
- `print_cm = real_m * 100 / scale`

## 本地 Web UI

新增 FastAPI + Leaflet 本地界面：

```bash
python server.py
# 打开 http://127.0.0.1:8000
```

功能（v0.1）：

- 城市搜索与定位
- 地图矩形选区（bbox）
- scale/mode/crop/tile/base 参数
- 异步任务（job_id + polling）
- 下载 ZIP（包含 OBJ/MTL/metadata/logs）

每次生成输出到：

```text
output/jobs/<timestamp_slug>/
  *.obj
  *.mtl
  metadata.json
  logs.txt
  model.zip
```

## 测试

```bash
pytest -q
```
