# 图汇编语言（转换层）

> 分篇之二（入口见 `overview.md`）。统一抽象：**文档、模型、执行现场都是外部原文，图是它们的可检查投影**。
> 每种转换都是确定性工具——同样的原文必得同样的图。人和任何模型只读写原文，不直接操作图。
> 标注 🔲 的小节是已定稿、未施工的规格（子任务 S1–S3、S8；编号见 overview 施工清单）。

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

## 图 → 文档：brief 块 + `brief export` 🔲（S3）

分析者开场输入，ingest 的逆操作。输出 markdown：prose 概览 + 一个 ```` ```simulanka-brief ```` JSON 块，与 plan 块**镜像对偶——简报给出的图 id 就是下轮 distill 段可直接引用的 id**。

- 块内容（全部确定性、按 id 排序，同图态必同输出）：open 的 question/hypothesis/claim；近期 run（id、task goal、contract_check、duration、**evidence 条目含节点 id + metrics**——没有 evidence id，下轮 supports/contradicts 无的放矢）；未处理的 escalate note；§13 分歧集条数（一行）；预算消耗小计。
- open 判据（v1，查询时判）：claim = `status=="open"`；hypothesis = 无 `verdict`；question = 全列。「近期 run」= 非 `done` experiment 名下全部 run（experiment 翻 done 是操作员机械流）。
- `--out <file>` 或 stdout；文件走 FileRegistry `brief` kind。如有写入，`actor="system"`。
- **escalate 闭环（2026-07-10 定）**：note 增 `status: open|resolved`；解除＝人的显式动作（前端就地「已处理」按钮 / CLI，`actor=user`，可附处置理由 `resolve_note`）；brief 只列 open。「下轮 ingest 自动消音」已否决——叫停信号只能由人解除，与人裁至上同源。
- 无 task 的 run（`run exec` 裸跑）：task goal / contract_check 字段缺省即空，不造假。
- 分歧集条数与 server `/disagreements` 同一计算（抽共享模块，不写第二份）；预算小计＝每个非 done experiment 一行，Σrun duration 对 Σtask budget。

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
- 现状限制：**run 挂 task（fulfills + 契约检查）目前只有 `run agent` 一条路**——这正是切片②要解开的。

**🔲 `run begin` / `run end`（S1）**——执行括号，系统只在两端测量，中间干活的是人还是 agent 不管：

- `run begin --task <sel> [--parent <dir>] [--name <n>] [--workdir <path>]`：建 run 节点（`status=running`）；镜像契约（`contract` attr + `<run_dir>/contract.json` 快照 + `fulfills` 边）；**diff 机制＝wrapper 快照比对**（2026-07-09 裁定：begin 拍工作区快照存盘、end 比对，全系统统一为这一条测量路径；作废原 §14.8「porcelain 清单集合差」——集合差漏掉「begin 时已脏、run 中又改」的文件，快照比对不漏且不依赖 git）。git HEAD 与脏文件清单（`git status --porcelain -uall` 文件粒度）仍在 begin 时记录为**诚实性元数据**（`baseline_dirty=true`），不作 diff 机制。打印 run id，harness 自持，**不设「当前 run」环境态**。`--parent` 缺省 = task 的父 experiment。
- **diff 粒度（2026-07-10 定）＝路径清单**：快照只存 `{路径: hash}` 不留内容——系统永久回答「动了哪些文件」（漏不掉），不回答「改了什么内容」；内容对比靠 workdir 为 git 仓时兜底（baseline 工作流 worktree-per-run 天然满足），彩排首撞「必须看内容」再议，不预做。快照存盘 `<run_dir>/snapshot.json`；`_snapshot/_diff` 从 agent wrapper 抽成共享模块（「一条测量路径」的实体化）。
- 人肉括号不造 stdout/stderr file 节点（人在自己终端干活，系统看不见就不假装记录；acceptance.log 照旧入 run_dir）。同 workdir 并发 run 的 diff 互染 v1 不设防（靠 worktree-per-run 约定）。预算超时不打失败章——duration 如实记录，值不值归分析者。
- `run end <run> [--status done|failed] [--metrics <file>]`：① 对基线算 diff（复用 wrapper 的 workspace diff 路径）→ ② 按 contract.json 快照跑 acceptance → ③ 写 `contract_check` → ④ 有 metrics 则触发切片③ → ⑤ `ended_at`/`duration_seconds`/`status`。已 end 再 end = 拒。
- 孤儿 run（begin 后 harness 崩）：v1 人工 `run end --status failed` + doctor 增一检（`running` 超预算或 24h 即提示）。
- intent 一律 `actor="system"`（测量归系统）。

**🔲 `evidence extract <run>`（S2，`run end` 内也触发）**：

- 约定：metrics 文件 = **平铺 JSON 标量字典**（`--metrics` 或 workdir `metrics.json`；task 的 `allowed_outputs` 应涵盖它）。
- 产出：`evidence` 节点（parent=run），attrs `source="machine"`、`metrics`、`metrics_path`、`body`=一行摘要；`produces` 边 run→evidence。**不连 supports/contradicts**——语义判断归分析者。
- 解析失败/非标量 → 不造 evidence，run 记 `metrics_error`（宁可缺不可假）。
- 标量边界（2026-07-10 定）：str / int / float / bool 算标量；null 或嵌套 dict/list 出现即整文件拒，不做部分提取。
- 幂等（2026-07-10 定）：同一 run 重复 extract，metrics 内容相同＝无操作（报既有 evidence id）；内容变了＝新造 evidence 节点，不覆盖旧的（历史不改写）。`run end` 触发与手动同一条路。

## agent 调用（插座）✅

系统管调用、测量、写权三件事，不管 agent 输出什么：

- **`run agent`**：(agent, prompt|--task) → CLI 调用（argv 模板 `codex exec {prompt}` / `claude -p {prompt}`，`SIMULANKA_AGENT_<NAME>_ARGV` 环境变量可覆盖）。**不接管** agent 的 skills/MCP 配置，**不解析**其输出——只前后快照工作区、diff 写 `changes.json`；挂 task 时镜像契约 + fulfills + 契约检查。`--detach` 异步同 run 路径。
- **`propose`**：起 agent 读 forward() 提议 ghost 数据流边。纪律在代码里强制而非 prompt 里恳求：仅已知直接子模块间、`citation` 非空才落地（cite-or-skip），全部生而 `proposed/unconfirmed`，多输出经 out_port/out_slice 表达。
- **opencode harness**（`agent/harness.py`）：非交互续聊 opencode session、抽出回复文本、解析 ops 块——讨论面板的执行底座。

## agent 插座子任务 🔲（S8，静态末位）

2026-07-09 grill 定，2026-07-10 编号提级为独立子任务。四件：

1. **run agent 骑到 run 括号上**——消掉「wrapper 快照 diff」与「run end 测量」两套并行真相，全系统一条测量路径（动 `agent/wrapper.py`，属 Codex 线，规格 Claude 出；S1 抽出的共享快照模块是其地基）。
2. **`--actor operator`** 在 CLI 机械写命令上贯通。
3. **前端内嵌自由 agent 会话**走结构化事件流路线（见 frontend.md S8）。
4. **锚定会话 UI**——核对/讨论会话的就地化壳（S7 面板退役的配套件；一批一场、写权闸机制不变）。

**死端勿再试**：PTY 终端透传作主路线（`pty_bridge`/`opencode_cli_bridge` 原型实测体验差，TUI 重绘/尺寸/输入法驯服成本无底）——降级为逃生舱不再投入，sidecar 录制思想保留。

## CLI 一览（转换面）

| 命令 | 转换 | 现状 |
| --- | --- | --- |
| `plan ingest <file>` | 文档→图 | ✅ |
| `brief export` | 图→文档 | 🔲 S3 |
| `import torch` / `import baseline [--check]` | 模型→图 | ✅ |
| `export model-explorer` | 图→可视化 | ✅ |
| `run exec [--detach]` / `run status|wait|kill|reconcile` | 执行现场→图 | ✅ |
| `run begin --task` / `run end` | 执行现场→图 | 🔲 S1 |
| `evidence extract <run>` | 执行现场→图 | 🔲 S2 |
| `task create|inspect` | 契约 | ✅ |
| `run agent` / `propose` | agent 插座 | ✅ |
