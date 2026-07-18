# 图汇编语言（转换层）

> 分篇之二（入口见 `overview.md`）。统一抽象：**文档、模型、执行现场都是外部原文，图是它们的可检查投影**。
> 每种转换都是确定性工具——同样的原文必得同样的图。人和任何模型只读写原文，不直接操作图。
> 标注 🔲 的小节是已定稿、未施工的规格（子任务 S8；编号见 overview 施工清单）。

## 铭章约定（attrs 语义词表）

转换层落图时盖的章，前端与可信度分级都只读这些：

| attr | 取值 | 含义 |
| --- | --- | --- |
| `source` | user / agent / analyst / trace / machine | 这条事实是谁主张的 |
| `status` | proposed / accepted（边）；planned / done（experiment）；open / supported / refuted（claim）；open / resolved（escalate note，2026-07-10） | 生命周期 |
| `verdict` | unconfirmed / correct / wrong / uncertain / disputed | 裁决（§13.2 五词） |
| `verdict_by` | user / agent / trace | 谁裁的；**user 最高，agent 覆盖不了** |
| `citation` / `note` / `verdict_note` | 文本 | 引证与理由 |
| `plan_file` / `plan_lid` / `reviewed_in` | 路径 / lid | 文档出处深链 + 强验记录 |

## 文档 → 图：plan 块 + `simulanka plan ingest` ✅

分析者的计划文件 = 自由 prose + **恰好一个** ```` ```simulanka-plan ```` 围栏 JSON 块（0 或多个 = 拒）。

```jsonc
{
  "distill": {   // 审旧账：引用已落图实体；new_claims 是唯一铸造例外
    "new_claims": [{"lid": "c1", "body": "...", "status": "open|supported|refuted"}],
    "edges":  [{"type": "supports|contradicts", "source": "<evidence id>",
                "target": "<claim|hypothesis id> | c1", "note": "..."}],
    "claims": [{"id": "<claim id>", "status": "...", "note": "..."}],
    "hypotheses": [{"id": "<hypothesis id>", "verdict": "...", "note": "..."}]
  },
  "plan": {      // 开新篇：lid = 块内本地 id
    "questions":   [{"lid": "q1", "body": "..."}],
    "hypotheses":  [{"lid": "h1", "body": "...", "addresses": "q1 | <graph id>"}],
    "experiments": [{"lid": "e1", "goal": "...", "tests": "h1 | <graph id>",
                     "tasks": [{"lid": "t1",  // 可省，按序派生 t1/t2/…（显式 lid 先占名）
                                "goal": "...", "allowed_outputs": [], "acceptance": "...",
                                "budget_time_seconds": null}]}]
  },
  "escalate": null   // 或 {"reason": "..."}：分析者叫停，操作员见之必停
}
```

规则（全部实测于 `tests/test_plan_ingest.py`）：

- distill / plan 两段**均可省，全空块拒**。schema 严格（未知字段拒）。
- lid：字母开头、字母/数字/下划线、≤64、块内全局唯一；`escalate` 为保留 lid。
- 引用：图 id 直接 resolve 并做类型校验（错误定位到分析者级路径，如 `distill.claims[0]: …`）；lid 只在块内引用，落图走 kernel 的 `@ref` 机制。
- **单 PatchIntent 原子落地**：部分失败 = 整体拒 + 零残留（归档副本在 patch 成功后才写盘），改文件重发即可。
- 落图布局：`research/` 下每计划一个 directory 节点（名 = 文件 stem），新原子落其中、**名 = lid**；task 落为一等 `task` 节点（父 = 其 experiment，attrs = 契约字段平铺）。
- 铭章：新实体 `source="analyst"` + `plan_file` + `plan_lid`；distill 改写同时在目标实体盖 `reviewed_in=<plan_file>`（可信级 `reviewed` 的判据）；intent `actor="analyst"`（工具只是笔）。
- escalate 非空 → 建 `note` 节点（`kind=escalate`），CLI 打印 `ESCALATE:`。
- 归档：文件在 `research/` 外则复制为 `research/plan-<名>.md`；已在内则就地登记（要求 `plan-` 前缀）。同一路径重复 ingest = 拒（修订流 v2 再议）。
- **表达力演进**：目标对齐研究原子全词表；v1 已知缺口（分析者铸 evidence、已有实体间补 addresses/tests 边、自由 note）**不预补**，真实轮次首撞驱动。

## 图 → 文档：brief 块 + `brief export`（S3）✅

分析者开场输入，ingest 的逆操作（`brief.py`，实测于 `tests/test_brief_export.py`）。输出 markdown：prose 概览（计数 + ESCALATE 醒目列出）+ 一个 ```` ```simulanka-brief ```` JSON 块，与 plan 块**镜像对偶——简报给出的图 id 就是下轮 distill 段可直接引用的 id**。

- 块内容（全部确定性、按 id 排序、无时间戳，同图态必同字节输出）：open 的 question/hypothesis/claim；近期 run（id、task goal、contract_check、duration、**evidence 条目含节点 id + metrics**——没有 evidence id，下轮 supports/contradicts 无的放矢）；未处理的 escalate note；§13 分歧集条数（一行）；预算消耗小计。
- open 判据（v1，查询时判）：claim = `status=="open"`；hypothesis = 无 `verdict`；question = 全列。「近期 run」= 非 `done` experiment 名下全部 run（experiment 翻 done 是操作员机械流）。
- `--out <名>` 或 stdout；写入走 FileRegistry `brief` kind（`research/brief-<名>.md`，路径归策略不归用户），`actor="system"`。
- **escalate 闭环（2026-07-10 定）✅**：note 生而 `status=open`；解除＝人的显式动作（CLI `note resolve <id> [--note 理由]`，`actor=user`，理由记 `resolve_note`；已 resolve 再 resolve = 拒；前端就地「已处理」按钮随前端波次接同一原语）；brief 只列 open。「下轮 ingest 自动消音」已否决——叫停信号只能由人解除，与人裁至上同源。
- 无 task 的 run（`run exec` 裸跑）：task goal / contract_check 字段缺省即空，不造假。
- 分歧集条数与 server `/disagreements` 同一计算（共享模块 `disagreements.py`，不写第二份）；预算小计＝每个非 done experiment 一行，Σrun duration 对 Σtask budget（无声明记 null 不记 0）。

## 对话 → 图：ops 块（受限写入）✅

核对/讨论会话中 agent 的唯一写通道：回复内嵌至多一个 ```` ```simulanka-ops ```` 块，由 harness 解析、**server 写权闸逐条过滤**（`server/agent_ops.py`，一条坏 op 报告不连坐）：

| op | 闸门规则 |
| --- | --- |
| set_verdict | 仅 data_flow 边；verdict ∈ correct/wrong/uncertain；`verdict_note` 必填；**verdict_by=user 的边一律拒**（人裁至上） |
| propose_edge | source/target 为端口 id；`citation` 必填（无引证 = 猜测 = 拒）；落地强制 `source=agent, status=proposed, verdict=unconfirmed` |
| withdraw_edge | 仅撤自己未被接受的 ghost |

其余一切（接受实边、删人边、`verdict_by`、shape_check 等实域 attrs）都拒，理由回到聊天里。

## 模型 → 图：torch importer + baseline manifest ✅

**`simulanka import torch`**：`nn.Module` → model/module 层级 + 端口 + `data_flow` 边。

- 结构来自 `named_modules()`；数据流来自真实 forward 下的 module hooks + `TorchDispatchMode`（张量携带 producer 集合，血缘穿过 `+`/`cat`/reshape 等无 module 栈的函数桥），叶级边向上卷到首个分叉祖先对。
- trace 边铭章：`source=trace, verdict=correct, verdict_by=trace`——机器观察生而免验。
- `example_inputs=None` = **structure-only 兜底**：只导层级，根节点盖 `dataflow_unavailable=true`。

**`simulanka import baseline [--check]`**：baseline 仓内 `simulanka_builds/manifest.yaml` 声明式成图。

- `top_level.build` 必须返回完整顶层模型（通常 structure-only）；`children` 必须**恰好覆盖** `named_children()` 全集，每项 `build`（带真实输入的聚焦 trace）或 `skip: <理由>`（显式豁免）二选一——漏组件是 lint error，不是静默缺口。
- 聚焦 trace 以 fqn 命名、作**兄弟** model 节点提交，不并入顶层子树。`--check` 只 lint 不落图。

## 图 → 可视化：`simulanka export model-explorer` ✅

模型子树 → Google Model Explorer JSON（namespace 层级 + incomingEdges），供第三方查看器。

## 执行现场 → 图：run 记录

**现状已有：**

- **`run exec`** ✅ 同步 shell run：`sh -c` 执行、stdout/stderr 落 `.simulanka/runs/<handle>/` 并登记为 file 节点 + `produces` 边；status ∈ done/failed/timed_out。
- **`run exec --detach` + status/wait/kill/reconcile** ✅ 异步：子进程独立会话存活，run 节点先记 `running`，收尾**惰性 reconcile**（wrapper 脚本写 finished 标记，下次查询时 `update_attrs` 补账；进程死而无标记 = failed）。graph 查询命令不偷偷 reconcile。
- **`task create/inspect`** ✅ TaskContract：`goal` + `allowed_outputs`（gitignore 风格 glob）+ `acceptance.command` + `budget.time_seconds`，平铺进 task 节点 attrs。
- **契约检查** ✅（`contract.py`）：diff 对 `allowed_outputs` 越界 → `out_of_scope`；acceptance 非零 → `acceptance_failed`；判定优先级 out_of_scope > acceptance_failed > passed；acceptance 日志入 run_dir。

**`run begin` / `run end`（S1）✅**——执行括号（`runner/bracket.py`，实测于 `tests/test_run_bracket.py`），系统只在两端测量，中间干活的是人还是 agent 不管：

- `run begin --task <sel> [--parent <dir>] [--name <n>] [--workdir <path>]`：建 run 节点（`status=running`, `bracket=true`）+ 镜像契约（`contract` attr + `<run_dir>/contract.json` 快照 + `fulfills` 边），单 PatchIntent 原子落地。**diff 机制＝快照比对**（2026-07-09 裁定：begin 拍工作区快照存盘、end 比对，全系统统一为这一条测量路径；作废原 §14.8「porcelain 清单集合差」——集合差漏掉「begin 时已脏、run 中又改」的文件，快照比对不漏且不依赖 git）。git HEAD 与脏文件清单（`git status --porcelain -uall` 文件粒度）在 begin 时记录为**诚实性元数据**（`git_head` / `baseline_dirty` / `git_dirty_files`，workdir 非 git 仓则不记），不作 diff 机制。首行裸打 run id，harness 自持，**不设「当前 run」环境态**。`--parent` 缺省 = task 的父节点；`--name` 缺省 = `run-<handle>`。
- **diff 粒度（2026-07-10 定）＝路径清单**：快照只存 `{路径: hash}` 不留内容——系统永久回答「动了哪些文件」（漏不掉），不回答「改了什么内容」；内容对比靠 workdir 为 git 仓时兜底（baseline 工作流 worktree-per-run 天然满足），彩排首撞「必须看内容」再议，不预做。快照存盘 `<run_dir>/snapshot.json`；共享测量模块＝`workspace.py`（snapshot/diff/scope，wrapper、detached、bracket 三处同源——「一条测量路径」的实体化）。
- 人肉括号不造 stdout/stderr file 节点（人在自己终端干活，系统看不见就不假装记录；acceptance.log 照旧入 run_dir）。同 workdir 并发 run 的 diff 互染 v1 不设防（靠 worktree-per-run 约定）。预算超时不打失败章——duration 如实记录，值不值归分析者。
- `run end <run> [--status done|failed] [--metrics <file>]`：① 对 begin 快照算 diff（写 `<run_dir>/changes.json`）→ ② 按 contract.json 快照跑 acceptance（判的是 begin 时的契约，改 task 不改历史）→ ③ 写 `contract_check` → ④ `ended_at`/`duration_seconds`/`status` 单 patch 收口 → ⑤ 触发 evidence 提取（S2 同一条路；显式 `--metrics` 或 workdir `metrics.json` 存在即提，提取失败不挡收口）。已 end 再 end = 拒；`--status failed` 照样测量（人的主张不改测量）。
- 孤儿 run（begin 后 harness 崩）：人工 `run end --status failed`；doctor 增 `stale_running_run` 检查（`running` 超预算、无预算超 24h 即提示，bracket 提示 end、detached 提示 status）。
- intent 一律 `actor="system"`（测量归系统）。

**`evidence extract <run>`（S2）✅**（`evidence.py`，实测于 `tests/test_evidence_extract.py`；`run end` 内也触发，同一条路）：

- 约定：metrics 文件 = **平铺 JSON 标量字典**（`--metrics` 或 workdir `metrics.json`；task 的 `allowed_outputs` 应涵盖它）。
- 产出：`evidence` 节点（parent=run，名 `evidence-<序号>`），attrs `source="machine"`、`metrics`、`metrics_path`、`body`=一行摘要；`produces` 边 run→evidence，单 PatchIntent。**不连 supports/contradicts**——语义判断归分析者。
- 解析失败/非标量 → 不造 evidence，run 记 `metrics_error`（宁可缺不可假）；后续提取成功则清为 null。文件不存在＝用法错误，不盖 `metrics_error`（从未主张过测量）。
- 标量边界（2026-07-10 定）：str / int / float / bool 算标量；null 或嵌套 dict/list 出现即整文件拒，不做部分提取；空对象也拒。
- 幂等（2026-07-10 定）：同一 run 重复 extract，metrics 内容相同＝无操作（报既有 evidence id）；内容变了＝新造 evidence 节点，不覆盖旧的（历史不改写）。
- intent `actor="system"`（测量归系统）。

## agent 调用（插座）✅

系统管调用、测量、写权三件事，不管 agent 输出什么：

- **`run agent`**：(agent, prompt|--task) → CLI 调用（argv 模板 `codex exec {prompt}` / `claude -p {prompt}`，`SIMULANKA_AGENT_<NAME>_ARGV` 环境变量可覆盖）。**不接管** agent 的 skills/MCP 配置，**不解析**其输出——只前后快照工作区、diff 写 `changes.json`；挂 task 时镜像契约 + fulfills + 契约检查。`--detach` 异步同 run 路径。
- **`propose`**：起 agent 读 forward() 提议 ghost 数据流边。纪律在代码里强制而非 prompt 里恳求：仅已知直接子模块间、`citation` 非空才落地（cite-or-skip），全部生而 `proposed/unconfirmed`，多输出经 out_port/out_slice 表达。
- **opencode harness**（`agent/harness.py`）：非交互续聊 opencode session、抽出回复文本、解析 ops 块——讨论面板的执行底座。

## agent 插座子任务 🔲（S8，静态末位）

2026-07-09 grill 定，2026-07-10 编号提级为独立子任务。四件：

1. **run agent 骑到 run 括号上**——消掉「wrapper 快照 diff」与「run end 测量」两套并行真相，全系统一条测量路径（动 `agent/wrapper.py`，属 Codex 线，规格 Claude 出；S1 抽出的共享测量模块 `workspace.py` 是其地基）。
2. **`--actor operator`** 在 CLI 机械写命令上贯通。
3. **前端内嵌自由 agent 会话**走结构化事件流路线（见 frontend.md S8）。
4. **锚定会话 UI**——核对/讨论会话的就地化壳（S7 面板退役的配套件；一批一场、写权闸机制不变）。

**2026-07-18 grill 增补**：轮次模型＝opencode 非交互续聊（沿讨论 harness session 模式），`--format json` 事件流边到边转；事件词表＝07-16 转录规格的扩展（`user_msg / agent_text / tool_call / tool_result / status / error`，每场一文件逐条追加、挂载恢复，干活与聊天会话共用）；**actor 贯通机制**＝会话/CLI 子进程注入 `SIMULANKA_ACTOR`，CLI 缺省 actor 读环境——agent 会话里跑的一切写图命令自动带正确身份过写权闸；**护栏 v1＝测量不拦**（批准流挂动态线）；**叫停＝杀当轮进程、run 括号留人收口**（doctor stale 检查兜底）。前端呈现细则见 frontend.md S8「2026-07-18 grill 增补」。**S8 施工＝openspec 管自身开发的试点第一单**（与死端「openspec 套研究循环」无冲突）。

**死端勿再试**：PTY 终端透传作主路线（`pty_bridge`/`opencode_cli_bridge` 原型实测体验差，TUI 重绘/尺寸/输入法驯服成本无底）——降级为逃生舱不再投入，sidecar 录制思想保留。

## 手稿层改造 🔲（S9，排 S8 后；2026-07-18 Reparent 场 grill 定）

**定案：研究原子＝手稿模式。** 一轮研究＝盘上真轮次文件夹 `research/<round>/`：**原子手稿文件**（question / hypothesis / experiment / claim / task / note——一原子一文件，front-matter 记类型/lid/引用/契约，正文＝内容；**唯一原文**）＋纯散文 `plan.md`（叙事，不再承载结构块）。**plan 结构块退役**（修正 2026-07-06「一文档恰一结构块」定案）。切线原则：**凡分析者写的皆文件；凡机器测的皆投影**（run/evidence 不立文件——真身本来就是日志与 metrics）。

- **plan ingest → 手稿同步器**：盯轮次文件夹确定性落图——lid/文件名＝钥匙、就地重画；系统外删手稿＝图上**失效态**（不静默清）。原子的图位置由手稿派生：住哪个文件夹＝属哪轮、front-matter 引用＝属哪个实验——画布对研究域是取景器，研究原子不走画布拖拽。
- **裁决只记图**＋记裁决时内容指纹——手稿事后被改，能亮「裁决针对旧版」。
- **直通删除**（语义本场定，执行随 S9）：系统内删（画布右键）＝预览清单（N 手稿、M 原子、K 档案、断链提示）一次确认 → 盘＋图一笔事务清除，**档案（runs/evidence）连坐可删**（用户拍板），事件日志永久案底（销毁本身记一笔）；系统外删＝失效态等人处置。两扇门语义不同是有意的。
- **kernel `ReparentOp`**（本场顺带定）：改 parent＋重写 contains 边一笔事务、防环防重名，原语通用；v1 消费者＝圈选打包（照片域，前端侧见 frontend.md「S9 配套」）。
- **配套**：brief export 出口适配（图 id 通货不变）；旧图迁移脚本（从既有原子 attrs 生成手稿文件）；完工后补「写计划」步骤迷你彩排（静态验收按旧写法过的）。

**死端勿再试**（2026-07-18）：**全节点文件化**（文件管理器管全部节点、库只记边）——写权蒸发（fs 不记 actor，「人裁最高」无法执行）、两份真相同步税（双 research bug 病根 × 全图）、删除级联断头（`rm` 不知边的存在）、模型内节点必不可文件化⇒「全」字破坏统一（用户自证）；**原子文件＝回执模式**（图为源、文件为打印件）——用户必顺手改回执，重印覆盖人改；**工作区整体只读（只有系统能写）**——杀死手稿模式与 agent 干活的自由写前提，同账号下 OS 锁一条 `chmod` 即解、真锁＝服务账号重机械单机代价荒谬，「只有系统能写」在图层已成立、推广到工作区是把门装错地方。

**定位句（2026-07-18 用户）**：图＝一个可交互的巨大文档——对 agent 是上下文（简报/锚定戳/血缘按需切片喂），对人是账本（测量/裁决/历史）；文件＝创作区，分开管（登记中心＋直通操作＋同步器，故意做薄，不取代文件管理器）。

## CLI 一览（转换面）

| 命令 | 转换 | 现状 |
| --- | --- | --- |
| `plan ingest <file>` | 文档→图 | ✅ |
| `brief export [--out <名>]` | 图→文档 | ✅ |
| `note resolve <note>` | escalate 闭环（人解除） | ✅ |
| `import torch` / `import baseline [--check]` | 模型→图 | ✅ |
| `export model-explorer` | 图→可视化 | ✅ |
| `run exec [--detach]` / `run status|wait|kill|reconcile` | 执行现场→图 | ✅ |
| `run begin --task` / `run end` | 执行现场→图 | ✅ |
| `evidence extract <run>` | 执行现场→图 | ✅ |
| `task create|inspect` | 契约 | ✅ |
| `run agent` / `propose` | agent 插座 | ✅ |
