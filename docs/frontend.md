# 前端

> 分篇之三（入口见 `overview.md`）。人的唯一检查面与裁决面——把关人不读代码，读画布。
> 对着 `src/simulanka/server/` 与 `frontend/src/` 写成。标注 🔲 的是已定稿、未施工的规格（切片⑥等）。

## 技术栈与启动

- 后端：FastAPI（`simulanka serve`），单用户本地服务；启动时激活 `.simulanka/` 内嵌 git 检查点仓（agent 写权只从 server 进入，安全网先于风险就位）。
- 前端：Svelte + Vite + LiteGraph.js；dev 模式 vite 代理 API（**注意：新增后端路由必须同步加进 vite proxy 名单**——`/ui`、`/discussion` 两次踩坑）。
- 实时：SSE（`/events`），轮询事件日志，按 commit 推送受影响实体 id，前端只刷相关视图。

## 服务端 API

| 端点 | 用途 |
| --- | --- |
| `GET /graph?root&depth` | 子图载荷：nodes（含 `child_count`）、edges、**boundary_edges**（恰一端在视图内）、external_nodes、ports、ancestors（面包屑） |
| `GET /events` | SSE：每 commit 一条 `{graph_version, actor, nodes/edges/ports}` 受影响集 |
| `GET/POST /ui/positions` | 节点位置持久化（按视图分桶，`.simulanka/ui/positions.json`） |
| `POST /edge` · `DELETE /edge/{id}` | 人画/删 data_flow 边（`source=user`，可带画线时 `shape_check`） |
| `POST /edge/{id}/verdict` | 人裁决：correct/wrong/disputed，**note 必填**（辩护即学习时刻）；拒 ghost 不删边，留在分歧队列 |
| `POST /edge/{id}/accept` | 接受 ghost（同意无需辩护；仅人可点——写权矩阵） |
| `POST /edge/{id}/discuss` | 手动拉边进/出讨论集 |
| `GET /disagreements` | 分歧集（纯 attrs 计算，无额外状态）：人拒的 ghost / agent 打 wrong-uncertain 的人边 / disputed / 手动 |
| `POST /discussion/start|message` · `GET /discussion` | 一批一场讨论：start 快照分歧集 + 打 `discussion-start` 恢复 tag + 开 opencode session；每轮 ops 块过写权闸 |

## 渲染器（litegraph-adapter）

- **统一 node-edge-port 渲染**：任何类型的节点同一套画法；`child_count > 0` 即可**双击下钻**，面包屑由服务端 ancestors 重建（下钻/跳转/深链一致）。
- **跨层边界端口投影**（§12.4）：恰一端在视图内的边投影到虚拟 boundary 节点——纯渲染，虚拟节点永不进图。
- **布局**：dagre 自动布局，人工拖动的位置持久化并覆盖 dagre 结果。
- **边语义染色**（夜空主题 theme.ts）：user=金、agent=紫、ghost（proposed 未决）=灰蓝虚线、人拒=绯红；trace 边与「constructed 可信」同源同色（星蓝）。
- 画线时即时 shape 校验（match/mismatch/unknown），人的确认意图随边记录。

## 面板

- **NodeInspector**：属性侧栏，选中实体的全部 attrs。
- **VerifyPanel（核对面板）**：分歧四桶批量核对——裁决、接受、拉入讨论。
- **DiscussPanel（讨论面板）**：一批一场；agent 无写工具，回复中的 ops 块经写权闸逐条落图/拒绝，拒绝理由回到聊天；画布经 SSE 同步刷新。

## 写权矩阵（执行点在此层）

| 动作 | user | agent |
| --- | --- | --- |
| 画/删边、接受 ghost | ✅ | ❌ |
| 裁决 verdict | ✅ correct/wrong/disputed（note 必填） | ✅ correct/wrong/uncertain（note 必填），**verdict_by=user 的边不可碰** |
| 提议边 | —（直接画） | ✅ 必须带 citation，生而 proposed/unconfirmed |
| 撤边 | ✅ 任意非结构边 | ✅ 仅自己未被接受的 ghost |
| 实域 attrs（shape_check 等） | ✅ | ❌ |

人裁至上：agent 永远覆盖不了 `verdict_by=user`。kernel 记账不裁权，本层是闸门。

## 交互定案：锚定式对话（§13.6，2026-07-08 定）

不做全局自由聊天窗。**对话必锚定画布选择集**（一至多个节点/边；无自然实体则锚到容器——experiment、计划目录、根）。消息**不进图**：留在会话树/sidecar 文件，图侧至多一个指向锚点的 note。现状：分歧批次讨论（DiscussPanel）是该模型的已落地特例；通用锚定对话为待实现方向，优先级在 §14 静态缺口之后。

## 待实现（静态验收缺口）

**通用文件查看器 + 深链文档出处** 🔲（2026-07-09 用户指正：按「所有文件」抽象，勿按触发用例特化——能力的自然宿主是 file 节点，不是 plan 文件）：

- server 一个「按 file 节点读内容」端点，**任何 kind 通吃**（plan/brief/doc/config/run 日志……都是 file 节点）。
- 前端一个只读文档抽屉：markdown 渲染，其余纯文本/代码预格式化；「打开并高亮一个词」做成通用参数。
- **深链出处＝特例**：研究原子带 `plan_file`+`plan_lid` → 打开该文件、高亮 lid。图是文档的有损投影，这条链是投影可逆性的人面保证。
- **run 日志（stdout/stderr file 节点）由此免费前端可读**——人肉彩排「全程前端可见」的闭环件。
- **不做**：编辑、双向同步、逐条精确锚定（匹配不到退化开顶部）；跳编辑器按钮不预做。

**按轮下钻 + 信息密度** 🔲：ingest 已按计划建轮次目录（`research/<plan-stem>/`），下钻机制现成。呈现要求（2026-07-09 用户定为硬需求）：**日常所需信息大多数不点开侧栏就能从画布读到**。每类研究原子一张卡片：question/claim=正文摘要+状态徽记、hypothesis=正文+verdict 徽记、experiment=goal+status、task=goal+契约摘要、run=状态/时长/exit code、evidence=关键 metrics 数值。字段清单=可调项（首版 Claude 定，彩排中按用户反馈迭代）。

**可信度染色 + 血缘链** 🔲（切片⑥规格，可与皮肤轮同捆）：

两条硬原则：**查询时算、不落盘**；**展示血缘、不折叠**——不做 min/加权把上游可信度折成一个分数，图存在的意义就是让人看见「为什么可信」。

每实体可信级（确定性映射，只读既有铭章，按优先序）：

| 级 | 判据 | 染色 |
| --- | --- | --- |
| human | `verdict_by=="user"` 或人批标记 | 金 |
| constructed | `source ∈ {trace, machine}` | 星蓝（与 trace 边同色） |
| reviewed | 有 `reviewed_in` | 玉 |
| checked | 有 `checked_by` | 琥珀 |
| unreviewed | 以上皆无 | 灰（「未定」应显眼地不显眼） |

- 血缘链查询 `GET /node/{id}/provenance`：claim/hypothesis 沿固定边集回溯（supports/contradicts → evidence →（parent/produces 逆）→ run → fulfills → task →（parent）→ experiment → plan_file → 计划文件节点），每跳 `{id, type, name, trust, via_edge, via_edge_trust}`——边与节点分别定级（supports 边是分析者判断、evidence 是机器测量，可信级常不同，这正是不折叠的理由）。visited 防环，按 id 排序保证确定性。
- 研究域节点 view payload 带 `trust` 字段（服务端算）；NodeInspector 加可信级徽记 + 血缘链列表（逐跳可点跳转）。
- 配套铭章：`reviewed_in`（plan ingest 已盖✅）；`checked_by/checked_at/check_note`（快检工具属动态线，铭章词表先定）。
- v1 不做：数值分数（伪精度）、跨实体折叠聚合、question 可信级（提问不是断言）、快检章的矩阵强制。

**内嵌 agent 会话（插座子任务，静态末位）** 🔲（2026-07-09 grill 定）：前端起一个自由 agent 会话——agent 像在自己的 harness 里一样做任何事，界面是前端。技术路线＝**结构化事件流 + 原生会话面板**：用 harness 无头流式接口（opencode JSON / `claude -p --output-format stream-json`），渲染为对话气泡 + 工具调用卡片 + 流式输出；每 harness 一个薄展示适配器（只薄在展示层，调用与写权仍 harness 无关），先只接 opencode（免费模型现成）。写图仍只经 CLI/写权闸；会话干 task 时自己调 `run begin/end` 打卡（打卡即会话的图身份）。
**验收**：免费模型跑一个玩具 task，会话/diff/验收/落图全程前端可见，输出好坏不作数。
**与 §13.6 的边界**：不冲突——§13.6 禁的是「谈论图的无锚聊天」；这是**干活的会话**，锚天然是 task/run。
**死端勿再试**：PTY 终端透传（xterm.js 嵌 TUI）作主路线——原型实测体验差，TUI 重绘/尺寸同步/输入法驯服成本无底；降级为逃生舱，sidecar 录制思想保留。

**美术皮肤**（原神童话风）：不作为静态验收条件，随前端波次择机。
