# 前端

> 分篇之三（入口见 `overview.md`）。人的唯一检查面与裁决面——把关人不读代码，读画布。
> 对着 `src/simulanka/server/` 与 `frontend/src/` 写成。标注 🔲 的是已定稿、未施工的规格（仅余 S8；编号见 overview 施工清单）。

## 技术栈与启动

- 后端：FastAPI（`simulanka serve`），单用户本地服务；启动时激活 `.simulanka/` 内嵌 git 检查点仓（agent 写权只从 server 进入，安全网先于风险就位）。
- 前端：Svelte + Vite + LiteGraph.js；dev 模式 vite 代理 API（**注意：新增后端路由必须同步加进 vite proxy 名单**——`/ui`、`/discussion` 两次踩坑；**且 proxy 键是前缀匹配**：`'/node'` 会吞掉 `/node_modules/**` 打死全部模块加载，短路由名必须写正则键 `'^/node(/|$)'`——2026-07-12 第三坑）。
- 实时：SSE（`/events`），轮询事件日志，按 commit 推送受影响实体 id，前端只刷相关视图。

## 服务端 API

| 端点 | 用途 |
| --- | --- |
| `GET /graph?root` | 单容器视图载荷：nodes=root 的**直接孩子**（含 `child_count`；root 本人永不入 nodes，其名片在 `root_info`）、edges、**boundary_edges**（恰一端在视图内，contains 除外——root 端口连向孩子的边落在此，即子图输入/输出括号）、external_nodes、ports、ancestors（面包屑）。无 depth 旋钮：视图永不混层（2026-07-12 定） |
| `GET /events` | SSE：每 commit 一条 `{graph_version, actor, nodes/edges/ports}` 受影响集 |
| `GET/POST /ui/positions` | 节点位置持久化（按视图分桶，`.simulanka/ui/positions.json`） |
| `POST /edge` · `DELETE /edge/{id}` | 人画/删 data_flow 边（`source=user`，可带画线时 `shape_check`） |
| `POST /edge/{id}/verdict` | 人裁决：correct/wrong/disputed，**note 必填**（辩护即学习时刻）；拒 ghost 不删边，留在分歧队列 |
| `POST /edge/{id}/accept` | 接受 ghost（同意无需辩护；仅人可点——写权矩阵） |
| `POST /edge/{id}/discuss` | 手动拉边进/出讨论集 |
| `GET /disagreements` | 分歧集（共享模块 `disagreements.py`，与 brief 同一计算）：人拒的 ghost / agent 打 wrong-uncertain 的人边 / disputed / 手动 |
| `GET /file/content?node|path` | S4 文件查看器：按 file 节点读内容（node=节点 id / path=fs_path 反查，二选一）；未登记路径 404（图是「什么可读」的权威）；binary/truncated 如实标记，上限 1 MiB |
| `POST /node` | 画布加节点（右键菜单）：`{type, name, parent?, attrs?, ports?}`，actor=user；parent=当前视图 root；同胞重名自动 `_2` 后缀（菜单连放三个 Conv2d 必须直接成）；ports 走第二个 patch（resolver 看不见未提交节点，与 importer 同型）；kernel 容器矩阵违规→422 |
| `POST /node/{id}/rename` | 改名（RenameNodeOp）；file/directory 拒改（name ↔ fs_path 是 FileRegistry 领地）；重名冲突 422 |
| `DELETE /node/{id}` | 删**空**节点（kernel DeleteNodeOp：级联自身端口+关联边+父 contains——后者是建点双写的合法逆操作；有孩子 422 先清空）；画布策略=仅 module/model（file/directory 绑磁盘、研究原子血缘不可断）。Delete 键与右键「删除」同走此路——画布永不本地假删 |
| `GET/POST /ui/templates` · `DELETE /ui/templates/{name}` | 自定义节点模板（`.simulanka/ui/templates.json`，按名 keyed、可覆写）；UI 态非图实体——图只记真正放置过的东西 |
| `GET /node/{id}` | slim locator `{id,type,name,parent_id}`——「跳转并选中」原语的服务端半边：选中一个实体先得打开它父容器的视图（S6 血缘链逐跳 / S7 卡片点击共用） |
| `GET /node/{id}/provenance` | S6 血缘链：固定边集回溯（claim/hypothesis ← supports/contradicts ← evidence ←(produces/parent)← run →fulfills→ task →parent→ experiment →plan_file→ 计划文件节点），每跳 `{id,type,name,trust,via_edge,via_edge_trust}`，节点与边分别定级；查询时算不落盘；visited 防环、按 id 排序 |
| `POST /node/{id}/resolve` | S7 escalate 就地「已处理」：`status→resolved`、`actor=user`、可附 `resolve_note`（包 `plan.resolve_escalate`，与 CLI `note resolve` 同芯）；非 escalate note 422；重复 resolve 422——停止信号恰好解除一次 |
| `POST /discussion/start|message` · `GET /discussion` | **会话=语言原语（2026-07-14 解耦）**：start 无分歧也可开（空批次=通用图助手开场）；有分歧则批次开场（一批一场保留）。均打 `discussion-start` 恢复 tag + 开 opencode session；每轮 ops 块过写权闸。消息可带锚定戳（锚定：…）。**空批次会话固定走仓库级无工具 agent `graph-chat`**（`.opencode/agent/graph-chat.md`；agent 选择存进会话状态随轮次沿用）——opencode 默认 build agent 带全套工具，会对着代码库跑几分钟（慢的真凶）；批次核对线保留默认 agent（引证需要读码）。实测默认模型 ~7-9s/轮。「整页卡死」的真凶另在前端：Svelte 5 下 `$:` 里调 `tick()`（=微任务+flushSync）会无限重入刷新循环，ChatNode 挂载即冻死主线程——已改 `afterUpdate`/`queueMicrotask`，**禁止在响应式语句里调 tick()**（无头浏览器复现+调试器中断实证 2026-07-14） |

## 渲染器（litegraph-adapter）

- **统一 node-edge-port 渲染**：任何类型的节点同一套画法；**任意节点双击可进入**（叶子的内部=合法空视图，右键加节点即在其中生长——空容器由此可填充；child_count 是徽记不是闸门），面包屑由服务端 ancestors + root_info 重建（下钻/跳转/深链一致）。
- **跨层边界端口投影**（§12.4）：恰一端在视图内的边投影到虚拟 boundary 节点——纯渲染，虚拟节点永不进图。**root 自身端口=子图声明的 IO，常驻投影为左右括号**（左=in 朝内、右=out；model/module 层空括号也显示=「尚无声明 IO」）；跨界边落在括号槽位或按 (external, direction) 聚合的 boundary 节点上。**括号可连线（2026-07-14）**：槽位携带 root 真端口 id，画线走 POST /edge，kernel **隧道规则**放行（父.in→子.in、子.out→父.out，恰一层；validator 与 doctor 同一规则）。
- **布局**：dagre 自动布局，人工拖动的位置持久化并覆盖 dagre 结果。
- **边语义染色**（夜空主题 theme.ts）：user=金、agent=紫、ghost（proposed 未决）=灰蓝虚线、人拒=绯红；trace 边与「constructed 可信」同源同色（星蓝）。
- 画线时即时 shape 校验（match/mismatch/unknown），人的确认意图随边记录。
- **右键菜单**（2026-07-12，自绘 Svelte 层，LiteGraph 内建菜单/搜索框已灭）：空白处=加节点（搜索 + 分类目录：torch.nn 精选约 45 项按卷积/线性/归一化/激活/池化/注意力/循环/损失/形状/张量运算分组 + 通用容器 + 我的模板）；节点上=进入子图/重命名/存为模板/删除（仅 module/model 出现此项）。菜单收起=window 捕获相 mousedown（LiteGraph 在画布层吃掉冒泡，常规监听收不到——2026-07-14 修）。
- **鼠标/导航（2026-07-14）**：视图历史前进/后退（顶栏 ‹ › + Alt+←/→ + 鼠标侧键；一切导航走 navigateTo 单入口）；框选=引擎原生 **Ctrl+拖**、加选=Shift+点。更成熟的整套手感（左键框选、reroute 等）归引擎换血片（@comfyorg/litegraph）。菜单按 **kernel 容器矩阵过滤**（前端镜像 `registry/builtin.py` 的 allow_parents：module 只在 model/module 内出现、model 只在 directory 内、顶层只有 directory）——kernel 422 仍是硬闸，菜单只是不出注定被拒的项。手放节点=与 importer 同种（type=module + class_name/class_module 约定），端口无 confidence（诚实标注：草图没有观测）。落点=右键处（先记位置再等 SSE 重载）。**研究原子不进菜单**——它们的正路是 plan ingest（§14）。

## 面板

- **NodeInspector**：属性侧栏，选中实体的全部 attrs。
- **消息面（2026-07-12 用户定向、07-14 落地并框架化）**：设计原则=**不出现单一用途按钮，agent→人的一切都是消息**。**框架先行（用户 07-14 再定向）**：现阶段只建语言，不实现子功能——分歧/待裁卡片已从面上剥离（server 端点 `/edge/{id}/verdict|accept|discuss`、`/disagreements` 保留，前端绑定随「消息类型」功能回归）。落地两件：**底部常驻输入条 ChatDock**（只做输入；锚定 chip=选中集优先、否则当前容器，锚定戳随消息发给 agent）+ **会话节点 ChatNode**（画布浮动 node 观感消息面、可拖；纯消息流，错误也进流——状态栏低语被彩排证实读作卡死）。首条消息自动开 opencode 会话；消息本体在会话文件，不进图（图皮文件芯）。
- **VerifyPanel / DiscussPanel——已删除（2026-07-14）**：顶栏「核对」按钮一并退役。就地裁决/跳转选中已随 S7 余项落地（2026-07-15，见下）。

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

不做全局自由聊天窗。**对话必锚定画布选择集**（一至多个节点/边；无自然实体则锚到容器——experiment、计划目录、根）。消息**不进图**：留在会话树/sidecar 文件，图侧至多一个指向锚点的 note。
2026-07-10 更新：「DiscussPanel＝已落地特例」的过渡态结束——核对/讨论全面并入锚定原语，就地裁决部分进静态波次（S7），会话 UI 部分随 S8；「通用锚定对话优先级在静态缺口之后」对就地裁决不再成立。

## 待实现（静态验收缺口）

**S4 通用文件查看器 + 深链文档出处 ✅**（2026-07-09 用户指正：按「所有文件」抽象，勿按触发用例特化——能力的自然宿主是 file 节点，不是 plan 文件。实现：`FileViewer.svelte` + `GET /file/content`，server 侧实测于 `tests/test_server_file_content.py`）：

- server「按 file 节点读内容」端点，**任何 kind 通吃**（plan/brief/doc/config/run 日志……都是 file 节点）；`path` 变体按 `fs_path` 反查 file 节点——未登记的路径即使在盘上也 404，图保持「什么可读」的权威。
- 前端只读文档抽屉（右侧展开，Esc 关）：`.md` 走 marked 渲染（DOMPurify 消毒——plan 文件可能出自 agent 之手），其余纯文本预格式化；「打开并高亮一个词」为通用参数（先试 JSON 引号形 `"lid"` 再试裸词，命中即 `<mark>` 滚动定位）。
- **深链出处＝特例**：带 `plan_file`+`plan_lid` 的原子在 NodeInspector 出「↗ 出处」按钮 → 打开该文件、高亮 lid。图是文档的有损投影，这条链是投影可逆性的人面保证。
- **run 日志（stdout/stderr file 节点）由此免费前端可读**（inspector 上 stdout/stderr 按钮）——人肉彩排「全程前端可见」的闭环件；evidence 的 metrics 按钮同理（未登记则如实报 404）。
- **不做**：编辑、双向同步、逐条精确锚定（匹配不到退化开顶部）；跳编辑器按钮不预做。

**S5 按轮下钻 + 卡片化信息密度 ✅**（实现：`cards.ts` 字段清单 + `litegraph-adapter.ts` 单一绘制骨架）：ingest 按计划建轮次目录（`research/<plan-stem>/`），下钻机制现成。呈现要求（2026-07-09 用户定为硬需求）：**日常所需信息大多数不点开侧栏就能从画布读到**。首版字段清单（可调项，彩排中按用户反馈迭代）：question=正文摘要、hypothesis=verdict 徽记+正文、claim=status 徽记+正文、experiment=status 徽记+goal、task=预算徽记+goal+契约摘要（globs 数·acceptance）、run=status/contract_check 双徽记+时长·exit code、evidence=关键 metrics 数值（至多 3 行）、escalate note=ESCALATE/RESOLVED 徽记+正文。徽记语义色：玉=好结果 / 琥珀=待定 / 绯红=坏结果 / 紫=进行中 / 灰=未判；未知状态词落灰不猜语义。
卡片的实现边界（2026-07-10 定，已照办）：卡片＝统一渲染器里 **attr 驱动的展示模板**——同一套节点画法与卡片骨架（`cards.ts` 是唯一的字段清单来源，dagre 布局同源取高），每类原子只是字段清单不同；不做 per-type 分叉渲染，渲染器原则不破，信息密度靠模板。正文截断=CJK 感知字符预算（全角算 2），不逐节点 measureText。

**S6 可信度染色 + 血缘链** ✅（2026-07-15 落地：`src/simulanka/trust.py` + view payload `trust` 字段 + `GET /node/{id}/provenance`；前端＝节点体 trust 描边（`litegraph-adapter` 与卡片共用 foreground 钩子，unreviewed 刻意最淡）+ NodeInspector 可信徽记与血缘链逐跳可点。**配套铭章**：系统造的血缘边（`fulfills`/`produces`，共 6 处创建点）自此盖 `source="machine"`——否则机器记录的执行事实在链里读作「未定」是不诚实的；旧图未盖章的边如实落灰。实测于 `tests/test_trust.py` + `tests/test_server_trust.py`）：

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
- 边的染色归属（2026-07-10 定）：画布上边仍按既有 source/verdict 语义染色；trust 染色只作用于**节点体**；边的 trust 仅在血缘链视图逐跳展示——画布不叠两套边色。

**S7 锚定核对（口径已修订）** ✅（余项 2026-07-15 落地）：

- **2026-07-12 用户修订口径**：「核对也是一种消息」——原「薄清单只导航、不承载写动作」被**消息卡片（带裁决动作）**取代，落进会话节点（见「面板」节，07-14 已落地）；VerifyPanel / DiscussPanel 已删除。
- **边选中→就地裁决**：LiteGraph 原生「点链接中心点」路由到 `showLinkMenu`——覆写为自绘 `EdgeMenu.svelte`，锚定在点击处；ghost proposed＝接受 / 拒绝（要理由），其余＝正确 / 错误 / 存疑（note 必填走 prompt，取消＝放弃），外加拉入/移出讨论。仅 data_flow 出菜单（server 422 同一条线）。
- **跳转并选中原语**（S6 血缘链逐跳共用）：`GET /node/{id}` locator 拿父容器 → `navigateTo` → load 末尾 `selectNodes`+`centerOnNode` 兑现选中——跨下钻层级可达；后续消息卡片回归时直接复用。
- **escalate 就地「已处理」**：NodeInspector 在未解决 escalate note 上出按钮 → `POST /node/{id}/resolve`（可附说明）；卡片 RESOLVED 徽记与 S3 brief「只列 open」由此闭环。
- 人肉彩排的「人终裁」步骤走本件。

**S8 内嵌 agent 会话（插座子任务，静态末位）** 🔲（2026-07-09 grill 定）：前端起一个自由 agent 会话——agent 像在自己的 harness 里一样做任何事，界面是前端。技术路线＝**结构化事件流 + 原生会话面板**：用 harness 无头流式接口（opencode JSON / `claude -p --output-format stream-json`），渲染为对话气泡 + 工具调用卡片 + 流式输出；每 harness 一个薄展示适配器（只薄在展示层，调用与写权仍 harness 无关），先只接 opencode（免费模型现成）。写图仍只经 CLI/写权闸；会话干 task 时自己调 `run begin/end` 打卡（打卡即会话的图身份）。
**验收**：免费模型跑一个玩具 task，会话/diff/验收/落图全程前端可见，输出好坏不作数。
**与 §13.6 的边界**：不冲突——§13.6 禁的是「谈论图的无锚聊天」；这是**干活的会话**，锚天然是 task/run。
**同波配套**：锚定会话 UI（核对/讨论会话的就地化壳，替代 DiscussPanel；一批一场、写权闸机制不变——S8 清单第 4 件，见 assembly.md）。
**死端勿再试**：PTY 终端透传（xterm.js 嵌 TUI）作主路线——原型实测体验差，TUI 重绘/尺寸同步/输入法驯服成本无底；降级为逃生舱，sidecar 录制思想保留。

**美术皮肤**（原神童话风）：不作为静态验收条件，随前端波次择机。
