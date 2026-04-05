# city3dmodels

从 OpenStreetMap 自动下载指定城市中心区的建筑数据，生成 1:10000 比例的三维模型，输出为 OBJ + MTL 文件。

## 功能特点

- 支持全球任意城市，输入城市名即可自动定位
- 数据来源：OpenStreetMap（免费、开放）
- 建筑高度从 OSM 标签读取，缺失时自动估算
- 纯几何模型（墙面 + 屋顶 + 庭院），无贴图依赖
- 内置三阶段数据校验，确保输出质量
- 网络请求失败自动重试（指数退避）

---

## 安装

**Python 3.11+ 必须**

```bash
git clone https://github.com/waholulu/city3dmodels.git
cd city3dmodels
pip install -r requirements.txt
```

---

## 快速开始

```bash
# 下载纽约市中心 1km 范围内的 3D 建筑模型
python main.py "New York" --radius 1000 --output ./output --verbose
```

运行完成后，`./output/` 目录下会生成：

```
output/
├── new_york.obj   # 3D 模型主文件
└── new_york.mtl   # 材质定义文件
```

---

## 用法

```
python main.py <城市名> [选项]
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `city` | 字符串（必填） | — | 城市名，支持中英文及"城市, 国家"格式 |
| `--radius` | 数字（米） | `2000` | 从城市中心向外的抓取半径 |
| `--output` | 目录路径 | `./output` | OBJ 和 MTL 文件的保存目录 |
| `--min-buildings` | 整数 | `5` | 最少建筑数量，低于此值终止并报错 |
| `--verbose` / `-v` | 标志 | 关闭 | 打印详细进度与警告信息 |

### 示例

```bash
# 巴黎，半径 1.5km
python main.py "Paris, France" --radius 1500

# 东京，保存到自定义目录，显示详细信息
python main.py "Tokyo" --radius 2000 --output /tmp/tokyo --verbose

# 小范围测试（梵蒂冈）
python main.py "Vatican City" --radius 500 --min-buildings 3

# 上海陆家嘴，2km 半径
python main.py "Shanghai" --radius 2000 --output ./shanghai_model
```

---

## 输出格式说明

### OBJ 文件

- **坐标系**：X = 东，Y = 北，Z = 上（右手系）
- **单位**：1 OBJ 单位 = 1 米
- **比例标注**：文件头注明 1:10000（即模型覆盖的真实范围是尺寸的 10000 倍）
- **分组**：每栋建筑为一个独立 `g building_<osm_id>` 组

### MTL 材质

| 材质名 | 用途 | 颜色 |
|--------|------|------|
| `mat_wall` | 建筑外墙 | 浅灰色 |
| `mat_roof` | 屋顶 | 砖红色 |
| `mat_ground` | 地面 | 深灰色 |

### 在 3D 软件中导入

**Blender**：`File → Import → Wavefront (.obj)`，导入时单位选 `Meters`

**MeshLab**：`File → Import Mesh`，直接打开 `.obj` 文件

**其他软件**（SketchUp、3ds Max 等）均支持 OBJ 格式，直接导入即可

---

## 数据校验说明

程序运行时自动执行三阶段校验：

| 阶段 | 检查内容 |
|------|----------|
| **A. 建筑轮廓** | 建筑数量是否达标、高度是否合理（1.5～800m）、多边形几何有效性、坐标是否在范围内 |
| **B. 三维网格** | 面索引是否越界、顶点坐标是否含 NaN/Inf |
| **C. 输出文件** | OBJ/MTL 文件非空、材质引用一致、顶点面数大于零、包围盒与请求范围匹配 |

校验发现 **ERROR** 时程序终止并返回非零退出码；**WARNING** 仅打印提示，不影响输出。

---

## 常见问题

**Q: 城市找不到怎么办？**
尝试更精确的名称，例如 `"Beijing, China"` 或 `"München, Germany"`。

**Q: 建筑数量很少？**
部分城市的 OpenStreetMap 数据不完整。可以尝试增大 `--radius`，或在 [openstreetmap.org](https://www.openstreetmap.org) 贡献数据。

**Q: 运行很慢？**
Overpass API 对大范围查询响应较慢。建议 `--radius` 不超过 3000m；网络异常时程序会自动重试最多 3 次。

**Q: 导入 Blender 后建筑方向不对？**
导入时将 **Forward** 设为 `-Z Forward`，**Up** 设为 `Y Up`，与程序坐标系一致。

---

## 数据来源与许可

本工具使用 [OpenStreetMap](https://www.openstreetmap.org) 数据，遵循 [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/)。

使用输出模型时请注明：**© OpenStreetMap contributors**
