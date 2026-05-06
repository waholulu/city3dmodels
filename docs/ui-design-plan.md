# City 3D Models UI Design Work Plan

## 1. 背景

`city3dmodels` 当前核心能力已具备：可从 OpenStreetMap 抓取建筑并导出 OBJ/MTL，支持 `--scale`、`--crop`、`--tile`、`--base-mm` 等参数。

当前体验痛点在于用户需要自行理解以下关系：

- 标准照片尺寸
- 最终打印尺寸
- 比例尺
- 真实世界截取范围
- 抓取半径
- 底板厚度

本方案目标：以“打印成品尺寸”为主入口，降低 CLI 参数心智负担。

## 2. 产品目标

第一版 UI 核心目标：

1. 用户能明确最终打印尺寸。
2. 用户能明确打印尺寸对应真实世界范围。
3. 用户能在地图上预览并调整截取范围。

## 3. 非目标（v1）

- 账号系统
- 云端任务队列
- 多人协作
- 在线支付/模型市场
- 浏览器内完整 3D 编辑器
- STL 支持（后续再评估）

## 4. 技术路线

- Streamlit
- Folium
- streamlit-folium

新增文件：

- `app.py`
- `src/print_layout.py`
- `docs/ui-design-plan.md`

新增依赖：

- `streamlit`
- `folium`
- `streamlit-folium`

## 5. 核心用户流程

基础流程：

1. 输入城市名。
2. 选择标准照片尺寸。
3. 选择横向/竖向。
4. 选择打印比例尺。
5. 设置底板厚度。
6. 查看地图预览。
7. 点击生成。
8. 下载 OBJ/MTL/ZIP。

高级流程：

- 自定义中心点（经纬度）
- 调整 fetch buffer
- 设置最少建筑数量
- 覆盖抓取半径
- verbose 日志

## 6. 页面结构

### 6.1 标题区

- Title: `City 3D Print Preview`
- Subtitle（EN+中文）

### 6.2 左侧参数区

- 城市设置
- 打印尺寸设置（预设 + Custom）
- 方向设置（Portrait / Landscape）
- 比例尺设置（预设 + Custom）
- 底板厚度 slider（0.0–5.0mm）
- 高级设置（fetch buffer / min buildings / output folder / verbose / override radius）

### 6.3 中间预览区

- 打印摘要卡片：print size、crop size、scale、base、fetch radius
- 地图预览：
  - 红色实线：最终 crop 区域
  - 灰色虚线：fetch buffer 区域
  - 蓝色标记：中心点

### 6.4 右侧输出区

- 生成前：Ready
- 生成中：状态与日志
- 生成后：building count、输出路径、OBJ/MTL/ZIP 下载按钮

## 7. 核心计算逻辑

统一收敛到 `src/print_layout.py`：

- `PrintLayout` 数据结构
- `compute_print_layout()`
- `resolve_print_size_cm()`

关键公式：

- `crop_width_m = print_width_cm * scale / 100`
- `crop_height_m = print_height_cm * scale / 100`
- `fetch_radius_m = max(crop_width_m, crop_height_m) / 2 * (1 + fetch_buffer_pct)`

关键原则：

- `crop` 决定最终打印模型尺寸。
- `radius` 只决定抓取数据范围。

## 8. 与现有 CLI 关系

UI 复用现有 pipeline，不重写生成链路。

等价调用：

- `scale=layout.scale`
- `crop_cm=(layout.print_width_cm, layout.print_height_cm)`
- `base_mm=layout.base_thickness_mm`
- `radius_m=layout.fetch_radius_m`

## 9. 文档与一致性修正

- README 默认比例尺统一为 `1:50000`
- OBJ 单位说明统一为 `mm`
- `--tile` 文案改为“at the selected print scale”
- validator 输出中的比例尺由运行时传入的 `scale` 决定

## 10. 第一版验收标准

1. 用户可不写 CLI 完成生成。
2. 支持标准照片尺寸 + 自定义尺寸。
3. 支持横竖方向切换。
4. 支持比例尺配置。
5. 支持底板厚度配置。
6. 实时显示打印尺寸与真实截取范围。
7. 地图显示 crop 与 fetch 框。
8. 调用现有 pipeline 生成 OBJ/MTL。
9. 结果区可下载 OBJ/MTL/ZIP。
10. README 与 UI 描述一致。

## 11. 优先级

- P0：换算模块、基础 UI、README/单位/比例尺统一
- P1：地图增强、下载按钮、validator 文案一致
- P2：可拖动中心点、配置保存、3D 预览

## 12. 最终原则

让用户关注“打印成品”而非底层参数耦合：

- 我要打印多大
- 我要覆盖多大真实区域
- 我要底板多厚
- 我要截取哪里

