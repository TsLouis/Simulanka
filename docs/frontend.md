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
| `GET /graph?root` | 单容器视图载荷：nodes=root 的**直接孩子**（含 `child_count`；root 本人永不入 nodes，其名片在 `root_info`）、edges、**boundary_edges**（恰一端在视图内，contains 除外——root 端口连向孩子的边落在此，即子图输入/输出括号；**视图内节点连向自身后代的隧道边被滤除**——那是该孩子内部布线，投影在孩子自己的视图括号上，不该污染父视图）、external_nodes、ports、ancestors（面包屑）。无 depth 旋钮：视图永不混层（2026-07-12 定） |
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
- **跨层边界端口投影**（§12.4）：恰一端在视图内的边投影到虚拟 boundary 节点——纯渲染，虚拟节点永不进图。**root 自身端口=子图声明的 IO，常驻投影为左右括号**（左=in 朝内、右=out；model/module 层空括号也显示=「尚无声明 IO」）；跨界边落在括号槽位或按 (external, direction) 聚合的 boundary 节点上。**括号可连线（2026-07-14）**：槽位携带 root 真端口 id，画线走 POST /edge，kernel **隧道规则**放行（父.in→子.in、子.out→父.out，恰一层；validator 与 doctor 同一规则）。**importer 自动连括号（2026-07-15，彩排反馈#2）**：真图 data_flow 曾全是同层兄弟边、括号永远悬空、数据流读作断裂——现在 trace 补齐**垂直隧道边**（原始输入盖 root producer 印记→逐层 parent.in→child.in；每个 post-hook 在 producer 重印前记录 child.out→parent.out），下钻进任一容器，输入括号已连到第一个消费者、输出括号已连到产出节点。隧道边同样 `source=trace`，走 kernel 隧道规则落库。
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

### 人机写权框架（2026-07-16 grill 定稿；2026-07-17 场景 brainstorm 收口 🔲 执行件未施工）

- **挑战不覆写**：agent 遇不同意的人裁边，不被硬挡、也不就地改写——落 `challenge={理由, 证据引用, 时间}` 附在边上，边进**现有分歧队列**（S7 批次核对/就地裁决即人的复裁面），agent 随后照常干活（要绕开可在旁另立 proposed 结构，图是追加友好的）。「agent 可就地覆写人裁，有历史/diff/回滚兜底即可」已辩论否决：画布上没有「上次看后改了什么」的复核面，回滚只是存储层安全带，对不读事件日志的单人用户是心理安慰；且平局规则会从「人至上」反转为「后写者至上」。人裁翻案是稀有事件，为其付「一次人点击」换画布上金色语义的确定性，划算。
- **两层本体（方向已认；07-17 场景收口见下三条）**：图分**投影层**与**意图层**。投影层（导入结构、run 记录、evidence）＝外部原文的确定性投影，**转换器独占写**，人和 agent 皆只读——改图不改现实，手改无意义（baseline「上锁」由此免费）。意图层（研究原子、人画边、手加模块）＝自由写 + 现行 proposed/ops 闸 + 挑战规则（Claude Code 工作区模式）。**「真实」只由确定性转换器颁发**：手加的 conv 是意图节点（intended 态，ghost 视觉语言反向复用——agent 提议 ghost 等人批，人画意图 ghost 等重导入对账），agent 说「实现了」不作数，trace 出来才作数（＝测量归系统的直接推论）。意图↔投影的匹配算法是工程题，v1 可粗糙甚至手动勾销。VSCode 类比的正确读法：代码世界靠自由写+diff 复核+出处（git）而非权限系统，Simulanka 已移植（proposed 态=图原生未审 diff、事件日志=git log、checkpoint=revert）。
- **投影层只读＝三分法（2026-07-17 定）**：照片背后的现实隔多远，决定照片上能做什么。①文件/目录照片→**直通操作**（文件管理器模式）：图上改名/移动＝系统确定性执行真实文件操作+投影同步，一次事务、不经 agent。护栏：不做全量镜像（目录节点懒展开——双击下钻时读盘对账，带忽略清单）；画布拖拽永远不动真文件（真操作＝显式动作）；系统账本（run 目录、日志、`.simulanka/`）与代码文件 v1 不给直通（血缘指针/import 引用不可被手滑弄断；代码改名让 agent 连引用一起改）；文件进分组＝图上关系，不动真文件。此即 FileRegistry 当年「已知限制」预留的演进路（archive/design.md），用例今至。②代码结构照片（模型）→不可直改+**修订标记**（Word 修订模式，用户提议）：增＝幽灵节点、删＝删除线、改＝批注（带新值）——三者同一机制（intended 态的推广），转换器重导入时兑现；修订标记只对「背后有可改现实」的照片有意义。③历史照片（run/evidence）→**档案**：不可改不可修订（不能「打算」上周实验跑出别的数），异议走便签/挑战，或转换器重提取。**摆放（别名、分组、画布位置）永远自由**，不算改照片。层管「镜像保真」不管「内容可信」（agent 写的报告 ingest 成 file 节点没问题，内容可疑归 trust 染色）。「投影节点整节点级只读」已否——堵死别名/归组/圈选打包。
- **重导入＝就地重画（2026-07-17 定）**：现状 importer 重导入＝整棵新建（无 upsert），踩破「引用耐演化」承诺，必须改。定案：同 `fqn`＝同节点（ULID 身份延续，人贴的边/裁决/便签原地不动）；消失的部分→所贴意图物变**醒目失效态**，绝不静默删（与收集篮失效态同一视觉语言），处置权归人；新增部分＝新节点+幽灵对账兑现。**无仪式**：不弹窗不催复核；「attrs 变了提示复核既有裁决」→v2（机制现成＝进 S7 分歧队列）；「照片墙」（历次导入并存画布）已否——画布只有一张现在的图，历史归事件日志/checkpoint。
- **agent 无阻塞 + 真实必经转换器（2026-07-17 加固）**：agent 工作流＝改代码→自己跑 `import`→图自动更新+幽灵转正，全程无审批弹窗。**死端勿再试**：「agent 手填图真实 + 定期 reviewer 巡检一致性」——用户提出后被说服放弃：VSCode 类比的正确读法恰好反对它（编辑器显示＝系统从磁盘渲染出的真文件，不是 agent 往窗口里打字；同一份真相有两个写者才需要巡检员，写权收回给转换器则巡检岗位整个裁掉）；且撞「中模型翻译落图」死端，令投影层可信度降级为聊天记录水平。转换器不够强的事故形态＝图暂时不满（幽灵多挂一会儿/structure-only 降级），永远不是图说谎——唯一安全的失败方向；importer 补强＝彩排后回炉（原暂缓项恢复）。
- **节点锁（07-16 保留；07-17 细化＝连文件一起锁）**：人/agent 皆可上锁，锁节点＝锁整棵子树；人可解锁，agent 走 escalate 请求——类比 Claude Code 的操作审批门。执行点两处：图侧＝kernel apply_patch 查祖先链；文件侧＝锁住子树内登记过的文件路径**自动从 agent 任务契约 allowed_outputs 扣除**（契约 glob 检查现成）。「只锁图」已否＝装饰品（用户锁 baseline 真正要保护的是文件）；契约外裸跑 shell 不归锁管（越狱问题，同 CC 权限门管不住人自己开终端）。

## 交互定案：锚定式对话（§13.6，2026-07-08 定）

不做全局自由聊天窗。**对话必锚定画布选择集**（一至多个节点/边；无自然实体则锚到容器——experiment、计划目录、根）。消息**不进图**：留在会话树/sidecar 文件，图侧至多一个指向锚点的 note。
2026-07-10 更新：「DiscussPanel＝已落地特例」的过渡态结束——核对/讨论全面并入锚定原语，就地裁决部分进静态波次（S7），会话 UI 部分随 S8；「通用锚定对话优先级在静态缺口之后」对就地裁决不再成立。

### 引用原语（2026-07-16 grill 定稿 🔲 未施工）

彩排反馈「裁决=工作流不是地基，真地基=引用」的落地设计。心智模型＝Claude Code 的「@」——但 @ 展开成上下文由**系统**做（不是用户手拼），且引用的是图实体不是文件。

- **引用=值，不进图**：一个引用就是 `{nodes: [id…], edges: [id…]}`；id 是稳定 ULID 身份（非内容哈希）⇒ 引用天然耐图演化、天然跨下钻层级。「引用集=可命名图实体」已辩论否决——重蹈「消息进图」的过滤税老路，勿再走；真出现「复用命名集合」用例再议。
- **锚定戳＝server 端渲染**：前端只上行结构化 anchor，server 从图状态渲染 **card 级上下文块**（S5 卡片字段口径：id+type+name+关键 attrs；边=两端名+verdict+source）随消息喂 agent。必要性：graph-chat agent 无工具，戳里的信息就是它的全部锚点上下文。本质=brief 块的选择集切片，语言现成。现状前端手拼 `（锚定：type:name）` 人读字符串（App.svelte）退役。
- **收集篮＝通用交互暂存件**（用户定，类比手机「中转站/魔法胶囊」）：快捷键/右键把当前选中集入篮，跨层攒集，拖进 ChatDock 或一键「作为锚定」消费。不算单一用途面板——已在案的第二、三消费者：圈选打包子图（Reparent，待 grill）、未来裁决工作流的输入集。护栏：篮里只装实体引用 id（不装文件/文本，真用例撞上再扩）；消费路径不只拖拽（留点击路径）；被删实体显失效态、消费时剔除并提示；localStorage 持久化（刷新不清篮）；入口挂现有右键菜单，不立新按钮。
- **会话持久化（彩排硬伤修复）**：现状只存指针（`discussion.json`＝session_id/model/agent/batch），转录只活在 opencode 内部存储、前端纯内存一刷即失。定案：**Simulanka 自持转录文件**（每场一文件，逐条 `{role, text, anchor, applied/rejected, ts}`）+ GET 历史端点 + 前端挂载即恢复。理由：消息记录需要我们的结构（锚定引用、ops 落账），agent CLI 是可换件、历史不能陪葬。树结构＝文件级 fork 元数据（`parent_session`+fork 点），对齐既定「分枝 v1=新 session+祖先重放」，消息级不需要 parent 指针。
- **配套**：`GET /edge/{id}` locator（「跳转并选中」的边半边，现只有节点半边）；消息文本里的 `nod_`/`edg_` id 自动链接化→跳转并选中（ops 块已用 id 作 agent 侧通货，人侧补齐对称）。
- **裁决通道切法**：**落章=地基、流程=工作流**——人侧 verdict 端点 + kernel verdict op + 写权矩阵是「人亲手落章」的可信通道（外包给 agent 工作流=出处变代笔，撞「中模型翻译落图」死端），保留；EdgeMenu 裁决按钮=可拆薄皮，裁决工作流成熟后退役不心疼。

## 彩排二轮收官（2026-07-17，用户拍板通过＝静态验收关过）

随行修三件（4b99252）：**SSE 突发防卡**（CLI 连发 commit 逐条整刷卡死画布→250ms 尾部合并）；**registry 认领同名根目录**（plan ingest 建的 `research/` 无 fs_path 章，registry 不认→另立重复节点；名字兜底认领＋测试锁契约，彩排图已修）；**血缘丝线层**（fulfills/produces 等无端口语义边此前与 `contains` 一并不画→run→task 血缘整条隐形；adapter 收集、App 背景层手绘虚线+箭头+类型标注，`contains` 仍隐含于下钻）。

观察清单（未修，按性质挂账）：
- **人裁落章无画布可见记号**：边色=出处三色、可信五色只染节点体（设计如此），裁过的边与未裁的看不出差别——落章可见性=打磨项。
- **直通删除未施工 + 混合子树语义未定**：用户预期「删图目录=删磁盘目录」（写权框架直通操作的自然延伸），且 `research/` 下同住磁盘文件与纯图研究原子，删除等式不成立——语义随 Reparent 场 grill 定，执行随直通操作施工。
- **研究原子↔模型结构无自动纽带**（用户挂账后续打磨）；**隧道边修复未目验**（老图无 trace 边，重导入被停；单测覆盖）；**消息面/agent 会话未走**（S8 领地）；doctor 对共享目录未登记文件按 plan/brief 双报（小噪声）。

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
