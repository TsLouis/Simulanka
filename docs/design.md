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

**数据流**：`torch.export.export(model, example_inputs)`，遍历 fx graph，借 `meta["nn_module_stack"]` 把每个 aten op 归到它所属的 nn.Module。leaf-leaf 流回滚到"首个发散祖先"那一对（`b1.lin → b2.lin` 折成 `b1 → b2`；`b1.lin → b1.act` 保留为同级），再连成 `data_flow` 边。

**Alpha 不做**：
- aten 层级图（leaf-leaf 边收起来了；多级展开留给查询/前端）
- 配置文件解析为图节点（用 `file:config` 节点 + `uses` 边足够）
- shape/dtype 元数据（`ExportedProgram` 里有，先没存）
- 自定义 autograd function、`torch.compile` 后的图、量化图

**已知支持范围**：纯 functional + 静态控制流的 forward。data-dependent control flow（Dynamo 阻断）的模型 import 会失败 —— 错误原样冒上来。

**CLI**：`simulanka import torch --build pkg.mod:fn --name N [--parent /dir]`

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

#### 不在 Alpha

- `run agent --detach`：agent wrapper 在 subprocess 之后做 workspace diff，detached 模式下需要把 before-snapshot 持久化、reconcile 时计算 diff。值得做但优先级低。
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

下一步候选：`run agent --detach`（detached 模式下也跑 workspace diff）；TaskContract 化（goal + allowed_outputs + budget 结构化输入）；前端 canvas。视具体研究流程触发。

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
