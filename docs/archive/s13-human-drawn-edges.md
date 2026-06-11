# Archive — §13 人画连线 + agent 核对（完整推导）

> design.md §13 的**完整历史推导**：动机 → 多次 grill pivot → 证伪记录 → 逐项落地。
> 2026-06-08 从 design.md 移出归档——正文 §13 现为**浓缩的当前状态**，本文件保留全过程
> 与已否决路径的证据供回溯。**勿据此重走 dead-end**（已否决项见正文 §13.4）。

---

## 13. 人画连线 + agent 核对（2026-05-22 提出；§13.5.1/2 + §13.5.3 task B 已落地）

> **状态**：§13.1–§13.4 是 2026-05-22 的设计讨论存档（动机/洞见/约束），保留推导过程避免重复论证；落地方案与进度见 §13.5——§13.5.1（端口）、§13.5.2（连/拆边）、§13.5.3 task B（agent 提议 ghost 边）均已落地，§13.5.4/5 重设计 + 真 SAM2 命门 B 验过，§13.5.6（多输出端口=切片落在边 D4）2026-06-08 设计定稿、实现进行中；核对-讨论交互、命门 C（importer→图→propose live 串联）仍推迟。

### 13.1 触发动机：前端可视化审计暴露的三个顶层问题

2026-05-22 用前端肉眼验 DS_r（SAM2，`/tmp/sim_ds_r`），发现三件事，全是当前 import 策略的直接后果，不是 bug：

1. **3 个 traced model（image_encoder / memory_attention / sam_mask_decoder）之间 0 条边**。它们是 3 次独立 forward，各抓各的内部；顶层编排（谁喂谁）只存在于 `SAM2VideoPredictor.forward`，而顶层走 structure-only（`example_inputs=None`），从没被 trace → 三座孤岛。
2. **sam_prompt_encoder / memory_encoder 在 dataflow 视角“消失”**。它们只是 structure-only 顶层树里的 module 节点，被 manifest `skip`，没提升为有数据流的 sibling。
3. **端口零语义**：`_commit_io_ports` 给每个节点写死 1 个 `in` + 1 个 `out`，多输入全挤进一个口。

根因（#1+#2 同源）：策略是「完整结构导一次（每个 module 都是节点）+ 对手挑子集各跑独立 forward，commit 成独立 sibling」，于是**结构与数据流是两套不相交表示**，数据流是手挑出来的稀疏孤岛。

**固有天花板**：跨组件数据流藏在有状态的顶层 forward（视频循环 + memory bank）里，torch.export / fx 都抓不全（data-dependent 控制流 2026 仍未解）。「一张完全自动、完全连通的完整数据流图」不可达，硬追等于重造 torch.fx（已否决，见 §5 importer 设计）。

### 13.2 核心洞见：沿“确定性 vs 理解”劈开

> 机器只做它能 100% 确定的事（**结构 + 端口**）；需要“理解”的事（**连线**）交给**人画、agent 核对**。

三点理由：
- **绕开天花板而非硬撞**：不让机器去 trace 抓不到的顶层 forward；抓不到的连线由人补。
- **对齐使命**：Simulanka 的目的是让研究者**理解 baseline**，不是产出一张图。人自己把线画出来 = 被迫理解架构（生成效应，动手建构比读图记得牢）。一张完美自动图反而没达成这个目的。
- **agent 核对补上 tracer 的盲区**：tracer 抓不了的有状态顶层 forward，恰恰是 agent **读源码**最容易看懂的。人画线 + agent 读 `forward()` 核对，正好覆盖自动 trace 的死角。

### 13.3 三个必须先解决的约束（真问题，非捧场）

1. **“端口全自动 + 绝对准确”没那么免费。**
   - 结构那半已免费且成立：`named_modules()` + structure-only 顶层 + manifest lint → **每个模块都有节点、层次天然正确**，纯自动、零 AI。
   - 端口这半静态做不到“绝对准确”：一个模块输出几个张量、叫什么，**不跑 forward 不知道**（签名常是 `x` / `*args`，返回可能 tuple/dict）；而“不跑 forward”正是顶层模块的处境，又绕回 trace。
   - **解法：端口精度匹配要玩的层级**。深层（block 内部）不关心 → 顶层组件用**粗端口**（模块整体进/出，可靠拿到），只在真能跑 forward 处给**细端口**。并给端口标**置信度**：“真跑出来的（可信）” vs “签名推断的（未验证）”。
   - **唯一真风险**：端口标错 → 用户对着错棋盘画线、agent 拿错答案核对 → **自信地学错**。地基必须诚实标注可信度。

2. **agent 拿什么当标准答案？** 两个来源分工：
   - 能 trace 的子模块 → 用隐藏的自动 trace 当答案键（tracer 从“显示的图”降级为“判分依据”，既有工作不浪费）。
   - 不能 trace 的顶层 → agent **读 `forward()` 源码**推断（能处理控制流/状态，比 trace 强）。
   - *⚠️ 2026-05-24 pivot：此“答案键/判分”框架被 §13.5.3 的 verdict 模型取代——agent 提议为主线、trace 降为“只确认不否定”的附议者。下面这段的分工方向仍对，但谁主谁副反过来了。*

3. **突破只读红线**：现前端是只读 MVP（§12.7，编辑留 v2）。用户画 edge → 前端变写方（画线 → `apply_patch(CreateEdgeOp)`）。kernel 本就支持该 op，但把 v2 编辑能力提前了。配套：边加来源标记 `source: trace | user | agent`，三种线在图上要可区分。

### 13.4 用户拍板的判断（已决定，下方"默认从 0 画"已被 2026-05-24 pivot 取代）

- **值不值取决于目标**：若目标是“用户理解 baseline”（用户明示），手动成本就是价值，值得；若哪天只想要那张图，别玩游戏，直接让 agent 读源码画完最省。
- **UX 旋钮（松紧）**：用户从零画 → agent 判分（学得最狠、最费力）；或 agent 先读源码提一版 → 用户改（轻一些，改的过程也在理解）。

> **决定（2026-05-22）**：**「人从 0 画」为默认**。理由：本项目本就允许人与 agent 沟通，想让 agent 先画直接说一句即可；「agent 先提一版」推迟到后续 agent 工程慢慢做，甚至可做成一个 skill。先把一条路做透（lean），不做可切换的双模式。
>
> **⚠️ 已被取代（2026-05-24）**：用户行使了上面那句"想让 agent 先画直接说一句即可"的后门，把「agent 先提一版」从备选升级为**默认主线**。理由是经验证（见 §13.5.3 的 GitNexus 实测）：用户注意力集中在浅层框架，而浅层恰是 trace 盲区，确定性工具也搭不上——agent 提议是问题形状决定的必然。定稿见 §13.5.3。

### 13.5 落地方案与状态

#### 13.5.1 端口生成 —— **已落地**（importer，仅 `torch_export.py` + 测试，schema/kernel/registry 零改动）

地基是端口里那半确定、半不确定的部分。落法：

- **端口 `name` 是结构槽位、保持稳定**：主端口永远是 `in`/`out`；多输入/输出再加 `in1`/`in2`…、`out1`…。`data_flow` 边（registry 要求 out→in 端口）继续挂主 `.out`/`.in`，现有 trace 边、前端、选择器零破坏。
- **语义信息全进 `port.attrs`**（Port schema 已有 attrs，不动 schema）：
  - `confidence`：**两档**。`verified` = 一次真实 forward 里观测到的（arity / 形状可信）；`inferred` = 没跑到、只从 `forward()` 签名推断（拿到名字，但未验证）。这就是 §13.3.1 的「诚实标注可信度」——唯一真风险是端口标错让用户自信地学错，所以宁可标 inferred 也不假装 verified。
  - `label`：语义名。verified 来自 forward 实参 slot（位置参数取签名形参名、kwarg 取键名、输出 tuple 取下标 / dict 取键）；inferred 来自签名形参名。
  - `shape`：仅 verified 且该槽位是单张量时记观测形状，供画线时辨认（`[B,256,64,64]` vs `[B,77,768]`）。
- **抓取免费**：forward 那趟 hook 本就看得到 `args/kwargs`（pre-hook）和 `output`（post-hook）。trace 提前到建节点之前跑一次，顺带返回每个 fqn 的「首次观测 IO」；建端口时有观测用 verified、没观测（结构-only 顶层、未执行分支）退签名推断 inferred。每个 module 的端口要么整组 verified、要么整组 inferred（forward 同时给了进和出）。
- **边来源标记**：trace 边写 `attrs.source="trace"`，为 §13.5.2 的 `user` 边、§13.5.3 的 `agent` 边铺路；三种线前端要可区分。

#### 13.5.2 前端连线游戏交互 —— **已落地**（kernel `delete_edge` + `POST/DELETE /edge` + 前端连/拆 + 形状确认）

落地清单：kernel 加 `DeleteEdgeOp`（拒 `contains`，`Receipt.deleted_edges`）；server `POST /edge`（落 `source="user"` + `shape_check`，端口 id 直接当 selector）与 `DELETE /edge/{id}`，SSE `_affected` 已认 `delete_edge`；前端接管 LiteGraph `onConnectionsChange`（仅 INPUT 侧处理一次、`building` 标志屏蔽建图期自连），连线本地算 `shape_check`、`mismatch` 走 `window.confirm`（取消则撤销画布连线）、确认后 POST，拆线按链上 stash 的 edge id 走 DELETE，落库后靠 SSE 重载刷新。下方设计要点：

突破只读红线：在现有下钻视图里，逐层画 children 之间的边；写回走 `CreateEdgeOp(type=data_flow)`，边带 `attrs.source="user"`，端口级（port→port）精确连线。trace 边是粗的 module 粒度、user 边才是精确的，二者按 `attrs.source` 上色区分。

**边因此有了双重语义**：两端 verified 形状相等 = 纯数据流（原样传递）；相等之外（用户确认后仍连）= 这条边自带一个 reshape/transform。**不新增边类型**，语义全进 `attrs`。

**校验 = 画线当场的本地提示，不是硬拦**（决策依据见 §13.4 之外的讨论结论）：
- 形状可比是可靠的——同一次 forward、同一个 batch 跑出来的两个端口，维度本就同源；我曾错以为 batch 维会引入噪声，实则不会（噪声只存在于跨次运行）。
- 但**形状不等 ≠ 连错**：模块间常夹一个改变形状的函数操作（reshape/flatten/pool/`window_partition`），这正是 importer 专门捕捉的边。典型如 CNN 主干 `[B,512,7,7]` → flatten → 分类头 `[B,25088]`，是完全正确的边。所以硬拦会误杀；闷声放过又回到"没提示"。
- 落点：**连线的当下在前端本地算**（两端 `attrs.shape` 都在 payload 里），verified↔verified 给 `match`/`mismatch`，含 inferred 端口给 `unknown`。`mismatch` 弹确认（提示"中间若有 reshape 则正常，否则可能连错，仍要连？"），确认后才落库，边记 `attrs.shape_check` 与两端形状。
- **最终把关仍是人 + agent**（§13.5.3），系统只给提示。
- kernel 的 out→in 方向约束（`validate_edge`）是唯一的硬约束，已存在，免费拦住 in→in 这类结构错误。

**删边一并做**：画布上"连"和"拆"是同一交互的两半——只接管连、不接管拆，则用户拆掉一根线刷新又回来，是骗人的。故本步同时处理 connect→建边 / disconnect→删边。删边需 kernel 新增 `delete_edge` op（当前只有 create/update/rename，无任何删除语义）——这是本步唯一的 kernel 改动，先于前端交互落地并单测。

#### 13.5.3 agent 提议 + trace 附议 —— 设计定稿（2026-05-24，grill 讨论后 pivot）

> 本节是一轮 grill 式设计讨论的产物（Q1–Q7），取代了上午先写的"端口置信度当路由器 / 路 A 程序化判分为主"的初稿。核心转向：**agent 提议为主线，trace 退为附议**。

**为什么转向（GitNexus 实测，记此免得以后重试）**
转向前先验证了"能否用确定性静态工具承担浅层框架接线"。结论是**不能**，实测三连（在已索引的真实 SAM2 baseline `DS_r` 上）：
1. GitNexus schema 只有 `CALLS / ACCESSES / IMPORTS / EXTENDS / …`，**没有数据流边**——给不出"A 的输出流进 B"。
2. 顶层**方法**编排抓得准（`forward → forward_image → track_step → _track_step → _encode_memory_in_output`）。
3. 但 `image_encoder / memory_attention / sam_mask_decoder / sam_prompt_encoder` 这些**子模块全仓 0 次当被调方**——`self.image_encoder(x)` 是 `nn.Module.__call__` 间接调用，静态分析解析不出。而这正是要画进图的边。

→ 加上自建 torch-aware AST def-use 也会**恰好在 SAM2 变复杂处（视频循环 / 条件 / 跨 pass）崩**、且仍需 agent 兜底。**浅层框架躲不开 agent，是问题形状决定的，不是没选好工具。** §13.2"顶层要靠语义阅读"由此被三方坐实。

**新架构（主线 = agent 提议，附议 = trace）**
- import 后，agent **读顶层 `forward()` 源码**，产出**保守的 ghost 草稿框架**（灰虚线，不落成实边，不阻塞用户）。
- 用户审：选中一个 port 时浮出该处的 ghost 建议，**同意就连上、画得不一样就是分歧**。
- 点"核对"批量提交分歧 → agent 与用户**讨论解决**（这一步本身就是学习——为自己的判断辩护或被说服）。
- **trace 退为深层 verified 区的确定性附议者**，只盖 `correct`。

**verdict 模型（Q1–Q3 定稿）**：单标量进 `edge.attrs`（经 `_edge_dict` 直达前端，schema/kernel 零改动）：
- `verdict ∈ {unconfirmed, correct, wrong, uncertain, disputed}`
- `verdict_by ∈ {trace, agent}`
- `verdict_note`：理由（`disputed` 时**必须写清**）

状态机：
- 画下 / trace 没命中 → `unconfirmed`（**显式存**，不靠"字段缺失"表达；agent 据此找待裁的边）。
- trace 命中（node 对级，trace 边无 port 精度）→ `correct`（`by=trace`）。
- agent 裁 `unconfirmed` → `correct` / `wrong` / `uncertain`（`by=agent`）。
- agent 对一条 trace-`correct` **提异议** → `disputed`（`by=agent`，理由进 note）。

两条铁律：
1. **trace 不对称：只确认、绝不否定。** trace（`TorchDispatchMode` + producer-set）只看 tensor 谱系，对 Python 标量/列表、有状态属性（memory bank）、非张量返回、控制流**全盲**——即使同一 pass 内也会漏真实边。所以 trace 边在 → `correct` 可靠；trace 边不在 ≠ 错（可能只是没看见）。**唯一灾难是"自信地学错"（§13.3.1），假 `wrong` 正是它**，故 trace 无权说 `wrong`，只有读源码的 agent 有。
2. **agent 可对 trace 提异议（`disputed`）。** 永远无法保证不犯错，能在工作中发现并改正才是关键；`disputed` = "两台仪器打架、快来人看"，是最该被看见的状态，不被静默覆盖。

**agent 性格（Q6 定稿，行为契约）**：**少而准**。
- 只画能从源码**直接指出依据**的边（附上那行 `feats = self.image_encoder(x); … self.memory_attention(feats)`），**每条 ghost 必带源码出处**。
- 凡要靠猜控制流/状态的，**不画，只标缺口**"agent 拿不准，你来定"——把"宁可漏不可错"的纪律从 trace 复制到 agent。
- 好处：生成效应保住（难的边还是人画）、agent 不自信断言错边、接受 ghost 是学一个被指认的事实而非给猜测盖章。
- *prompt 怎么写、出处怎么格式化、agent 怎么自评——属实现细节，留给 agent 工程阶段（见 [[project-deferred-agent-work]]，§13.4 早有此意）。这里只锁行为契约。*

**落地状态（Q7：B = 最小端到端尝鲜 —— ✅ 已落地 2026-05-24）**
- ✅ **地基**：importer 给 module/model 节点加**源码定位**（`class_module` + `source_file`），用 `inspect.getsourcefile`，C 实现/无源码的模块 `source_file` 缺省。agent 读 `forward()` 的前提，与 prompt 细节解耦。（`importer/torch_export.py::_source_location`）
- ✅ **ghost 生成**：新模块 `simulanka/propose.py`（**不**走 `agent/wrapper.py`——那层只抓 workspace diff、不解析输出；这里要把回复解析成边）。流程：`resolve_node` → ast 从 `source_file` 抠出 `forward` 源码（无需 import 模型）→ 列直接子模块当合法端点词表 → opencode 单发 → 解析 JSON → 用现成 `CreateEdgeOp(attrs={source:"agent",status:"proposed",verdict:"unconfirmed",citation})` 落边。**无需新 kernel op。** 两条纪律落在代码里而非 prompt：只连词表内的子模块、**只落带 `citation` 的边**（无出处=猜测=skip，少而准）。CLI：`simulanka propose <model>`。
- ⚠️ **opencode 调用坑**：`opencode run` 不带 `--print-logs` 在非 TTY 管道里会**永久挂起**（渲 TUI spinner）。必须加 `--print-logs`——日志走 stderr，stdout 即纯回复。
- ✅ **前端 ghost 渲染**：`status="proposed"` 的边渲**灰虚线**（`GHOST_COLOR` + `App.svelte` 实例级包 `renderLink` 加 `setLineDash`，LiteGraph 无 per-link 虚线），与确认后的实线 agent 紫区分。
- ✅ **命门验证通过**：本地合成 TinySAM（`image_encoder→(flatten)→memory_attention(+state buffer)→mask_decoder`，含 trace 盲的 functional glue + 状态）。免费模型 `deepseek-v4-flash-free` 准确吐出两条边、各带源码行、零幻觉模块、零 skip。证实"浅层框架接线靠 agent 读源码"可行。
- **明确推迟**：agent 工程（prompt/出处/自评）、核对-讨论交互细节、edge-attr 更新 op（重核/异议回写时再加）、`/verify` 批量。
- ⚠️ **真实 SAM2 `DS_r` 实测已做（2026-05-26），证伪了本节的「读 `forward()`」机制 → 见 §13.5.4。** 本节 spike 的命门只覆盖了「forward 本地定义、数据流全在 forward 内」的简单模型；SAM2 这类 forward 继承/编排在非 forward 方法的模型族不成立。

**已知小问题（high-effort code review 标记，spike 可接受）—— #1–#5 均已修**
- **解析鲁棒性两处已修**（2026-05-24 review）：① `parse_response` 旧版 `find('[')…rfind(']')` 遇 citation 里的 `]`（`x[0]`）或 prose 括号会静默吞边 → 改成 string-aware 平衡括号扫描、逐候选取第一个能解出真实边的；② CLI typo 模型名时 `resolve_node` 抛 `ResolveError` 漏过 CLI 的 `except ProposeError` → 现在 `propose_edges` 把它包成 `ProposeError`。
- **#3 已修**（2026-05-26）：前端 ghost 虚线——`App.svelte` 包 `renderLink` 的 `setLineDash([6,4])`→draw→`setLineDash([])` 改成 try/finally 包 draw，原 `renderLink` 抛异常时也保证 reset，虚线不再泄漏到本帧后续连线。
- **#4 已修**（2026-05-26）：重复跑 `simulanka propose` 不再累积重复 ghost 边——`propose_edges` 建边前先扫图，按 `(source_id, target_id)`（= 拥有端口的两节点，见 `apply.py`）过滤已存在的 `source=agent` `data_flow` 边；kernel 仍不去重 data_flow，dedup 落在 propose 这层。重提→更新的语义留到 edge-attr 更新 op 落地时再做。
- **#5 已修**（2026-05-26）：`_extract_forward_source` 不再盲取第一个同名 class——优先取**顶层** class（`nn.Module` 必在模块顶层），同名重定义取**最后一个**（与 Python 名字绑定一致），无顶层匹配才回退到首个嵌套定义；同名嵌套 helper 不再喂错 `forward`。

#### 13.5.4 真实 DS_r 实测 → 入口方法重设计（2026-05-26，grill 后定稿）

> §13.5.3 的 spike 在合成 TinyMLP/TinySAM 上过了命门，但真实 SAM2（DS_r baseline）实测把它的核心假设「agent 读顶层 model 的 `forward()`」打穿了。本节记录证伪 + 重设计；**取代** §13.5.3 的「读 forward」机制（验证/出处/少而准/verdict 等其余决策不变）。

**实测发现（源码级，未建模；DS_r 已备完整 `simulanka_builds/manifest.yaml`）**——两层都崩，合成玩具结构上抓不到（它们 `forward` 本地定义、数据流全在 `forward` 内）：
1. **extractor 非 MRO-aware**：`SAM2VideoPredictor`（manifest 顶层模型）自己文件里**不定义 `forward`**（自有方法是 `init_state`/`add_new_points_or_box`/`propagate_in_video`…），`forward` 继承自**另一文件**的 `SAM2Base` → `_extract_forward_source` 返回 `None` → propose 直接抛 `ProposeError("no forward found")`，根本到不了 agent。
2. **`forward` 是错入口**：即便 MRO 解析到，`SAM2Base.forward` 只是 `raise NotImplementedError("用 SAM2VideoPredictor 的对应方法")` 桩。真正编排在 `track_step → _track_step → {_prepare_memory_conditioned_features(→memory_attention), _forward_sam_heads(→sam_mask_decoder/sam_prompt_encoder/obj_ptr_proj), _use_mask_as_output}` + `forward_image(→image_encoder)` + `_encode_new_memory(→memory_encoder)`：8 个子模块各调一次，**摊在 SAM2Base 的 5 个私有方法、约 600 行、跨两文件**。**子模块之间的边**（image_encoder→memory_attention→sam_mask_decoder）不在任何单一方法里——是 `track_step` 用返回值 + 每帧状态（memory bank）串起来的。
   - 旁证：GitNexus 当初**抓得准方法调用图**（`track_step→_track_step→…`，§13.5.3 finding #2），抓不到的恰是 `self.<submodule>(...)` 间接调用与张量数据流。这条「静态拿方法图、语义读数据流」的天然分工，下面被用上。

**重设计决策（grill 2026-05-26）**：
1. **agent 提议覆盖 smeared 顶层**：读多深是 **agent 自己决定**（越深越好），深度/导航策略推迟到 agent 工程。覆盖 spike 的隐含「只读 forward」。
2. **证据局部性 = 分级出处**（verdict/values 决策）：单跳同方法引用 vs 跨方法 + 跨状态引用**不是同等可信**——深/跨态的 cited 边天生更可疑，`核对` 按局部性加权。理由：§13.3.1 唯一灾难是「自信学错」，而**带似是而非 citation 的错边比没 citation 的错边更危险**（SAM2 实例：`memory_encoder→memory_attention` 是真边但靠跨帧 memory bank 状态中介，agent 能就 `self.memory_attention(..., memory=...)` 给出看似直连的出处）。少而准的 cite-or-skip 挡不住这种——agent 确实能 cite，只是跨了状态边界。**verdict 枚举不变**，`evidence_locality`（如 `in_method | cross_method | cross_state`）是 `citation` 旁的附加 attr。
3. **propose 改形（工程）**：从「AST 抠 `forward` 字符串 → 单发」改为「把 agent 指向 model 类 + 仓库，让它按需导航到任意深度」。一举化解 MRO/跨文件 + 错入口两问题（agent 自己跨文件读、自己找真编排）。**§13.5.3 的 parse / 校验 / dedup（含 #4）全保留**；`_extract_forward_source`（#5 修过的）降级为简单模型的提示/fallback。
4. **局部性谁算（工程）**：propose 从 citation 指向的位置推**结构跨度**（同方法 vs 跨方法，可核查）；**跨状态由 agent 显式标注**（只有它读了码）。
5. **推迟到 agent 工程**：导航/prompt 策略；验证 opencode `run` 能在 CWD=仓库时读文件导航；可选「静态方法调用图当导航辅助」（GitNexus 唯一抓准的东西）。
6. **推迟到将来**：消费 `evidence_locality` 的 `核对` 交互。

**未做 live import**：本地 `.venv` 缺 numpy/hydra/omegaconf/iopath；propose 结局已被源码实测 + 代码逻辑证实，无需建模。importer 侧（`simulanka import baseline DS_r --check` 在真 SAM2 上）**尚未实跑验证**，待补。

#### 13.5.5 命门 B 实测验证（2026-05-27，shim 修复后 opencode 真跑）

§13.5.4 的重设计此前只纸面定稿 + 源码推断；本节是它的真跑验证。先解掉一个环境前置——远端 shim 把 `node` 也转发，导致挂载目录下本地 node 基础设施（hook/MCP）全被发往远端而死，已修（详见全局 `~/.claude/CLAUDE.md`）——再用 opencode 1.15.7 + 免费 `deepseek-v4-flash-free` 跑 propose 的新形态。

**Setup**：本地复制 DS_r 的 `sam2/` 源码到 `/tmp`（隔离 sshfs 延迟与 shim 噪声，干净测「模型能力」而非环境）；prompt = 指向 `SAM2VideoPredictor` 类 + 8 个直接子模块词表，要求 cite-or-skip + 给每条边标 `evidence_locality`（in_method/cross_method/cross_state）。这正是决策 #3「指向 model 类 + 仓库自由导航」的形态。

**命门 B 通过（n=2 一致）**：
- **导航过桩**：完全跳过 line-199 的 `forward` 桩，自己找到 `track_step`/`_prepare_memory_conditioned_features`/`_forward_sam_heads` 里的真编排——这正是 §13.5.3「读 forward」机制做不到、§13.5.4 重设计要解的。
- **产出准**：10 条顶层边，引用逐行核对全部属实，零幻觉模块。
- **cross_state 命门边正确**：`memory_encoder → memory_attention`（经跨帧 memory bank）两轮都标 `cross_state`、没伪装成直连——§13.5.4 决策 #2 最怕的「带似是而非 citation 的自信学错」**没发生**。证实 `evidence_locality` 可由免费模型准确产出。
- **一致性**：两次独立运行边集 + locality 标签完全一致（第三次因 opencode 权限门挂起作废，见下）。

**但机制不穷尽——人核对当场生效**：用户凭领域知识两轮逼出模型漏的真边 `image_encoder → sam_mask_decoder` 直边——① 浅层高分辨率特征 `current_vision_feats[:-1]` → `high_res_features` → decoder 做掩码上采样细化（`_track_step` 806-809/844，**无条件每帧走**）；② `no_mem_embed` 首帧分支（713）。模型只留了「深层 `[-1]` → memory_attention → decoder 经记忆」那条。漏点集中在**控制流分支 + 多尺度直连**；模型选择 omit 而非 fabricate，"宁可漏不可错"纪律守住。**这实时演示了「agent 提议、人处置」的价值——验证通过 = 机制产出准确诚实的边，≠ 穷尽。**

**🔑 表示层发现（reshape 前要定，比 prompt/导航更靠地基）**：image_encoder 的多尺度输出（深层 `[-1]` → memory_attention、浅层 `[:-1]` → decoder）意味着模块有**多个不同输出**。propose 现在把边端点写成单一 `模块.out`（`f"{child}.out"`），会把 `image_encoder.out→memory_attention` 与 `image_encoder.out→decoder` 从同一 `.out` 引出、抹平分流语义。→ 边端点须落到模块的**具体输出端口**，接 §13.5.1 的多输出端口（`out1`/`out2`…）。

**两个 opencode harness 坑（操作层，留 agent 工程）**：
1. **`opencode run` 非交互下会卡在权限门**：第三次运行随机走了更 agentic 的路（派 `@explore` subagent + `bash`），触到 opencode `external_directory=ask` 权限门，非 TTY 下无人批准 → 永久挂起。real propose 必须把 agent **限制在仓库目录 + 预置权限**，否则死锁（§13.5.3 `--print-logs` 坑的同类）。
2. **导航策略 run 间随机**：2/3 在进程内读文件、1/3 派 subagent + shell 出去越界。佐证决策 #5「导航/prompt 策略推迟 agent 工程」。

**决策 #5 进度**：其中「验证 opencode run 能在 CWD=仓库时读文件导航」一项今天**已验通过**；其余导航/prompt 策略仍按原计划推迟。

**仍未做**：importer 侧 live import（命门 C，`simulanka import baseline DS_r --check` 在真 SAM2 上）仍未实跑——本次 propose 用的是**手工提供的子模块词表**，非从导入图取，importer→图→propose 的端到端串联待补。

#### 13.5.6 多输出端口 —— slice 级分流落在边上（D4，2026-06-08 grill 定稿）

> §13.5.5 末尾的 🔑「表示层发现」的落地设计。先纠正 §13.5.5 自身一个没核到底的假设，再定表示层方案。本节是设计 + 今日实现边界；live 验证随 命门 C。

**纠正 §13.5.5 的隐含假设**：finding 说「边端点落到 `out1`/`out2` 就能分开 image_encoder 的两路分流」。核 `_output_specs` 真实行为 + SAM2 返回结构后**不成立**：image_encoder 的 `forward` 返回 `dict{vision_features, vision_pos_enc, backbone_fpn}`，**多尺度分流发生在 `backbone_fpn` 这个 list 内部**（深层 `[-1]`→memory_attention、浅层 `[:-1]`→sam_mask_decoder 的 high-res skip）。而 `_has_tensor` 递归 → 整个 list collapse 成**一个**结构端口 `out2`。两个消费者都连同一 `out2`，「落到 outN」**对它自己的动机例子无效**。→ 真问题不是「propose 落到 outN」（那是 importer 早做好的、对干净 tuple/dict 返回有效），而是 **slice 级分流（`[-1]` vs `[:-1]`）这种「机器看不出、要读码才懂」的区分该不该、怎么表示**——直接踩在 §13.2「确定性 vs 理解」那条线上。

**当前地基（核过的 ground truth）**：① importer 的 `_output_specs`+`_commit_ports` 已把 tuple/list/dict 返回拆成结构端口 `out`/`out1`/`out2`（§13.5.1），list 值整体 collapse 成一个端口；② 前端 `litegraph-adapter.ts` 已泛型渲染所有端口，outN 自动出槽、带 label/shape/confidence；③ 唯一代码缺口：`propose.py` 硬编码 `source=f"{child}.out"`，`GhostEdge` 协议 `{src,dst,citation}` 无输出端口维度。

**Decision A（产品判断，用户拍板）**：要在图上**一眼看见两路**——image_encoder 流出的是两个不同的东西，而非两条无差别边。理由：高分辨率 skip 绕过 memory 直供 decoder 是 SAM2 出细掩码的**承重结构**，人画线游戏的目的就是看见这种架构；连两条无差别边等于视觉上漏掉它。

**Decision B：slice 级区分落在「边」上（D4），importer/schema 都不动。** 三设计逐个验：
- **D1（importer 递归把 list 拆成 `out2_0`/`out2_1`…）——原则性否决。** ① 人要的 `[:-1]` 是**切片/组**（多元素），indexed 子端口是单个，`[:-1]` 得从多端口引一条边，与 data_flow「1 端口→1 端口」不匹配；② **违反 §13.2 线**：机器 100% 确定的只是「backbone_fpn 是一个 list」，「按 `[:-1]`/`[-1]` 切成两个有意义输出」是**理解**，让 importer 做这切分=机器替人做理解判断。
- **D3（agent 提议时在源模块现造语义端口）——否决。** 让 agent 造**端口**=闯进结构层（§13 里结构归机器）；还得新引一档 confidence；agent 端口与 importer 结构端口 `out2` 的父/兄弟/替换关系一团乱。
- **D4（切片信息作边 attr，边仍连结构端口）——选定。** backbone_fpn 保持一个结构端口（确定的结构事实），「哪个切片流去哪」这个**理解**落在 agent/人画的**边**上——正落在 §13.2 给「理解」划的那侧。边加 `attrs.output_slice`（`[-1]`/`[:-1]`），前端按它给边上标签 + 视觉区分。零 schema、零 importer 改动。
  - **D4 顺手化解上一轮自己的告诫**：§13.5.4/前文有「得先跑出真实图才能定 outN 形状，盲做会过设计」。D1/D3 正是在赌结构端口的确切形状（几个口、怎么拆），没 命门 C 真实图就是盲赌；**D4 不赌**——切片在边上，无论 image_encoder 真实导出几个结构端口都成立。选 D4 既贴 §13 线、又**不必等命门 C 即可动手**。把不确定的东西放到理解层（边），本就该独立于结构层的未知。
  - **D4 可逆**：哪天某条切片边被反复确认、确实想升成真端口（D3），edge attr 已指明在哪个模块铸哪个口——D4→D3 前向兼容，不是死胡同。先 lean。

**Decision C（agent 协议）+ D（可信度）——落在现有机制，零新概念。**
- agent 报告它 cite 的**输出表达式**（如 `backbone_fpn[-1]`）；propose 按端口 `attrs.label`（=dict key / 形参名）把它**映射**到结构端口 + 把切片写进 `output_slice`；映射不到则退回粗 `.out`。`GhostEdge` 加两个可选字段（输出端口/切片）。
- 切片声明的**可信度不需要新东西**：它是 `citation`/`evidence_locality` 旁的又一条证据，挂在边的 `verdict` 体系下，人核对时一并裁；§13.5.4 #2 最怕的「带似是而非 citation 的自信学错」对切片声明同受 `evidence_locality` 加权，已覆盖。

**今日实现边界（诚实切分）**：
- **今天闭环**（不需命门 C、不烧 opencode）：① 本节设计；② 前端——同一端口引出的多条边按 `output_slice` 上标签、视觉可分（用「前端对着 fixture 写」那套）；③ propose 的端点映射逻辑 + `output_slice` 写入，用注入式 runner + 合成图**单测**。三绿。
- **随命门 C（Codex）**：真 opencode 是否真吐切片、真导入 SAM2 端口是否带 propose 映射所依赖的 label——live 验证挂在命门 C 上，今天不假装关掉。

#### 13.6 核对-讨论交互 —— 设计定稿（2026-06-11 grill，Q1–Q4 + 工程裁定）

> 浓缩定稿在 design.md §13.6；本节存推导与证据，含一处被 spike 推翻的预设。

**起点（现状核查）**：propose.py 的 ghost 已直接经 `apply_patch_now` 落库、前端灰虚线已通；§13.5.3 锁了流程骨架（选 port 浮 ghost / 同意即连 / 不同即分歧 / 「核对」批量提交 → 讨论）；当年明确推迟的「核对-讨论交互细节、edge-attr 更新 op、/verify 批量」就是本场要裁的。kernel 现状：`UpdateAttrsOp` 只收 node selector；存储层**无任何 undo/snapshot**（纯 JSON + 追加 event log，sqlite 可重建）。

**Q1 讨论形态 —— 用户裁：实时交互必要（推荐的「异步回合制」被否）**。用户明确：实时交互是必要的，harness 交互化问题交给 Codex 线解决。
- **spike 把可行性坐实、且推翻了「实时=攻 TTY」的预设**：`opencode serve`（headless server）与 `opencode run -s <session-id> --format json`（**非交互续接同一会话**）都存在。所以实时聊天 = 共享 session id 的非交互单发序列，每一发都是 §13.5.3 已验证可靠的调用形态；TTY 死锁/权限门坑根本不在路径上。Codex 的活从「解决交互式问题」缩为「session 续聊 + JSON 解析 + prompt」。
- 当初推荐异步回合制的理由（非交互坑、复用 propose 形状）被 spike 化解大半——记此供后人：**「opencode 非交互坑」只挡 TUI 交互，不挡 session 续聊**。

**Q2 讨论单位 —— 一批一场会话（用户采纳推荐）**。整批分歧进同一会话：一个架构性误解（如漏看某分支）常同时解释 3–5 条分歧，agent 须有全局上下文才能发现共同根因，也省每条边重复导航源码的成本。结论逐条落到各自边上，聊完才算批完。否决「一边一线程」：跨边共同根因发现不了 + N 次独立导航成本。

**Q3 写权 —— 用户提出「真实 vs 意图」两域，吸收为写者维度（不立分支机制）**。用户：人和 agent 在「意图」上可宽松写（服务人机对齐），「真实情况」只反映当前代码；并要求 git 自动化撤回。
- **机制修正（lean 纪律）**：两域不是新分支/新实体——现有 attrs 已表达它，缺的只是把**写权矩阵**讲明白：
  - 真实域 = importer 结构+端口、trace verdict、shape_check、port confidence → **只有机器写**，人/agent 不能伪造（不能手标 trace-correct）。
  - 意图域 = ghost、agent verdict/note、人画的边、人的裁决、讨论 → 人+agent 写，内部分层：agent 实时改**自己的层**（自己的 verdict/note、撤回自己未被接受的 ghost、新提 ghost）；实边连/拆/接受、推翻人的判断**只能人点**。
  - 关键推论：**人画的实边也在意图域**——人的当前理解、非被验证事实，这正是它需要被核对的原因。
- **agent 不拿写工具**：会话回复嵌结构化 op 块 → 服务端解析 → 按矩阵过滤 → `apply_patch`。kernel 唯一写者不破；op 块协议 = Claude/Codex 接缝契约。
- **git 自动化（必要兜底，非锦上添花）**：agent 拿到实时写权 + 存储层零 undo ⇒ 必须有恢复点。`.simulanka/` 内嵌**独立 git 仓**（嵌在 baseline 代码仓里会污染用户 code history，故隔离；indexes/logs/cache 入 .gitignore），每次 kernel commit 自动 git commit、讨论每轮起点打 tag，恢复 = checkout + index rebuild。

**Q4 生成效应 —— 分歧必填短理由（用户采纳推荐）**。拒 ghost / 坚持己见提交前必须写一句「我认为…因为…」：① 「为自己的判断辩护」即本项目的学习时刻（与 §13.5.3 disputed-必写-note 铁律对称，人不豁免）；② 给 agent 可反驳的靶子，讨论从「针对你的理由」开场而非从零猜。结论蒸馏回该边 `verdict_note`；全文 transcript 留 opencode session（可 export），不进图——「学习笔记」类功能是 scope creep，不做。

**工程裁定（Claude 定，随实现可调）**：
- **分歧集**（机械推导自 §13.5.3 verdict 状态机）：① 人拒的 ghost；② 核对 pass 被裁 wrong/uncertain 的人画边；③ disputed。人可手动拉任意边进讨论。
- **拒 ghost ≠ 删边**：`verdict=wrong, verdict_by=user（枚举新增）, note=理由`，status 仍 proposed 进队列；讨论后人确认拒绝才 DELETE。
- **kernel 增量**：`UpdateAttrsOp.target` 扩到 edge selector（= §13.5.3 推迟的那个 op，到点）；`verdict_by` 增 `user`。均按分工规矩①在本场设计讨论过审。
- **流程**：点「核对」一键两相 —— agent 核对 pass（裁 unconfirmed，写 verdict）→ 分歧集非空则自动开讨论会话。
- **切缝**：Claude 先行到「分歧集就绪 + 面板」（kernel op、server 端点、port 浮 ghost、拒绝理由表单、面板、git checkpoint），不被 Codex harness 阻塞。
