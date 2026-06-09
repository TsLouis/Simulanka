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

- `id`: ULID 带前缀 `nod_` / `edg_` / `prt_`。
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

**CLI**：`simulanka import torch --build pkg.mod:fn --name N [--parent /dir]`

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

**Detached + 契约**：`start_agent_run --task` 在 launch 后立刻镜像契约到 run 节点，把 `task_node_id` 写进 `agent_meta.json`；`finalize_agent_diff` 跑完 diff 之后自动跑 `check_contract`（acceptance 命令在 host 进程的 finalize 阶段同步执行，不是在 detached subprocess 里）。再次 finalize 看到 run 节点已有 `contract_check` attr，跳过——幂等。

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
4. `.gitignore` 模板：排除 `indexes/`、`cache/`、`logs/`；保留 `manifest.json` 与 `graph/{nodes,edges,ports,events}/`。`init` 时如目标内无 `.gitignore` 则写入；已有则不动。

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
  `verdict` ∈ {`unconfirmed`, `correct`, `wrong`, `uncertain`, `disputed`} + `verdict_by` ∈ {`trace`, `agent`} +
  `verdict_note`；`citation`（agent 提议必带的源码出处，无则 skip）；`evidence_locality` ∈ {`in_method`,
  `cross_method`, `cross_state`}（出处局部性，核对按它加权——跨态的 cited 边更可疑）；`output_slice`（§13.3 多输出，
  一个输出的哪一片走这条边，如 `[-1]`/`[:-1]`）；`shape_check`（连线当下本地算，`match`/`mismatch`/`unknown`，只提示不硬拦）。
- **两条铁律**：① **trace 不对称——只确认绝不否定**（trace 只看 tensor 谱系，对状态/标量/控制流全盲；假 `wrong` =
  "自信学错"灾难，故 trace 无权说 wrong，只读源码的 agent 有）；② **agent 可对 trace-`correct` 提异议 → `disputed`**
  （两台仪器打架、该被看见，不被静默覆盖）。
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

- **核对-讨论交互**：选中 port 浮出该处 ghost 建议、同意即连/分歧批量提交、agent 与人讨论解决（学习发生在此）。
- **命门 C**：importer→图→propose **live 串联**（真 SAM2，用导入图的端口词表而非手工提供）。归 Codex 后端线。
- **agent 工程**：prompt/导航策略；opencode harness 坑（非交互卡权限门死锁、`run` 须 `--print-logs` 否则挂起、
  导航策略 run 间随机）；`evidence_locality` 由 propose 推结构跨度 + agent 显式标跨态。见 [[project_deferred_agent_work]]。
- **前端边界投影删除缺口**（§12.4 × §13.3 连/拆边）：在下钻视图里删 boundary 桩子上的边不落库（桩子没接删除逻辑），
  会"骗人"。待修：或标桩子连线不可拖断（只读），或映射到真 edge id 发 DELETE。
