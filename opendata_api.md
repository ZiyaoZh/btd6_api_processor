以下是将提供的 API 文档整理成的 Markdown 文档，按模块分类，包含端点、描述、参数及响应模型说明：

---

# Ninja Kiwi Open Data API 文档

## BTD6 API
- **base url**: https://data.ninjakiwi.com/

### 竞速（Races）

#### 获取所有竞速赛事件
- **端点**：`/btd6/races`
- **描述**：获取所有可用的竞速赛事件列表。
- **参数**：无
- **响应模型**：`_btd6race`

#### 获取竞速赛排行榜
- **端点**：`/btd6/races/:raceID/leaderboard`
- **描述**：获取指定竞速赛的排行榜。
- **参数**：`:raceID` - 竞速赛 ID
- **响应模型**：`_btd6raceleaderboard`

#### 获取竞速赛元数据
- **端点**：`/btd6/races/:raceID/metadata`
- **描述**：获取指定竞速赛的详细信息。
- **参数**：`:raceID` - 竞速赛 ID
- **响应模型**：`_btd6challengedocument`

---

### BOSS活动（Boss Events）

#### 获取所有首领战事件
- **端点**：`/btd6/bosses`
- **描述**：获取所有可用的首领战事件列表。
- **参数**：无
- **响应模型**：`_btd6boss`

#### 获取首领战排行榜
- **端点**：`/btd6/bosses/:bossID/leaderboard/:type/:teamSize`
- **描述**：获取指定首领战的排行榜。
- **参数**：
  - `:bossID` - 首领战 ID
  - `:type` - `standard` 或 `elite`
  - `:teamSize` - 团队规模，目前仅支持 `1`
- **响应模型**：`_btd6bossleaderboard`

#### 获取首领战元数据
- **端点**：`/btd6/bosses/:bossID/metadata/:difficulty`
- **描述**：获取指定首领战的元数据。
- **参数**：
  - `:bossID` - 首领战 ID
  - `:difficulty` - `standard` 或 `elite`
- **响应模型**：`_btd6challengedocument`

---

### 每日挑战（Challenges）

#### 获取挑战筛选器列表
- **端点**：`/btd6/challenges`
- **描述**：获取所有可用的挑战筛选器。
- **参数**：无
- **响应模型**：`_btd6challengetype`

#### 根据筛选器获取挑战列表
- **端点**：`/btd6/challenges/filter/:challengeFilter`
- **描述**：根据指定筛选器获取挑战列表。
- **参数**：`:challengeFilter` - `newest`、`trending`、`daily`
- **响应模型**：`_btd6challenge`

#### 获取挑战详情
- **端点**：`/btd6/challenges/challenge/:challengeID`
- **描述**：获取指定挑战的详细信息。
- **参数**：`:challengeID` - 挑战 ID
- **响应模型**：`_btd6challengedocument`

---

### CT战（Contested Territory）

#### 获取 CT 事件列表
- **端点**：`/btd6/ct`
- **描述**：获取当前及历史 CT 事件信息。
- **参数**：无
- **响应模型**：`_btd6ct`

#### 获取 CT 事件地块信息
- **端点**：`/btd6/ct/:ctID/tiles`
- **描述**：获取指定 CT 事件的地块信息。
- **参数**：`:ctID` - CT 事件 ID
- **响应模型**：`_btd6cttile`

#### 获取玩家排行榜
- **端点**：`/btd6/ct/:ctID/leaderboard/player`
- **描述**：获取指定 CT 事件的玩家排行榜。
- **参数**：`:ctID` - CT 事件 ID
- **响应模型**：`_btd6ctleaderboardplayer`

#### 获取团队排行榜
- **端点**：`/btd6/ct/:ctID/leaderboard/team`
- **描述**：获取指定 CT 事件的团队排行榜。
- **参数**：`:ctID` - CT 事件 ID
- **响应模型**：`_btd6ctleaderboardteam`

#### 获取团队分组信息
- **端点**：`/btd6/ct/:ctID/leaderboard/group/:groupID`
- **描述**：获取指定团队的分组信息。
- **参数**：
  - `:ctID` - CT 事件 ID
  - `:groupID` - 分组 ID
- **响应模型**：`_btd6ctleaderboardteam`

---

### 征程（Odyssey）

#### 获取所有奥德赛事件
- **端点**：`/btd6/odyssey`
- **描述**：获取所有可用的奥德赛事件列表。
- **参数**：无
- **响应模型**：`_btd6odyssey`

#### 获取奥德赛元数据
- **端点**：`/btd6/odyssey/:odysseyID/:difficulty`
- **描述**：获取指定奥德赛事件的元数据。
- **参数**：
  - `:odysseyID` - 奥德赛 ID
  - `:difficulty` - `easy`、`medium`、`hard`
- **响应模型**：`_btd6odysseymetadata`

---

## 说明

- 所有时间字段均为 Unix 纪元毫秒数。
- `assetURL` 类型表示资源图标链接。
- `raw` 类型字段为内部结构，文档中未展开。
- 部分字段已标记为 `[Deprecated]`，建议使用替代字段。