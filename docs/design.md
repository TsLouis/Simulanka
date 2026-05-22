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

`PatchIntent.ops` 支持：`create_node` / `create_edge` / `create_port` / `update_attrs`（同 patch 内可级联，浅 merge 语义） / `delete` / `move`（后两者 Alpha 未实现）。实现节奏见 §9。

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

## 13. 提案：人画连线 + agent 核对（2026-05-22，未实现）

> **状态**：设计讨论，**尚未实现**。下午继续把它落成 §13.5 的具体方案。本节先固化动机、洞见、约束，避免下次重新推导。

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

3. **突破只读红线**：现前端是只读 MVP（§12.7，编辑留 v2）。用户画 edge → 前端变写方（画线 → `apply_patch(CreateEdgeOp)`）。kernel 本就支持该 op，但把 v2 编辑能力提前了。配套：边加来源标记 `source: trace | user | agent`，三种线在图上要可区分。

### 13.4 待用户拍板的判断

- **值不值取决于目标**：若目标是“用户理解 baseline”（用户明示），手动成本就是价值，值得；若哪天只想要那张图，别玩游戏，直接让 agent 读源码画完最省。
- **UX 旋钮（松紧）**：用户从零画 → agent 判分（学得最狠、最费力）；或 agent 先读源码提一版 → 用户改（轻一些，改的过程也在理解）。

> **决定（2026-05-22）**：**「人从 0 画」为默认**。理由：本项目本就允许人与 agent 沟通，想让 agent 先画直接说一句即可；「agent 先提一版」推迟到后续 agent 工程慢慢做，甚至可做成一个 skill。先把一条路做透（lean），不做可切换的双模式。

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

#### 13.5.3 agent 核对 —— 待做

两条路：能 trace 的子模块用隐藏的自动 trace 当答案键；不能 trace 的顶层 agent 读 `forward()` 源码推断。核对结果呈现为标对 / 错 / 存疑。
