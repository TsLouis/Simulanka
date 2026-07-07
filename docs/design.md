# Simulanka — Research Graph Kernel Alpha

Date: 2026-05-15 · Status: Draft

精简到最少原语。依据：`researcher-handoff/researcher_remote_handoff_2026-05-14.md` 八条原则。

## 1. 三个原语

**Node** — 任何"东西"。`directory`、`file`、`model`、`module`、`question`、`evidence` 等都是 node 的 `type`，不另立实体。

**Edge** — 任何"关系"。`contains` 是层级权威（不靠 parent_id）；`data_flow`、`supports`、`derived_from` 等是语义边。

**Port** — node 的连接点。只有 `data_flow` 这类需要精确接口的边引用 port；`contains`、`supports` 直连 node。

不引入 File、Directory 实体；不区分 PatchIntent 与 GraphPatch 两层模型（见 §3）。

## 2. 字段（pydantic v2 模型）

```
Node : id, type, name, parent_id?, attrs, created_at, created_by
Edge : id, type, source_id, target_id, source_port_id?, target_port_id?, attrs, created_at, created_by
Port : id, node_id, name, direction("in"|"out"), port_type, attrs, created_at, created_by
```

- `id`: ULID 带前缀 `nod_` / `edg_` / `prt_`。节点**名字**曾不禁用这些前缀，而 `UpdateAttrsOp` 按 `edg_` 前缀分流 selector——名为 `edg_*` 的节点裸名更新会被劫持报 "edge not found"（2026-06-12 评审发现）。**2026-07-06 裁定：三前缀为名字保留字**，validator 在 create/rename 时拒绝；2026-07-07 已实现，连带 `@` 前缀一并保留（与 §3 intent 内 `@ref` 句柄语法冲突）。
- `parent_id` 是 `contains` 边的反范式缓存；doctor 校验一致性。
- `attrs` 的合法 key 与值由类型注册表声明的 pydantic 模型校验。
- canonical 存储里不存 selector，只存 id。

## 3. 写路径

**唯一入口：`apply_patch(intent) -> Receipt`。** CLI、importer、agent 都走它。

```text
PatchIntent (含 selector)
  → resolve  (selector → id；歧义 → 拒绝并列候选)
  → validate (类型注册表声明式约束 + validator 钩子，钩子只读)
  → commit   (append event → 写实体文件 → 更新 index → bump manifest)
```

事务边界：上述四步全成功才落盘（临时目录 + 原子 rename）。失败 → 整体回滚。

`PatchIntent.ops` 支持：`create_node` / `create_edge` / `create_port` / `update_attrs`（同 patch 内可级联，浅 merge 语义） / `rename_node` / `delete_edge`（§13.3 加，唯一删除语义，拒 `contains`）。节点 `delete` / `move` 仍未实现（无真实用例驱动）。实现节奏见 §9。

**Intent 内引用 `@ref`**（2026-07-07 裁定，§14.7 干跑逼出）：`create_node` 增可选 `ref` 字段（intent
局部句柄）；同 intent 内后序 op 的 node selector 可写 `@<ref>` 引用该新建节点（parent、edge 端点、
update_attrs target 均可）。此前 resolver 只见已落盘实体，「建节点 + 连边」无法单 intent 原子落地
（plan ingest 的硬前提；importer 当年也是被迫分批）。选显式句柄而非让路径 selector 穿透 pending：
歧义为零、事件里仍记真实 id、回放不受影响。`ref` 不落盘、不进 canonical ops。

乐观锁：intent 携带 `base_graph_version`；与 manifest 不符则拒绝并提示重读。

## 4. Selector（仅 Intent 输入）

| 形式               | 含义                                        |
| ------------------ | ------------------------------------------- |
| `nod_01HX...`      | 直接 ID                                      |
| `/models/TinyNet`  | 按 `contains` 链解析的绝对路径               |
| `conv1.out`        | 当前 scope 下 node 的命名 port               |

任意匹配多于一项 → 拒绝并返回候选。canonical 不存 selector。

## 5. 类型注册表

```python
NODE_TYPES: dict[str, NodeTypeSpec]   # allow_parents, attrs_model, optional validator
EDGE_TYPES: dict[str, EdgeTypeSpec]   # needs_ports, source_types, target_types, optional validator
```

`PORT_TYPES` 只是字符串集合，由 edge 的声明驱动校验（如 `data_flow` 要求 source 是 `out` 方向、target 是 `in` 方向）。

注册表是代码 + 数据，版本号 `registry_version` 随之走。Validator 钩子签名 `(view, op) -> list[Error]`，只读。

### 5.1 研究语义层（atoms）

在第 7 步加入 7 类研究节点 + 6 条语义边，让图能描述科研叙事而不只是模型结构。

**节点类型与典型 attrs**（attrs 是约定，不强校验）：

| 类型 | 允许父类型 | 约定字段 |
| --- | --- | --- |
| `question` | directory | `body` |
| `hypothesis` | directory, experiment | `body` |
| `claim` | directory, experiment | `body`, `status` ∈ {open, supported, refuted} |
| `evidence` | directory, experiment, run | `body`, `source`（来源描述/链接） |
| `experiment` | directory | `goal`, `status` ∈ {planned, running, done} |
| `run` | directory, experiment | `started_at`, `ended_at`, `status`, `command` |
| `note` | directory, experiment, run | `body` |

**语义边**（端点类型严格约束）：

| 边 | source → target |
| --- | --- |
| `addresses` | hypothesis → question |
| `tests` | experiment / run → hypothesis |
| `supports` | evidence → claim / hypothesis |
| `contradicts` | evidence → claim / hypothesis |
| `produces` | run → file / evidence |
| `part_of` | run → experiment |

**有意为之的取舍**：

- 不引入 `task`、`decision`、`artifact` 三种 atom：task 与 experiment 在 Alpha 重叠，先用 experiment；decision 用 `note` + attrs 替代；artifact 直接用 `file` 节点 + `produces` 边表达，不再立一类。
- claim 的 status 不自动随 supports/contradicts 边的累积重算。状态由查询方实时算（"这条 claim 有几条支持/反驳"），写路径保持纯净。
- attrs 字段约定写在本表，**不在代码里强 schema 校验**。研究字段经常增删，硬 schema 是摩擦。当 attrs 真的稳定后，再按 kind 给 attrs 上 pydantic 模型，由 validator 钩子启用。
- 没有专门的研究 CLI 子命令：用现有 `simulanka graph node create --type <atom> --attr 'body=...'` + `simulanka graph connect <src> <tgt> --type <semantic_edge>`。用得多了再加 `simulanka research ...` 便利层。

`contains` 边的 source_node_types 在第 7 步扩入了 `experiment` 和 `run`（这两类节点是 container-capable），保持 dual-write 一致。

### 5.2 PyTorch importer（第 8 步加入）

把"已构造好的 `nn.Module` 对象"翻成 `model` + `module` + `data_flow` 图。**不**做静态 AST 解析。

**输入契约**：用户提供一个 `pkg.mod:fn`，`fn()` 返回 `(model, example_inputs)`。example_inputs 是 `model(*example_inputs)` 的位置参数元组。**多文件、复杂依赖、配置驱动的实例化都由 Python 自己的 import 机制处理**，importer 只看最终装好的 module 对象。

**层级**：`model.named_modules()` 出来的 dotted fqn 直接成为 `/<parent>/<name>/<fqn 用 / 替换 . >` 这条路径上的 module 节点。每个 module + 根 model 都自动配 `in`/`out` 两个 tensor port。

**数据流**：在每个非根 submodule 上挂 `register_forward_pre_hook` + `register_forward_hook`，再叠一层 `TorchDispatchMode` 拦截 aten op，跑一遍真实 forward。每个 tensor 携带一个 **producer 集合**（祖先模块 fqn），aten op 把所有输入的集合并到输出，post_hook 在模块边界把输出的 producer 重置为 `{fqn}`，pre_hook 在边界发 `(src, fqn)` 边。leaf-leaf 流回滚到"首个发散祖先"那一对（`b1.lin → b2.lin` 折成 `b1 → b2`；`b1.lin → b1.act` 保留为同级），再连成 `data_flow` 边。

> 实现坑：producer map 用 `id(tensor)` 键控，CPython 回收后立即复用内存地址，老 producer 残留会污染新 tensor。每次 stamp 必须注册 `weakref.finalize(t, _drop, tid)` 在 GC 时自动 pop，否则边数会爆掉一个量级。
>
> 历史：最初用 `torch.export` + `nn_module_stack` 归因，2026-05-19 在 Hiera 上发现对 transformer 系统性丢边（残差 `+` 是 functional op，没 nn_module_stack）。换成纯 hook 修了残差但还漏 functional bridge（`window_partition(norm1(x))` 这种夹在两 Module 之间的 reshape 会断链）。加 TorchDispatchMode 后 producer 集合穿透任意 functional op 链路，是 strict superset。

**导入入口约定（结构完备性的保证）**：build_fn 必须返回 baseline 的**顶层**模型实例（例如整个 `SAM2Base`），不是手挑的组件。结构完备性由 `model.named_modules()` 这个 PyTorch 自己的 API 保证 —— 在顶层 import 时，全部子模块及其子树**不可能漏**。手挑组件的旧用法（一个 baseline 写 N 个 build_fn）已淘汰，原因是漏哪个完全靠人记，2026-05-19 实操中真漏掉了 PromptEncoder/MemoryEncoder/FpnNeck。

**Alpha 不做**：
- aten 层级图（leaf-leaf 边收起来了；多级展开留给查询/前端）
- 配置文件解析为图节点（用 `file:config` 节点 + `uses` 边足够）
- shape/dtype 元数据（hook 拿不到，要 shape 得另起 export pass）
- 自定义 autograd function、`torch.compile` 后的图、量化图

**已知支持范围**：能跑通一次 forward 的模型都行，包括 data-dependent control flow。代价是要给真 example_inputs 跑一次推理，结构反映的是这次 trace 的执行路径（不同 input shape / mode 可能不同）。

**CLI**：`simulanka import torch --build pkg.mod:fn --name N [--parent /dir]`。`--parent` 默认 `/baselines`（scaffold 必建；`model` 节点不允许挂项目根，所以"省略=根"从来不是合法默认），`import baseline` 同理。

#### 收尾两项（均已落地）

1. ✅ **`example_inputs=None` 走 structure-only 路径**（2026-05-20）。顶层模型如 `SAM2Base` 的 forward 是跟踪 pipeline，构造合法 example_inputs 代价大；这种情况下只走 `named_modules`、跳过 data flow trace，落地一个 `model` + 一组 `module` 节点 + `dataflow_unavailable=true` 属性。配套 `simulanka import baseline <dir>` 读 `manifest.yaml`，`lint_manifest` 强制 `set(children)==named_children()` 做机制级防漏。
2. ✅ **导出 [Google Model Explorer](https://github.com/google-ai-edge/model-explorer) 兼容格式**（2026-05-21）。`src/simulanka/exporter/model_explorer.py::to_model_explorer` + CLI `simulanka export`。schema 即 `namespace` 分层 + 每节点 `incomingEdges`，换来浏览器里折叠/展开/搜索的交互式可视化。

#### 调研结论（2026-05-19）

调过开源生态找能直接替换的 backend：`torch.fx` / `torch.export` 在 functional 残差边和 data-dependent control flow 上 2026 仍有真问题（PyTorch 2.11 的 `draft_export` 是诊断，不是修复）；`torchinfo`/`torchviz`/`hiddenlayer` 只是 viz；`Netron`/Model Explorer 只渲染图、不抓图；`nnsight` 是干预 API；唯一对位的 `torchlens`（2026-05 活跃）机制等价（monkey-patch + hooks），能力**不更优**，且无 `weakref.finalize` 这层语义。结论是自研路径合理，可以借 torchlens 的 numerical validation 思路给 doctor 加图正确性自检（低优先级）。

### 5.3 Run executor（第 9 步加入）

把"跑一条命令"的执行历史落到图里。`simulanka run exec` 同步阻塞执行 shell 命令，捕获 stdout/stderr 到 `.simulanka/runs/<handle>/`，提交一个 `run` 节点 + 两个 `file` 节点（stdout/stderr 日志）+ 两条 `produces` 边。

**run 节点 attrs**（约定，不强校验）：
- `command`（shell 命令）
- `agent`（`shell` / `codex` / `claude` / ...；目前仅做标签，专属调用是上层封装）
- `status` ∈ {done, failed, timed_out}
- `exit_code`、`started_at`、`ended_at`、`duration_seconds`
- `workdir`、`stdout_path`、`stderr_path`、`run_handle`

**Alpha 不做**：
- 异步/后台执行；运行中状态切换。所有 attrs 在 subprocess 结束后一次写入；进程崩溃则什么都不留下（用户重跑即可）。
- 自动追踪命令写出的任意文件。用户产出物自行 `simulanka graph file register` 登记。
- Codex/Claude 专属调用层。`--agent` 当前只是个字符串标签。

**事务边界**：两个相邻 patch —— 第一 patch 写 run + 两个 file 节点，第二 patch 写两条 produces 边。中间崩溃则只有节点没有边；doctor 不会报错（produces 边不是必需的），节点的 fs_path / content_hash 仍然完整。

**CLI**：`simulanka run exec --cmd '...' --parent <dir|experiment> --name N [--workdir <path>] [--agent <label>] [--timeout <sec>]`

### 5.4 Agent wrapper（第 10 步加入）

在 §5.3 的 run executor 之上加一层薄薄的转换：把 `(agent, prompt)` 翻成具体 CLI 调用，跑完抓 workspace 文件 diff。**故意保持薄**：

- **不**接管 agent 的能力配置。Skills、MCP server、tool 白名单、权限模式 —— 都由用户在 codex / claude 自己的 config 里搞（`~/.codex/config.toml`、`~/.claude/CLAUDE.md` 等）。wrapper 只调二进制，agent 那边怎么配置都"自然生效"。
- **不**解析 agent 的输出格式。stdout/stderr 原样捕获到 run dir。JSON 流、tool-call trace 这类版本依赖强的东西不挂钩。
- **不**自动把 agent 摸过的文件登记为 graph 节点。"该归 code / config / baseline / artifact 哪类"是用户判断，wrapper 只在 `changes.json` 里给出快照清单。

**Argv 模板**：内置 `codex` 和 `claude` 两个起点。任何条目可以用环境变量 `SIMULANKA_AGENT_<NAME>_ARGV='binary --flag {prompt}'` 覆盖 —— codex 哪天改 CLI 改环境变量即可，**不需要改 simulanka 代码**。这就是松耦合的扩展点。

**生成的产物**：
- `run` 节点（attrs 同 §5.3，`agent` 字段就是 `--agent` 传的名字）
- 两个日志 file 节点（stdout / stderr）
- `<run_dir>/prompt.txt` —— 原始 prompt
- `<run_dir>/changes.json` —— `{agent, argv, workdir, track_scope, added, modified, deleted}`

`changes.json` 故意不进图：内容会随 agent 行为剧烈变化，做成 file 节点会让 doctor 频繁报 content_hash 漂移；用户要查询直接读文件。

**CLI**：`simulanka run agent --agent codex|claude|<name> --prompt '...' --parent <dir|experiment> --name N [--workdir <path>] [--extra <arg>...] [--track <subdir>...] [--timeout <sec>]`

### 5.5 update_attrs 与异步执行（第 12 步加入）

#### `update_attrs` op

第 4 个 intent 操作。**浅 merge** 语义：

```python
UpdateAttrsOp(target=<selector>, attrs={"status": "done", "exit_code": 0})
```

- 已存在 key 被覆盖，未提到的 key 保留原值。Alpha 不支持删除 key（用 None 不会删，会写 null 值）。
- 不能修改 type / name / parent_id —— 那是 move/delete op 的领地（Alpha 不实现）。
- 同一 patch 内可放多个 `update_attrs` 指向同一节点，后者基于前者 merge 结果再 merge。
- Receipt 新增 `updated_nodes: list[str]`。

#### 异步运行（`--detach`）

`simulanka run exec --detach ...`（也支持 `run agent` 未来扩，当前仅 `run exec`）：

1. 写 `cmd.sh`（用户命令）+ `run.sh`（包装脚本）到 `.simulanka/runs/<handle>/`
2. `subprocess.Popen(["sh", run.sh], start_new_session=True, ...)` —— subprocess 在新 session 中运行，simulanka 进程退出后它继续活
3. 立刻提交 `run` 节点（`status=running`、`pid`、空 hash 的两个 log file 节点 + produces 边），CLI 返回

包装脚本结构：

```sh
sh "$RUN_DIR/cmd.sh" > stdout.log 2> stderr.log < /dev/null
status=$?
date -u ... > ended_at
printf "%s\n" "$status" > exit_code
touch finished
```

无论 user cmd 成败，shell 总会写出 `finished` marker。只有 wrapper 自己被 SIGKILL 才会留无 marker，此时 reconcile 通过 pid 死活判断。

#### Reconcile（惰性）

`simulanka run status / wait / reconcile / kill` 触发：

```
finished marker 存在？
├── 是：读 exit_code + ended_at，update_attrs(run + 两个 log file 节点)
└── 否：pid 还活着？
    ├── 是：保持 running，不写图
    └── 否：进程消失，update_attrs(status=failed, exit_code=None, ended_at=now)
```

**`graph inspect` 等只读图命令不自动 reconcile**，它们显示"最近提交"的状态。要拿新鲜状态显式 `run status`。这个边界刻意不模糊：图层不知道 runner 在干啥。

**zombie 检测**：`os.kill(pid, 0)` 对 zombie 返回成功（zombie 仍有 PID 但已死），所以 `_is_alive` 读 `/proc/<pid>/status` 看 `State:`，是 `Z` 当 dead 处理。Linux/WSL 专属；其他平台 fallback 到 kill-probe（精度降级）。

#### `run agent --detach`（第 13 步加入）

同样的"两段：launch → 惰性 reconcile"骨架，加上一层 agent diff 的延后计算：

1. `start_agent_run`：先在主进程里算 before-snapshot，然后委托 `runner.start_run` 拉起 subprocess。subprocess 已经在跑之后，把 `before_snapshot.json`、`agent_meta.json`（agent、argv、workdir、track_scope）、`prompt.txt` 写进 `<run_dir>/`。CLI 立刻返回。
2. `finalize_agent_diff(layout, run_node)`：CLI 在 `run status / wait / reconcile` 里跑完 runner 的 reconcile 之后再调一次。它检查 `agent_meta.json` 是否存在 + status 是否终态 + `changes.json` 是否已写过——三者决定走 noop / 计算 diff / 复用现成 diff 三条路径之一。
3. Runner 仍然完全不感知 agent。snapshot 和 changes.json 都不进图（理由同 §5.4）。

before-snapshot 是 launch 前的快照，所以即便 subprocess 在我们写 meta 之前就开始改文件也不会丢；meta 写失败只会让 finalize 退化为 noop，run 节点本身仍由 runner 正常收尾。

#### 仍不在 Alpha

- 超时：detached 模式无 timeout；用 `run kill` 主动中止。
- 后台日志 tail：用户自己 `tail -f $(simulanka run status ... | jq -r .stdout_path)`。

**CLI**：
```
simulanka run exec --detach --cmd '...' --parent ... --name N [--workdir ...] [--agent ...]
simulanka run status <selector>     # reconcile + 打印
simulanka run wait <selector> [--timeout N] [--interval 0.5]
simulanka run kill <selector>       # SIGTERM 到 process group
simulanka run reconcile [<sel>|all]
```

### 5.6 TaskContract + 第一等 `task` 节点（第 14 步加入）

之前 agent 只接 free-form prompt，无法对"做了什么"和"该做什么"做对照。第 14 步把 agent 输入升格为结构化合同 + 第一等 graph 实体。

**`TaskContract`**（`simulanka.contract`，Pydantic）：
```python
TaskContract(
    goal: str,                                    # 必填，原 prompt 的语义升级
    allowed_outputs: list[str] = [],              # gitignore-ish 通配，支持 **
    budget: BudgetSpec(time_seconds: float | None),
    acceptance: AcceptanceSpec(command: str) | None,
)
```

**`task` 节点**：父类型 `directory` / `experiment`；attrs 平铺契约字段（goal、allowed_outputs、budget_time_seconds、acceptance_command）。Edge type 新增 `fulfills` (run → task)。

**两段流程**：
1. 用户先 `simulanka task create --parent ... --name ... --goal ... [--allow] [--budget-time] [--accept]`（或 `--contract <file>`）建一个 task 节点。
2. 用 `simulanka run agent --task <selector> --parent ... --name ...` 真正发起 agent run。agent 层做四件事：
   - 把契约镜像到 run 节点 `contract` attr（带 `task_node_id` 反向链），并写一份 `<run_dir>/contract.json` 留档（task 后续被改也不影响历史 run）。
   - 创建 `fulfills` 边。
   - 跑 agent，算 diff（与 §5.4 / §5.5 完全相同的路径）。
   - 调 `check_contract`：
     - `allowed_outputs` 非空 → 把 diff 里所有路径过通配，违例进 `out_of_scope_files`。
     - `acceptance.command` 非空 → 在 workdir 跑这个命令（用 `sh -c`），acceptance.log 保存到 `<run_dir>/`。
   - 把结果写到 run 节点 `contract_check` attr：`status ∈ {passed, out_of_scope, acceptance_failed, no_check}`，外加 `acceptance_exit_code`、`acceptance_log_path`。

**优先级**：scope 违例 > acceptance 失败 > passed。两者全空 → `no_check`（向后兼容 `--prompt` 自由模式）。

**Detached + 契约**：`start_agent_run --task` 在 launch 后立刻镜像契约到 run 节点，把 `task_node_id` 写进 `agent_meta.json`；`finalize_agent_diff` 跑完 diff 之后自动跑 `check_contract`，判定依据是 launch 时写的 `<run_dir>/contract.json` 快照而非 task 节点现值——launch 后改 task 不重写历史 run 的判定（acceptance 命令在 host 进程的 finalize 阶段同步执行，不是在 detached subprocess 里）。再次 finalize 看到 run 节点已有 `contract_check` attr，跳过——幂等。

**自由模式不动**：`run agent --prompt '...'` 不挂 task、不做检查、不写 `contract` attr。`--prompt` / `--task` 互斥。

**仍不在 Alpha**：契约的版本化；budget.time_seconds 在 detached 模式下的实际执行（仍只在 sync 模式作为 timeout 生效）；超出 wall-clock 之外的预算维度（cost / tokens）。

## 6. 存储与一致性

```text
<project>/.simulanka/
  manifest.json
  graph/
    nodes/<id>.json
    edges/<id>.json
    ports/<id>.json
    events/0001.jsonl           # 分段 JSONL
    indexes/graph.sqlite        # 可删可重建
  logs/  cache/
```

`tasks/` `runs/` `artifacts/` `proposals/` 等是后续阶段才用的目录，到时再建。

`manifest.json`：

```json
{
  "schema_version": 1,
  "registry_version": 1,
  "graph_version": 0,
  "kernel_version": "0.1.0",
  "project_id": "prj_01HX...",
  "content_hash": "sha256:..."
}
```

`content_hash` = 对 `(entity_id, sha256(file_bytes))` 列表按 id 排序后再取 sha256。一个数足以检测任意 out-of-band 篡改，doctor 用它。

三个版本号互相独立：`schema_version`（实体字段结构）、`registry_version`（类型表）、`graph_version`（每次 commit +1）。前两者与代码版本不兼容 → 阻塞写命令，提示 `simulanka graph migrate`。

SQLite 索引是查询加速，可任意删并 `simulanka graph index rebuild`。

## 7. CLI 表面

对齐 handoff acceptance flow，前缀 `simulanka`：

```text
simulanka init <path>
simulanka graph node create  --type T --name N [--parent S] [--attrs k=v]
simulanka graph port create  <node> --name N --direction in|out --type T
simulanka graph connect      <src.port> <dst.port> --type T
simulanka graph inspect      <selector>
simulanka graph doctor       [--repair]
simulanka graph export       --format json
simulanka graph import       --file <bundle>
simulanka graph patch apply  --file intent.json [--dry-run]
simulanka graph migrate      [--dry-run]
simulanka graph index rebuild
```

每个写命令在内部组装 `PatchIntent` 调 `apply_patch`。

## 8. `graph doctor` 检查

1. `manifest.content_hash` 与现盘一致。
2. `parent_id` 缓存与 `contains` 边一致。
3. 所有 edge/port 的引用 id 都存在、方向匹配。
4. SQLite 索引计数与实体文件一致。

`--repair` 只重算可派生项（索引、parent_id 缓存）；实体文件被改坏只报告不修。

## 9. 实现节奏

每一步 end-to-end 跑通一条 acceptance flow 才推进下一步：

1. ✅ `simulanka init` —— 目录树 + manifest。
2. ✅ `Node` 模型 + `entity_store` + `events` + `manifest` 哈希更新；`apply_patch` 只支持 `create_node`；`simulanka graph node create` 跑通。
3. ✅ 类型注册表 + validator；`graph inspect`。
4. ✅ Port + Edge + `connect`；`data_flow` 端口方向约束。
5. ✅ `export` / `import` / `index rebuild` / `doctor`。
6. ✅ `migrate`。
7. ✅ FileRegistry（文件登记 + 布局策略）。
8. ✅ 研究语义层 atoms + 语义边（见 §5.1）。
9. ✅ PyTorch importer（见 §5.2）。
10. ✅ Run executor（见 §5.3）。
11. ✅ Agent wrapper（见 §5.4）。
12. ✅ `update_attrs` op + 异步执行（见 §5.5）。
13. ✅ `run agent --detach`（detached 模式下也跑 workspace diff，见 §5.5）。
14. ✅ TaskContract + 第一等 `task` 节点（goal + allowed_outputs + budget + acceptance，见 §5.6）。

下一步：前端 canvas 可视化 MVP **已落地**（§12，2026-05-20/21 六轮迭代，见 `frontend/` + `src/simulanka/server/`）。多 attempt 比较等约定层议题落到 agent 工程，不进 kernel。

仍在 Alpha 范围外：artifact store、前端 canvas、file binding 的 snapshot/generated 模式。`fs_path` 类 attrs 留给后续 `attrs_model` 扩展。

## 10. 已知限制（不在 Alpha 修复）

FileRegistry 当前刻意保持简单，存在两处已被识别的限制，留待真实用例驱动后再演进：

1. **不支持多分枝实验布局**。`file create --kind X --name Y` 永远把文件放到 kind 的固定目录（`src/`、`docs/` 等），无法表达"branch A 和 branch B 各有自己的代码/日志/结果"。
2. **没有 `dataset` 类别**。`baseline` 当作通用外部引用顶着，但数据集的特性（体积大、跨实验共用、远程、有版本）当前没承载。

**根因**：`FileKindSpec.dir_name` 把"语义（这是代码/文档）"与"位置（放在 src/）"耦合在一处。多分枝场景下语义不变，位置应跟作用域走（project / experiment / run）。

**演进路线**（仅在触发条件出现时执行）：
- 把 `dir_name` 改为 kind 内相对子目录。
- `file create` 增加 `--scope <selector>` 参数，路径 = `{scope.fs_path}/{spec.subdir}/{name}`；默认项目根，行为向后兼容。
- 注册 `experiment` / `run` 节点类型。
- 给 spec 加 `scopable: bool`；`artifact` / `dataset` 等设为项目级，不允许 scope。
- 写一步 schema 迁移把已有 file 节点路径含义升级。

## 11. 已确认

1. CLI 框架：**typer**。
2. ID：**ULID + 前缀**（如 `nod_01HX...`）。
3. 项目定位：默认 `$PWD` 向上找 `.simulanka/`；`SIMULANKA_PROJECT` 环境变量覆盖。不加 `--project` 开关，YAGNI。
4. `.gitignore` 模板：排除 `indexes/`、`cache/`、`logs/`；保留 `manifest.json` 与 `graph/{nodes,edges,ports,events}/`。`init` 时如目标内无 `.gitignore` 则写入；已有则不动。项目根同理：无 `.gitignore` 则写入排除 `.simulanka/` 的片段（§13.6 后 `.simulanka/` 内嵌 checkpoint git 仓，外层用户仓本就无法按普通文件跟踪它），已有则不动。

## 12. 前端可视化

> **状态（2026-05-22）**：MVP 已落地（六轮迭代，见 `frontend/` + `src/simulanka/server/`）。§12.1–12.7 是当时遵循的设计原则，保留作 rationale；§12.8 的"做/不做"清单已按实际落地情况更新。
>
> ⚠️ **§12.7/§12.8 的"前端只读、编辑留 v2"已被 §13 部分突破**：边的连/拆/agent-ghost 现已可在前端写（§13.3 的 `POST/DELETE /edge` + LiteGraph 交互）；仍只读的是**节点 / attrs 编辑**，那些继续走 CLI。

**目的**：让研究者在浏览器里实时看到 Research Graph 与其内部 model 子图，肉眼验证 importer 抓得对不对、experiments / runs / files / lineage 的形状。导入器深挖（torch_export 覆盖度）等这一步落地后再继续——该前提现已满足。

### 12.1 第一原则：统一 node-edge-port 渲染器

Simulanka 的数据层已经统一在 node / edge / port 三个原语上。model 内部结构本质上是 Research Graph 的一个子图（root = model 节点），不是另一种东西。

由此推论：
- **一套渲染器**，只认 `{nodes, edges, ports}` 一种 payload。
- **一个 endpoint**，model 子图和 RG 全图共用，只是 root 节点不同。
- 不为 model 单独造"模型可视化"组件；要加新视图，先问能否复用同一个渲染器换 root。

### 12.2 数据契约

前端拉取的 payload：

```jsonc
{
  "root": "nod_01HX...",          // 当前视图根
  "nodes": [
    { "id", "type", "name", "parent_id?", "attrs", "ports": ["por_..."] }
  ],
  "edges": [
    { "id", "type", "src", "dst", "src_port?", "dst_port?", "attrs" }
  ],
  "ports": [
    { "id", "node_id", "name", "side": "in"|"out", "attrs" }
  ]
}
```

后端按 `root` 与一个 `depth` 参数返回子树 + 其中节点参与的边（含跨边界边，见 §12.4）。**深度懒加载**：双击下钻时再请求下一层；不一次性吐整张图。

### 12.3 交互模型：双击进入子图

所有节点统一为"折叠嵌套 + 双击进入子节点"。没有第二种心智模型。

- 节点是容器（`contains` 出边非空）就允许双击下钻；面包屑回溯。
- 自由 pan、滚轮缩放，深色主题。
- 布局算法（hierarchical / DAG）可以按节点类型自动选默认，但**交互入口只此一种**。

### 12.4 跨层连边：边界端口投影

进入子图后，原本指向子图外部的边需要落到某个可见位置。

**做法**：当前下钻视图的边框上画一圈**虚拟端口**；越界边在虚拟端口处收尾，端口上标 `← from ext.X` / `→ to ext.Y`。点击虚拟端口跳到对端所在视图。

**为什么不用 UE5 tunnel 节点**：tunnel 节点会污染图数据（凭空多出来一类只为视觉存在的节点）。边界端口是纯渲染层概念，不进 graph state。

实现要点（开工前再细化）：
- 进入子图 `S` 时，找所有 `src ∈ S, dst ∉ S` 与 `src ∉ S, dst ∈ S` 的边。
- 按 dst（或 src）的方向把这些边分配到 `S` 边框的左/右侧；同一外部对端聚合为一个虚拟端口。
- 虚拟端口的稳定 id = `f"ext:{external_node_id}:{direction}"`，避免重渲染时跳位。

### 12.5 视觉/交互风格：ComfyUI / UE5 Blueprint

直接对标这两套范式：
- 节点矩形带 title bar（type + name）。
- 输入端口左、输出端口右。
- 贝塞尔连线。
- 深色画布、grid 背景。
- 缩放时节点细节渐进显示（远缩看 type，近缩看 attrs/ports）。

> **最终美术方向（2026-06-11 用户定）**：交互范式不变（仍 ComfyUI/UE5 节点图 UX），但视觉皮肤最终走**原神
> 童话风**（呼应 Simulanka 之名）；现阶段不做，功能/稳定性优先，皮肤轮与 §13.6 面板开发同捆时再设计。

### 12.6 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 渲染引擎 | **LiteGraph.js** | ComfyUI 同款底层；canvas 原生；内置子图、端口、连线、双击下钻；不造轮子 |
| 前端框架 | **SvelteKit** | HUD / 工具栏 / 侧栏；比 React 轻；代码更像配置 |
| 后端 | **FastAPI** | Python，与 kernel 同栈；不增加技术面 |
| 实时通道 | **SSE** | 单向推送够用；比 WebSocket 简单 |

LiteGraph 的 quirks（JS 非 TS、API 偏旧）可控。需要的扩展点：自定义节点类型注册、虚拟端口（§12.4）、payload 适配层。

### 12.7 实时通道

- 后端 watch `.simulanka/graph/events/` 的 mtime（或新事件文件追加）。
- 有新事件就通过 SSE 推一条 `{event_id, affected_nodes, affected_edges}` 给前端。
- 前端按 `affected_*` 增量重取相关子图，不全量刷新。
- **不双向写**：MVP 阶段前端只读。编辑/创建仍走 CLI；交互式编辑留待 v2。

### 12.8 MVP 范围（与不做）

**已做**：
- 后端 `GET /graph?root=...&depth=...` + `GET /events`（SSE）+ `GET/POST /ui/positions`。
- 前端：LiteGraph 渲染 + 双击下钻 + 面包屑（祖先链重建）+ 跨层边界端口 + 节点属性侧栏（NodeInspector）。
- dagre 自动布局 + 按视图持久化节点位置（落 `.simulanka/ui/positions.json`）。
- SSE 增量刷新（按 affected 节点交集判断是否 reload）。
- 接现有 `.simulanka/` 项目就能跑（含 importer 已经导入的 DS_r baseline）。

**不做**（留 v2）：
- 前端编辑（创建节点、连边、改 attrs）。
- 大图性能优化（>10k 节点的虚拟化渲染）。
- 主题切换、可访问性、多语言。
- 鉴权 / 多用户。本来就是单用户本地工具。

## 13. 人画连线 + agent 核对

> 一串 grill 设计会话（2026-05-22 → 2026-06-08）的产物。**完整推导、证伪记录、已否决路径**归档在
> [`docs/archive/s13-human-drawn-edges.md`](archive/s13-human-drawn-edges.md)；本节只保留当前架构与落地状态，
> 方便接手。dead-end 见 §13.4——勿重走。

### 13.1 核心架构

**机器只做 100% 确定的事（结构 + 端口）；需要"理解"的事（边）人画、agent 提议、trace 附议、人裁。**
跨组件数据流藏在有状态的顶层 `forward`（视频循环 + memory bank）里，torch.export/fx 抓不全（data-dependent
控制流 2026 未解），"完全自动连通图"不可达，硬追等于重造 torch.fx（已否决，见 §5）。故沿"确定性 vs 理解"劈开：

- **结构 + 端口** → importer 全自动（`named_modules` + 端口）。机器确定。
- **边（谁喂谁）** → 主线 = **agent 读源码提议** ghost 草稿；**trace 退为深层 verified 区的确定性附议**（只确认、
  绝不否定）；**人最终裁**。人画/审线 = 被迫理解架构（生成效应），正是本项目使命（让研究者理解 baseline），
  不是产出一张图。

### 13.2 数据模型（schema/kernel 零改，语义全进 attrs）

- **`port.attrs`**：`confidence` ∈ {`verified`（真前向观测到，arity/shape 可信）, `inferred`（仅签名推断、未验证）}；
  `label`（参数名/kwarg/dict key）；`shape`（单张量 verified 槽才记）。结构端口名 `in`/`out` 永远在，多 IO 追加
  `in1`/`out1`…。**唯一真风险 = 端口标错让用户自信学错，故宁可标 inferred 不假装 verified。**
- **`edge.attrs`**：`source` ∈ {`trace`, `user`, `agent`}（前端三色区分）；`status`（`proposed` = ghost 灰虚线）；
  `verdict` ∈ {`unconfirmed`, `correct`, `wrong`, `uncertain`, `disputed`} + `verdict_by` ∈ {`trace`, `agent`, `user`}
  （`user` 2026-06-11 加：人拒 ghost = `verdict=wrong, verdict_by=user, verdict_note=必填理由`，`status` 仍 `proposed`
  进分歧队列，不直接删边——讨论后人确认拒绝才删，见 §13.6）+ `verdict_note`；`citation`（agent 提议必带的源码出处，无则 skip）；`evidence_locality` ∈ {`in_method`,
  `cross_method`, `cross_state`}（出处局部性，核对按它加权——跨态的 cited 边更可疑）；`output_slice`（§13.3 多输出，
  一个输出的哪一片走这条边，如 `[-1]`/`[:-1]`）；`shape_check`（连线当下本地算，`match`/`mismatch`/`unknown`，只提示不硬拦）。
- **两条铁律**：① **trace 不对称——只确认绝不否定**（trace 只看 tensor 谱系，对状态/标量/控制流全盲；假 `wrong` =
  "自信学错"灾难，故 trace 无权说 wrong，只读源码的 agent 有）；② **agent 可对 trace-`correct` 提异议 → `disputed`**
  （两台仪器打架、该被看见，不被静默覆盖）。
- **trace verdict 物化（2026-07-06 裁定）**：importer 建 trace `data_flow` 边时即盖 `verdict=correct, verdict_by=trace`。
  此前只标 `source=trace` 不盖 verdict，真图彩排实测面板显示 `verdict=None`——明明观测过却显示未裁，是撒谎；且不物化
  则「agent 质疑 trace」的 disputed 桶无从机械判定。2026-07-07 已实现（importer 一处 + 既有图 backfill 不做，新导入生效）。
- **agent 性格契约：少而准**——只画能从源码直接指依据的边、每条 ghost 必带 `citation`；要靠猜控制流/状态的不画、只标缺口。
  把"宁可漏不可错"从 trace 复制到 agent。

### 13.3 落地状态

| 件 | 状态 | 代码 |
| --- | --- | --- |
| 端口生成：多输入/输出结构端口 + confidence/label/shape | ✅ | `importer/torch_export.py` |
| 前端连/拆边 + 形状提示（连 = `CreateEdgeOp`、拆 = `delete_edge`） | ✅ | kernel `delete_edge` · `POST/DELETE /edge` · `frontend/` |
| agent 提议 ghost：读源码、cite-or-skip、少而准、dedup | ✅ spike | `propose.py` · CLI `simulanka propose <model>` |
| 真 SAM2 命门 B：opencode 真跑（导航过 forward 桩、10 边逐行属实、cross_state 边正确标） | ✅ 验证 | — |
| 多输出端口 = 切片落在边（D4） | ✅ | `propose.py`（端口映射 + `output_slice`）· `frontend/`（切片标签） |

> **命门 B 的实证结论**：机制**准但不穷尽**——免费模型 `deepseek-v4-flash-free` 在真 SAM2 上产出准确诚实的边，
> 但会漏控制流分支 + 多尺度直连（人凭领域知识当场补 `image_encoder→mask_decoder` 高分辨率 skip）。验证通过 = 产出
> 准确诚实，**≠ 穷尽**；正实证"agent 提议、人处置"的价值。

### 13.4 已否决（dead-end，勿再试；证据见归档）

- **GitNexus / 静态分析承担数据流边**——schema 无数据流边；`self.<submodule>(...)` 是 `nn.Module.__call__` 间接调用，
  静态解析不出（真 SAM2 实测三连）。自建 AST def-use 也会在 SAM2 视频循环/跨 pass 处崩。
- **propose 只读顶层 `forward`**——SAM2 顶层 `forward` 是 `NotImplementedError` 桩，真编排摊在 `SAM2Base` 的 5 个
  私有方法、跨两文件、靠每帧 memory bank 串。改为"指向 model 类 + 仓库让 agent 自由导航到任意深度"。
- **importer 递归拆容器 / agent 现造端口** 来表达 slice 分流——违反"结构归机器、理解归边"那条线（slice 是理解，不是
  机器确定的结构事实），且 `[:-1]` 切片 ≠ 单 index。改用 `edge.attrs.output_slice`（D4），importer/schema 不动。

### 13.5 待办 / 推迟

> **分工（2026-06-11 重定，替代旧的前后端切分）**：**Codex = agent 工程线**（`propose.py` + agent prompt/harness），
> **Claude = 其余全部**（kernel/schema/importer/frontend/server）。理由：§13.5 的活几乎都纵切前后端，按层切会在
> wire 字段上反复打架；agent 线边界天然窄而稳。三条规矩：① 契约冻结点 = §13.2 的 edge/port attrs，Codex 需要新增
> attrs 字段或动 schema/kernel 须先过设计讨论；② `docs/design.md` 单写者仍是 Claude；③ 交叉审保留。

- **核对-讨论交互**：Claude 侧全部落地（2026-06-12，含讨论端点+聊天面板，见 §13.6 末条）；开场 prompt
  Codex 已交付并合入 main（2026-07-03 合 `a1733b1`：逐边 triage、直指人理由、保留不确定性、cite-or-skip）。
  余：核对 pass（Codex）+ 真图端到端彩排（双方，`deepseek-v4-flash-free`）。
- **命门 C**（Codex）：importer→图→propose **live 串联**（真 SAM2，用导入图的端口词表而非手工提供）。
  本质是"propose 改用导入图的端口词表"，只*读*图状态、走现有 API。
- **agent 工程**（Codex）：prompt/导航策略；opencode harness 坑（非交互卡权限门死锁、`run` 须 `--print-logs` 否则挂起、
  导航策略 run 间随机）；`evidence_locality` 由 propose 推结构跨度 + agent 显式标跨态。见 [[project_deferred_agent_work]]。

### 13.6 核对-讨论交互（2026-06-11 grill 定稿，待实现）

> 完整推导归档在 [`docs/archive/s13-human-drawn-edges.md`](archive/s13-human-drawn-edges.md) §13.6。

- **形态 = 前端实时聊天面板；底层 = opencode session 续聊**。spike 验证：`opencode run -s <id> --format json`
  可非交互续接同一会话——多轮实时 ≠ 攻 TTY 死锁，每一发都是已验证可靠的非交互单发，多轮 = 共享 session id 的
  单发序列。harness 归 Codex（量级从「解决交互式问题」缩为「session 续聊 + JSON 解析」）。
- **单位 = 一批一场会话**。点「核对」→ agent 先跑核对 pass（裁 `unconfirmed`）→ 全部分歧进同一会话；理由：一个
  架构性误解常同时解释多条分歧，agent 要有全局上下文。结论逐条落到各自边上，聊完才算批完。
- **分歧集**：① 人拒的 ghost（必填理由，见 §13.2 `verdict_by=user`）；② 核对中被 agent 裁 `wrong`/`uncertain`
  的人画边；③ `disputed`（agent vs trace）。人可手动把任意边拉进讨论。
- **真实/意图两域 + 写权矩阵**（不立分支/新实体——它是现有 attrs 的*写者维度*）：
  - **真实域**（只反映当前代码）：importer 结构+端口、trace verdict、`shape_check`、port `confidence` ——
    只有机器写；人和 agent 都不能伪造。
  - **意图域**（人机对齐工作区）：ghost、agent verdict/note、人画的边、人的裁决、讨论 —— 人+agent 写，内部分层：
    **agent 讨论中可实时改自己的层**（更新自己的 verdict/note、撤回自己未被接受的 ghost、新提 ghost，画布经 SSE
    实时变）；**实边连/拆/接受、推翻人的判断，永远只能人点**（「人最终裁」铁律）。人画的实边也在意图域——它是人的
    当前理解而非被验证的事实，这正是它需要被核对的原因。
  - agent 在会话里**不拿写工具**：回复中嵌结构化 op 块，服务端解析、按写权矩阵过滤后经 `apply_patch` 落库——
    kernel 仍是唯一写者。op 块协议 = Claude/Codex 接缝契约，双方共定。
- **生成效应落点**：人提交分歧**必填短理由**（进 `verdict_note`，`verdict_by=user`）——「为自己的判断辩护」即
  学习时刻，也给 agent 可反驳的靶子；讨论开场即针对理由，不从零猜。结论蒸馏回该边 `verdict_note`；全文
  transcript 留在 opencode session（可 `opencode export`），不进图。
- **撤回兜底（agent 拿实时写权的前置）**：存储层现无任何 undo —— `.simulanka/` 内嵌**独立 git 仓**（与 baseline
  代码仓历史隔离；`indexes/` `logs/` `cache/` 入 .gitignore），每次 kernel commit 自动 git commit，讨论每轮起点
  打 tag；恢复 = git checkout + `graph index rebuild`。实现裁定：惰性激活——`.git` 不存在时 apply_patch 零开销跳过，
  API server 启动时 `ensure_repo` 点亮（agent 写权只经 server 进来，兜底必先于风险存在；kernel 测试不付 git 税）。
- **kernel 增量（本场拍板的契约变更）**：① `UpdateAttrsOp.target` 扩到 edge selector——即 §13.5.3 当年推迟的
  「edge-attr 更新 op，异议回写时再加」，到点了；② `verdict_by` 增 `user`（§13.2 已更新）。
- **实现切缝**：Claude = kernel op 扩展 + server 端点 + 前端（选中 port 浮 ghost、拒绝必填理由、讨论面板、逐条
  落边）+ git checkpoint；Codex = 会话 harness。Claude 侧可先行到「分歧集就绪 + 面板」，不被 harness 阻塞。
  实现裁定：「浮 ghost」落在**选中节点**粒度（面板内逐条带端口名）——LiteGraph 里端口圆点的点击命中框就是拉线
  手势的起点，抢同一命中框做选中会打架；被拒 ghost 画布上染红色虚线与未核 ghost 区分。
- **CLI-first bridge（2026-06-12，Codex）**：浏览器内嵌终端暂缓（无 xterm.js 时 TUI 控制序列裸露）；opencode 留在
  真终端跑，sidecar 旁录 `transcript.txt` / `ops.jsonl` / `events.jsonl` 至 `.simulanka/agent/opencode/<时间戳>/`
  （平面文件，FileRegistry 刻意旁路，同 `changes.json` 先例）；ops 仅是 intent，server 按写权矩阵过滤后经
  `apply_patch` 落库。前端第一版读 sidecar 文件即可；xterm.js 属后期产品化步骤。
- **讨论端点 + 聊天面板（2026-06-12，Claude）**：`POST /discussion/start`（分歧集快照入开场上下文、
  `tag_checkpoint("discussion-start")`、开 opencode session）/ `POST /discussion/message`（续聊）/ `GET /discussion`；
  每轮回复经 `server/agent_ops.py` 写权矩阵闸：`set_verdict`（不得覆人裁）/ `propose_edge`（无 citation 即拒）/
  `withdraw_edge`（仅自己未被接受的 ghost），server 强制 `verdict_by=agent`、`source=agent`，逐 op 落库（坏 op 报回
  聊天不毁批）。op 协议契约 = issue #2；开场 prompt 文案占位在 server（`OPENING_TEMPLATE`），编辑权归 Codex。
  前端 DiscussPanel 挂核对面板内，applied/rejected chips 让矩阵裁决可见；会话经状态文件
  （`.simulanka/agent/discussion.json`）跨重启续聊，transcript 不进图（在 opencode session 里）。

## 14. 科研主循环（2026-07-06 grill 定稿）

> 从「想改进 baseline」出发的完整循环：分析 → 计划 → 落图 → 执行 → 蒸馏 → 下一轮。
> 此前只有零件（§5.1 原子、§5.5 runner、§5.6 TaskContract），本节给整体拓扑与分工。

### 14.1 控制拓扑：agent 驱动系统

**缺省拓扑翻转**：研究工作由现有 agent harness（Claude Code / Codex / opencode）执行，
Simulanka 退成**图内核 + 写权闸门 + 工具面（CLI 先行，MCP 薄适配后置）+ 程序知识（skills）**。
不再维护自有 drive-the-agent 管道（propose.py 单发形态即此类，真图彩排首步即断、§13.5.4 改形
一个月未落地——自有管道跟不上 harness 迭代是结构性的，不是执行力问题）。「系统驱动 agent」
仅保留于人面同步交互（§13.6 讨论面板）。

**三条不变量**（翻转后防「图退化成 agent 日记」）：
1. kernel 唯一写者 + 写权矩阵照旧；
2. diff / acceptance / metrics 提取永远系统侧执行——agent 可触发、不可代笔结果；
3. task / run 仍是第一等图实体，agent 经工具立项，不绕图。

**确定性边界原则**（贯穿全循环）：凡能做成确定性工具的（成图、diff、验收、evidence 骨架提取、
简报导出、计划落图）一律做成工具，agent 只调用；工具可信 ⇒ 结果可信。此为 §13「机器只做
100% 确定的事」向全循环的推广。

### 14.2 循环形态与角色

```
分析者(最强外部模型) ──计划文件(prose+结构块)──▶ ingest(确定性) ──▶ 图(proposed 态)
     ▲                                                                │ 人异步批(画布)
     │ 简报(确定性导出: open claims/contradicts/近期 run+metrics/预算)   ▼
     └── evidence 骨架(机器提取) ◀── run end(系统测量) ◀── harness 执行 ◀── 操作员建 task/起 run
```

- **分析者**：只产出计划文件 = 自由 prose（推理原文）+ 机器可解析结构块（hypotheses /
  experiments / 语义边 / **escalate 动词**）。文件原生、零工具调用污染、harness 无关
  （GPT 类外部模型同样能写）。
- **落图 = 确定性 ingest 工具**，含语义边端点校验（§5.1 约束）+ 写权闸。落图状态一律
  `proposed`（分析者提议）。**否决过**「中模型秘书翻译落图」：格式严则解析器足矣，格式松则
  图成秘书转述——两头取一，答案都是解析器。
- **人批在落图后、画布上**（§13 核对习惯推广到研究原子），非阻塞（见 14.3）。图是文档的
  **有损投影**（结构块双向可逆、prose 单向驻留文件）⇒ 前端硬需求：节点一键深链文档出处。
- **操作员（中等模型秘书）**：循环的机械流——跑 ingest、修机械校验错、按 FileRegistry 归档、
  从计划建 task、起 run、回写状态。可触发工具，**不得代笔语义**。
- **执行括号**：`run begin`（建 run 节点 + worktree）→ harness 干活 → `run end`（系统算
  diff、跑 acceptance、从 metrics 机械提取 evidence 骨架 `source=machine`）。系统在括号两端
  测量，替代全程驾驶。
- **蒸馏归分析者**：supports / contradicts 边、hypothesis 定性、claim 升降 = 下轮分析者
  开场第一动作（先审旧账再开新篇）。执行者不给自己阅卷。claim 状态维持查询时算（§5.1）。

### 14.3 可信分级与「人裁至上、非必经」

| 层 | 内容 | 谁验 | 成本 |
| --- | --- | --- | --- |
| 构造可信 | diff、metrics、acceptance、成图 | 确定性工具，免验 | 零 |
| 部分可信 | 过程、代码改动、中间结论 | 便宜模型快速交叉检查，速度优先 | 低、封顶 |
| 须强验 | evidence→claim 语义判断、轮次结论 | 分析者审旧账 + 人异步抽查 | 高、集中 |

- **人裁至上、非必经**：人的裁决一旦给出即最高权威（写权矩阵已保证 agent 覆盖不了
  `verdict_by=user`），但人的缺席不阻塞循环——proposed / 部分可信之上照常推进，可信级别
  如实记录。**精确界定**：此表述适用研究域；模型结构域（§13.6）实边接受仍只能人点，原铁律不动。
- **可信度沿血缘查询时实时算**：claim 坐在未强验的中间结论上，展示可信级 = 全链最低档。
  不新增同步机制，图即计算基础（同 §5.1 claim status 先例）。

### 14.4 刹车（自主循环的护栏）

必要，细节推迟。已定两条方向：① **分析者主动叫停**——结构块含 escalate 动词，操作员见之
必停（格式后果现在生效，进 ingest schema）；② **时长/成本硬帽**（如每日工时上限）。断路器
参数（连续 N 轮无人查看、M 次无进展）后调。

### 14.5 打包分工与 openspec 划界

- **进系统**（确定性/策略）：kernel、storage、schema、ingest、evidence 提取器、简报导出、
  diff/acceptance、checkpoint、server/frontend。
- **工具面**：CLI 现成先用（彩排实证 harness 驱动 CLI 顺畅）；MCP 为薄适配层，摩擦出现再建。
- **skills**（程序知识，markdown 最耐久）：分析者格式说明书、操作员循环流程、成图 manifest
  编写法（彩排流程即底稿）、执行纪律。agent 工程线（skills/prompt）归 Codex（分工不变，
  内容从 propose.py 管道改道为 skills + 工具面，见 issue）。
- **openspec 只用于 Simulanka 自身开发**（强模型写 spec、弱模型施工），不套研究循环——
  研究循环有自己更富的 schema。

### 14.6 实施切片（供后续会话/Codex 按规格施工）

① plan 结构块 schema + `plan ingest`（规格见 §14.7）；② `run begin/end`
执行括号；③ evidence 骨架提取器；④ 简报导出 `brief export`；⑤ skills 四篇；⑥ 可信度血缘
查询 + 前端染色（后置，可与皮肤轮同捆）。①–④ 为确定性工具，规格清晰后弱模型可施工。

### 14.7 计划文件格式 v1（切片①可执行规格，2026-07-06）

**文件形态**：Markdown，自由 prose（分析者推理原文）+ **恰好一个** ```` ```simulanka-plan ```` 围栏块（JSON）。
0 个或多于 1 个块 = ingest 拒。文件经 FileRegistry 归档（kind/路径由 FileRegistry 裁，实现时定）。

**块 schema**（两段式，对应「先审旧账、再开新篇」）：

```jsonc
{
  "distill": {                    // 审旧账：引用已存在的图 id；new_claims 是唯一的铸造例外
    "new_claims": [{"lid": "c1", "body": "...", "status": "open|supported|refuted"}],
                                  // 蒸馏的核心产出就是新结论——没有它分析者无处铸造 claim（干跑咬出）
    "edges":  [{"type": "supports|contradicts", "source": "<evidence id>",
                "target": "<claim|hypothesis id> | c1", "note": "..."}],   // target 可引 new_claims 的 lid
    "claims": [{"id": "<claim id>", "status": "open|supported|refuted", "note": "..."}],
    "hypotheses": [{"id": "<hypothesis id>", "verdict": "...", "note": "..."}]   // 定性，词表沿用 §13.2
  },
  "plan": {                       // 开新篇：lid = 块内本地 id，ingest 时解析为新节点
    "questions":   [{"lid": "q1", "body": "..."}],
    "hypotheses":  [{"lid": "h1", "body": "...", "addresses": "q1 | <graph id>"}],
    "experiments": [{"lid": "e1", "goal": "...", "tests": "h1 | <graph id>",
                     "tasks": [{"lid": "t1",     // 可省，缺省按序派生 t1/t2/…
                                "goal": "...", "allowed_outputs": [], "acceptance": "...",
                                "budget_time_seconds": null}]}]   // 字段 = §5.6 TaskContract 原词表
  },
  "escalate": null                 // 或 {"reason": "..."}——分析者叫停（§14.4）
}
```

**`plan ingest <file>` 行为**：
1. 解析唯一围栏块 → pydantic 校验；引用解析：图 id 直接 resolve（失败=拒），lid 仅限块内引用。
2. 语义边端点类型按 §5.1 校验；**单 PatchIntent 原子落地**——计划是整体一致的叙事，半个计划落图
   =不一致状态，部分失败即整体拒+报告，分析者改文件重发（有意区别于 op-block 的逐 op：那是交互式聊天，这是文档）。
   块内 lid 引用（plan 段互引 + distill 边连 new_claims）用 §3 的 `@ref` 机制落成一个 intent。
3. 落图标记：新节点/边 attrs `source="analyst"` + `plan_file` + `plan_lid`（前端深链文档出处用）；
   experiment `status=planned`。distill 的 claim 状态改写是**分析者的判断记录**（写者=分析者，与 §5.1
   「支持/反驳计数查询时算」不冲突——计数与可信级仍实时算，status 是判断快照）。
4. `escalate` 非空 → 建 `note` 节点（attrs `kind=escalate`, `body=reason`）；**操作员契约：见 escalate 即停轮**。零新类型。
5. 计划文件本身登记为 `file` 节点；同一文件重复 ingest = 拒（判据：该注册路径的 file 节点已存在；
   幂等/修订流 v2 再议）。

**落图布局与铭章**（2026-07-07 干跑裁定）：
- FileRegistry 新增两 kind：`plan` / `brief`，共享顶层 `research/` 目录，`name_prefix` 分别
  `plan-` / `brief-`（一个目录、两类文件，按前缀即可分辨轮次产物）。
- ingest 为每份计划建**一个 directory 节点**（`research/` 之下，名=计划文件 stem），块内新原子
  （question/hypothesis/experiment/claim）落其中、**名=lid**——lid 天然块内唯一，跨轮撞名被
  per-plan 目录隔离，前端还白得一层「按轮下钻」。task 节点父=其 experiment。
- **tasks 落为一等 `task` 节点**（attrs 平铺 §5.6 契约字段），由 ingest 直接 `create_node`
  （`task create` CLI 不收自由 attrs，且操作员转录契约=已死的翻译步）；操作员对 task 只做
  `run begin --task <id>`，无一字转写。
- **actor 铭章**：ingest 的 PatchIntent `actor="analyst"`（工具只是笔，作者是分析者；attrs
  `source` 与 created_by 由此对齐）；操作员经 CLI 的机械操作应带 `--actor operator`（写权矩阵
  把 operator 归 agent 类，不得冒 user）。

**开放点**（记录不阻塞）：人批 ratified 标记的具体 attr（等前端整合）。
（对偶性已由 §14.8 简报块锁定；2026-07-07 干跑在真 SAM2 图上验证：plan→ingest→run→evidence→
brief→次轮 distill 全链闭环，铸出的 claim/supports 即上文 new_claims 语义的来源。）

### 14.8 执行括号与收尾工具（切片②③④可执行规格，2026-07-07）

**② `run begin` / `run end`（执行括号）** —— 替代「系统全程驾驶」，系统只在两端测量：

- `simulanka run begin --task <sel> [--parent <dir>] [--name <n>] [--workdir <path>]`：
  建 `run` 节点（`status=running`、`started_at`、`workdir`；`--parent` 缺省 = task 的父 experiment，
  containment 即表达 run↔experiment 归属，不另连 `part_of`）；镜像契约（§5.6 同款：`contract` attr +
  `<run_dir>/contract.json` 快照 + `fulfills` 边）；记录 diff 基线 = workdir 的 git `HEAD`，
  begin 时已有脏文件则记 `baseline_dirty=true` + 脏文件清单（诚实降级，不装干净）。
  清单必须 `git status --porcelain -uall` 取**文件粒度**——porcelain 默认把未跟踪目录折叠成一行，
  end 时的 diff = end 态清单 − begin 态清单（集合差），折叠粒度会把既有脏文件算到 run 头上（干跑实测）。
  打印 run id / handle，harness 自持（不设「当前 run」环境态——并发 run 显式传 id 更稳）。
- `simulanka run end <run> [--status done|failed] [--metrics <file>]`：系统侧依次——
  ① 对基线算 diff（复用 §5.4 wrapper 的 workspace diff 路径）；② 按 contract.json 快照跑
  acceptance（`sh -c`，log 入 run_dir）；③ 写 `contract_check`（判定优先级同 §5.6）；
  ④ metrics 存在则触发③的 evidence 提取；⑤ `ended_at`/`duration_seconds`/`status`。
  已 end 的 run 再 end = 拒（幂等边界同 detached finalize 先例）。
- **孤儿 run**（begin 后 harness 崩了没 end）：无进程可查（run=会话非进程，/proc 特判不适用），
  v1 由人工 `run end --status failed` 收尾 + doctor 增一检：`running` 超 `budget.time_seconds`
  （无预算则 24h）即提示。

**③ evidence 骨架提取器**（`run end` 内触发，也可独立 `simulanka evidence extract <run>`）：

- 约定：metrics 文件 = 平铺 JSON 标量字典（`--metrics <file>` 或 workdir `metrics.json`；
  task 的 `allowed_outputs` 应涵盖它）。
- 产出：`evidence` 节点（parent=run，§5.1 允许），attrs `source="machine"`、`metrics=<dict>`、
  `metrics_path`、`body`=一行摘要；`produces` 边 run→evidence。**不连 supports/contradicts**——
  语义判断归分析者（§14.2），执行者与提取器都无笔。
- 解析失败/非标量 → 不造 evidence，run 记 `metrics_error`（宁可缺不可假）。

**④ 简报导出 `brief export`**（分析者开场输入，ingest 的逆操作）：

- 输出 = markdown：prose 头（一段自动概览）+ **一个 ```simulanka-brief``` JSON 块**，与 §14.7
  计划格式镜像对偶——**块里给出的图 id 就是计划块 `distill` 段可直接引用的 id**。
- 块内容（全部确定性、按 id 排序，同图态必同输出）：open 的 question/hypothesis/claim（含
  verdict/status/body）；近期 run（id、task goal、`contract_check`、duration、**evidence 条目
  含其节点 id + metrics**——没有 evidence id 下轮 distill 的 supports/contradicts 就无的放矢，
  对偶性会在此断裂，干跑实测）；未处理的 escalate note；§13 分歧集条数（一行，不展开）；
  预算消耗小计（所列 run 的 wall-clock 和）。
- **open 的判据**（v1，全部查询时判）：claim = `status=="open"`；hypothesis = 无 `verdict` attr
  （distill 下过 verdict 即视为已结）；question = 全列（v1 无关闭机制）。「近期 run」= 非 `done`
  experiment 名下的全部 run（experiment 的 status 由操作员在其 tasks 的 run 收尾后翻 `done`，
  属机械流，写进操作员 skill）。
- 工具 PatchIntent（如有写入）与 evidence 提取器、`run begin/end` 一律 `actor="system"`
  （三不变量：测量永远系统侧）。
- `--out <file>` 或 stdout；文件走 FileRegistry `brief` kind（§14.7 已裁：`research/` 下 `brief-` 前缀）。

实现均为确定性工具（§14.1 边界），规格照施工即可；kernel/schema 零改动（全部现有原子与边型）。
