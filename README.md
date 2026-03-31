# BTD6 API Processor

基于 Ninja Kiwi Open Data API 的 BTD6 数据抓取与整理工具。

本项目适合两类使用场景：
- 作为命令行工具，定时生成群公告用的 Markdown 或排行榜图片。
- 作为 Python 模块，被其他项目直接调用，拿到结构化结果后继续加工。

当前覆盖活动：Race、Boss、Odyssey、Daily。
说明：CT 相关链路已在本项目中移除。

---

## 1. 功能总览

- 获取 BTD6 官方 Open Data 原始数据。
- 输出活动简报（summary）。
- 输出最新一期详细信息（detail）：race / boss / odyssey / daily。
- 输出排行榜（leaderboard）：
  - markdown 文本榜单
  - image 图片榜单（适合社群转发）
- 支持翻译表（translate.md）做中文化映射。
- 支持缓存只读查询 + 独立刷新服务策略。
- 支持一键全量更新（update）。
- 支持定时刷新服务（默认每 10 分钟）。

---

## 2. 目录结构

```text
.
├── btd6_cli.py                # CLI 入口
├── api_raw_fetcher.py         # 原始 API 请求层
├── btd6_core/
│   ├── common.py              # 通用工具：翻译、时间、格式化
│   ├── cache_store.py         # 缓存索引与文件读写
│   ├── summary_service.py     # 简报生成
│   ├── detail_service.py      # 详情生成
│   ├── leaderboard_service.py # 排行榜生成
│   ├── image_renderer.py      # PNG 排行榜渲染
│   └── update_service.py      # 全量更新流程
├── translate.md               # 翻译映射表
├── cache_index.json           # 缓存索引
├── race/ boss/ odyssey/ daily/# 输出目录（运行时自动创建）
└── assets/fonts/              # 图片渲染字体缓存
```

---

## 3. 环境与安装

### 3.1 Python 版本

推荐 Python 3.10+。

### 3.2 安装依赖

本项目核心网络请求使用标准库 urllib，图片输出依赖 Pillow。

```bash
pip install pillow
```

### 3.3 API Key（可选）

可通过环境变量设置：

```bash
export NK_API_KEY="your_api_key"
```

也可以每次通过 `--api-key` 传入。

---

## 4. 命令行接口（CLI）

入口脚本：`btd6_cli.py`

```bash
python btd6_cli.py --help
```

### 4.1 公共参数

- `--api-key`：Ninja Kiwi API Key，可选。
- `--translate`：翻译表路径，默认 `translate.md`。
- `--output`：主输出文件路径，默认 `btd6_digest.md`。
- `--mode`：模式，可选 `summary` / `detail` / `leaderboard` / `update` / `refresh-service`。
- `--refresh-interval-seconds`：refresh-service 刷新间隔，默认 600 秒。

### 4.2 summary 模式（只读缓存）

生成当前活动简报（Race/Boss/Odyssey/Daily）。

```bash
python btd6_cli.py \
  --mode summary \
  --output out/summary.md
```

### 4.3 detail 模式（只读缓存）

生成指定活动类型的“最新一期详细信息”。

参数：
- `--detail-types`：逗号分隔，支持 `race,boss,odyssey,daily`。

示例：

```bash
python btd6_cli.py \
  --mode detail \
  --detail-types race,boss \
  --output out/detail.md
```

说明：
- 若只传一个类型，输出该类型详情。
- 若传多个类型，主输出会包含每个类型的文件路径和合并内容。

### 4.4 leaderboard 模式（只读缓存）

生成排行榜（当前实现固定从第一页起拉取，内部按类型取固定人数）。

参数：
- `--leaderboard-type`：`race` / `boss-standard` / `boss-elite`
- `--leaderboard-format`：`markdown` / `image`

示例（文本排行榜）：

```bash
python btd6_cli.py \
  --mode leaderboard \
  --leaderboard-type race \
  --leaderboard-format markdown \
  --output out/race_lb.md
```

示例（图片排行榜）：

```bash
python btd6_cli.py \
  --mode leaderboard \
  --leaderboard-type boss-elite \
  --leaderboard-format image \
  --output out/boss_elite_image_result.md
```

说明：
- `--output` 保存的是执行摘要（来源、生成文件路径），真正榜单文件写入活动目录。
- 图片榜单仅显示：排行、玩家、得分。

### 4.5 update 模式（主动刷新）

一键更新所有核心数据：
- 简报：summary
- 详情：race / boss / odyssey / daily
- 排行榜：race / boss-standard / boss-elite（markdown + image）

```bash
python btd6_cli.py \
  --mode update \
  --output out/update.md
```

### 4.6 refresh-service 模式（定时刷新）

启动常驻刷新服务，默认每 10 分钟刷新一次全部数据。

```bash
python btd6_cli.py \
  --mode refresh-service \
  --refresh-interval-seconds 600 \
  --output out/refresh-service.log
```

---

## 5. 输出文件协议

### 5.1 详情输出

- `race/{event_id}_detail.md`
- `boss/{event_id}_detail.md`
- `odyssey/{event_id}_detail.md`
- `daily/{event_id}_detail.md`

### 5.2 排行榜输出

Markdown：
- `race/{event_id}_top100.md`
- `boss/{event_id}_standard_top150.md`
- `boss/{event_id}_elite_top150.md`

Image：
- `race/{event_id}_top100.png`
- `boss/{event_id}_standard_top150.png`
- `boss/{event_id}_elite_top150.png`

### 5.3 固定人数策略（image）

- Race：固定前 100 人（取前 2 页并截断）。
- Boss：固定前 150 人（尝试前 6 页并截断）。

---

## 6. 缓存机制

缓存索引文件：`cache_index.json`

索引结构示例：

```json
{
  "items": {
    "detail:race": {
      "id": "race_event_id",
      "path": "race/race_event_id_detail.md",
      "updatedAt": "2026-03-24T12:34:56"
    },
    "leaderboard:boss-elite:image-fixed": {
      "id": "boss_event_id",
      "path": "boss/boss_event_id_elite_top150.png",
      "updatedAt": "2026-03-24T12:35:10"
    }
  }
}
```

读取逻辑：
- `summary` / `detail` / `leaderboard` 模式只读取缓存文件。
- 缓存不存在时会报错提示先执行 `update` 或 `refresh-service`。
- 远程刷新仅由 `update` 与 `refresh-service` 负责。

---

## 7. 对外可复用的 Python 接口

下面接口可直接在其他 Python 项目中导入调用。

### 7.1 原始请求层

文件：`api_raw_fetcher.py`

- `ApiClient(api_key: str | None = None, timeout: int = 30, retries: int = 5)`
- `ApiClient.get(path_or_url: str) -> dict`
- `fetch_raw_data(client: ApiClient) -> dict`

说明：
- `get` 支持传完整 URL 或相对路径。
- 内置重试与指数退避。
- 统一期望 Open Data 返回格式：`{ success, error, body }`。

示例：

```python
from api_raw_fetcher import ApiClient, fetch_raw_data

client = ApiClient(api_key=None)
raw = fetch_raw_data(client)
print(raw.keys())  # dict_keys(['races', 'bosses', 'odyssey', 'daily'])
```

### 7.2 简报服务

文件：`btd6_core/summary_service.py`

- `build_report(client, trans) -> str`
- `resolve_summary(client, trans, refresh=False) -> tuple[path, content, cached]`

示例：

```python
from pathlib import Path
from api_raw_fetcher import ApiClient
from btd6_core.common import parse_translation_tables
from btd6_core.summary_service import build_report

client = ApiClient()
trans = parse_translation_tables(Path("translate.md"))
report = build_report(client, trans)
```

### 7.3 详情服务

文件：`btd6_core/detail_service.py`

- `resolve_detail(client, trans, detail_type, refresh=False) -> tuple[path, content, cached]`

参数：
- `detail_type`：`race` / `boss` / `odyssey` / `daily`

返回：
- `path`：详情文件路径
- `content`：详情文本
- `cached`：是否来自缓存

说明：
- `refresh=False` 时只读缓存，不会主动请求远程。

### 7.4 排行榜服务

文件：`btd6_core/leaderboard_service.py`

- `resolve_leaderboard(client, leaderboard_type, page, output_format="markdown", refresh=False) -> tuple[path, content, cached]`

参数：
- `leaderboard_type`：`race` / `boss-standard` / `boss-elite`
- `page`：保留参数，当前内部统一按固定策略处理
- `output_format`：`markdown` / `image`

返回：
- `path`：榜单文件路径（md 或 png）
- `content`：markdown 内容（image 时为空字符串）
- `cached`：是否来自缓存

说明：
- `refresh=False` 时只读缓存，不会主动请求远程。

### 7.5 更新服务

文件：`btd6_core/update_service.py`

- `update_all_data(client, trans) -> str`

用于批量刷新 summary、所有详情和排行榜（默认第一页基准 + 固定人数策略）。

文件：`btd6_core/refresh_service.py`

- `run_refresh_service(client, trans, interval_seconds=600, log_path=None) -> None`

用于常驻定时刷新服务。

---

## 8. 翻译表规范（translate.md）

解析逻辑在 `btd6_core/common.py` 的 `parse_translation_tables`。

支持分类标题：
- 难度等级
- 英雄
- 猴塔
- 地图
- 地图类型
- 游戏模式
- BOSS气球

每个分类使用 Markdown 表格，至少两列（英文、中文）。

示例：

```md
## 4. 地图
| 英文 | 中文 |
| --- | --- |
| MonkeyMeadow | 猴子草地 |
| TreeStump | 树桩 |
```

---

## 9. 图片排行榜渲染说明

渲染模块：`btd6_core/image_renderer.py`

- 默认自动尝试下载并缓存中文字体到 `assets/fonts/NotoSansSC-Regular.otf`。
- 竞速图布局：4 列 × 25 行。
- Boss 图布局：3 列 × 50 行。
- 每行字段：排行、玩家、得分。
- 使用斑马纹提高可读性。

---

## 10. 典型接入方式

### 10.1 作为定时任务

先启动刷新服务，再由业务侧按需读取缓存：

```bash
python btd6_cli.py --mode refresh-service --refresh-interval-seconds 600 --output out/refresh.log
python btd6_cli.py --mode summary --output out/summary.md
python btd6_cli.py --mode leaderboard --leaderboard-type race --leaderboard-format image --output out/race_image.md
```

你的系统只需读取 `out/*.md` 和活动目录下生成的 `*.png` 即可。

### 10.2 在已有 Python 服务中调用

```python
from pathlib import Path
from api_raw_fetcher import ApiClient
from btd6_core.common import parse_translation_tables
from btd6_core.detail_service import resolve_detail

client = ApiClient()
trans = parse_translation_tables(Path("translate.md"))
path, content, cached = resolve_detail(client, trans, "boss", refresh=False)

payload = {
    "path": str(path),
    "cached": cached,
    "preview": content[:200],
}
```

---

## 11. 错误处理建议

- 网络波动：已内置重试与退避；若业务侧严格 SLA，建议外层再包一层任务重试。
- 缓存文件缺失：查询命令会报错，请先执行 `update` 或 `refresh-service`。
- API 失败：`ApiClient.get` 会抛出 `RuntimeError`，上层应记录日志并告警。

---

## 12. 数据来源与免责声明

- 数据来源：Ninja Kiwi Open Data API
- 本项目为数据整理与展示工具，不隶属于 Ninja Kiwi 官方。
