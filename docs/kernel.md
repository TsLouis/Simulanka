# 图内核

> 分篇之一（入口见 `overview.md`）。图状态的唯一权威：三原语、类型注册表、唯一写路径、存储与自检。
> 本篇对着 `src/simulanka/{schema,kernel,storage,layout,registry}` 与其测试写成，只写现行结论。

## 三原语

| 原语 | 字段 | 说明 |
| --- | --- | --- |
| **Node** | `id` `type` `name` `parent_id` `attrs` `created_at` `created_by` | 层级由 `parent_id` 缓存 + `contains` 边双写 |
| **Port** | `id` `node_id` `name` `direction(in/out)` `port_type` `attrs` … | 同节点内端口名唯一 |
| **Edge** | `id` `type` `source_id` `target_id` `source_port_id?` `target_port_id?` `attrs` … | 端口仅 `data_flow` 类边使用 |

`attrs` 是自由字典：内核不硬校验其内容（研究字段演化快，硬 schema 是摩擦）。语义全靠 attrs 约定，约定见图汇编语言篇的铭章表。

## 类型注册表

**节点类型**（右列 = 允许的父类型）：

| 类型 | 允许父 |
| --- | --- |
| directory | directory、根 |
| model | directory |
| module | model、module |
| file | directory |
| question | directory |
| hypothesis | directory、experiment |
| claim | directory、experiment |
| evidence | directory、experiment、run |
| experiment | directory |
| run | directory、experiment |
| note | directory、experiment、run |
| task | directory、experiment |

**边类型**（源 → 目标的类型约束）：

| 类型 | 源 → 目标 | 端口 |
| --- | --- | --- |
| contains | 容器类 → 任意 | 无（随 create_node 双写，禁单删） |
| data_flow | 任意 → 任意 | **必须**，out → in |
| addresses | hypothesis → question | 无 |
| tests | experiment/run → hypothesis | 无 |
| supports / contradicts | evidence → claim/hypothesis | 无 |
| produces | run → file/evidence | 无 |
| part_of | run → experiment | 无 |
| uses | run → model/file | 无 |
| fulfills | run → task | 无 |

端口类型：`any` / `tensor` / `scalar`。所有约束在建时校验，doctor 全量复检。

## 唯一写路径

一切图变更 = `PatchIntent{ops, actor, base_graph_version, note}` → `apply_patch` → `Receipt`。六种 op：

| op | 行为 |
| --- | --- |
| create_node | 建节点；有父则双写 `contains` 边；可声明 `ref` 供同一 intent 内后续 op 以 `@ref` 引用（多实体叙事原子落地的机制，plan ingest 用） |
| create_port | 建端口，同节点名唯一 |
| create_edge | 建边，端点 = 节点/端口 selector 或 `@ref` |
| update_attrs | **浅 merge** attrs（无删键语义）；目标是节点 selector 或边 id（`edg_…`） |
| rename_node | 改名，同父之下兄弟唯一 |
| delete_edge | 按 id 删边，唯一删除原语；拒删 `contains`（它背书层级） |

- **原子性**：全部 op 先校验后落盘，任一错 = 整个 intent 拒，报错带 `op[i]` 定位。
- **乐观并发**：`base_graph_version` 与当前不符 = `VersionConflict`，重读重发。
- **名字保留字**：`nod_`/`edg_`/`prt_` 前缀与 `@` 开头的名字拒收（会被 selector 语法劫持）。
- **actor 铭章**：kernel 只记录 actor（进实体 `created_by` 与事件日志），**不裁权**——写权矩阵的执行点在 server 闸门（人侧端点 + agent op 闸，见前端篇）。CLI/库内约定的 actor 词表：`user`、`agent`、`analyst`、`operator`、`runner`、`importer:*`、`system:*`。

## Selector（读侧寻址）

- 节点：`nod_…` id / 绝对路径 `/a/b` / 全图唯一的裸名（歧义即报错并列候选）。
- 端口：`prt_…` id / `/path.name` / `nodename.name`。
- 兄弟同名是合法状态（kernel 建时不查重，除 rename 外）；歧义在读时拒——所以 plan 格式等上层要自禁保留名（如 `escalate`）。

## 存储（`.simulanka/`）

```
.simulanka/
  manifest.json          # schema/registry/graph_version、project_id、content_hash
  graph/
    nodes|edges|ports/   # 一实体一 JSON，原子写（tmp + rename）
    events/*.jsonl       # 追加式事件日志，1 MiB 分段
    indexes/graph.sqlite # 派生索引，可随时重建
  runs/<handle>/         # run 工作目录（日志、契约快照）
  logs/  cache/  ui/  agent/
```

- **事件日志**：每次 commit 一条 `Event`（actor、版本、canonical_ops——含已解析的实体 id），全历史可查，SSE 与 `_affected` 刷新都从它读。
- **content_hash**：manifest 记全体实体文件的滚动哈希；带外改动被 doctor 当场抓出。
- **git checkpoint（撤回兜底）**：`.simulanka/` 内嵌独立 git 仓，与用户代码仓隔离。惰性激活——`apply_patch` 只在 `.simulanka/.git` 存在时快照；server 启动时 `ensure_repo`（agent 写权只从 server 进入，故安全网必然先于风险就位）。讨论轮开始时打 `discussion-start` tag 作恢复点。
- **bundle**：`graph export` / `graph import` 整项目单 JSON 导出/复原。

## 项目布局与 FileRegistry

`simulanka init` 建 `.simulanka/` + 受管顶层目录，并为每个目录登记 directory 节点。**agent/用户不自由选路径**——按 kind 向 FileRegistry 要：

| kind | 目录 | binding | 命名 |
| --- | --- | --- | --- |
| code | src/ | managed | `.py` |
| test | tests/ | managed | `test_*.py` |
| doc | docs/ | managed | `.md` |
| paper | papers/ | managed | `.md` |
| config | configs/ | managed | `.yaml` |
| artifact | .simulanka/artifacts/ | managed | — |
| baseline | baselines/ | **reference** | — |
| plan | research/ | managed | `plan-*.md` |
| brief | research/ | managed | `brief-*.md` |

- `managed` = 内容入图（content_hash + size）；`reference` = 只登记存在（外部/大型活树，如 baseline 符号链接指向远端仓）。
- 新 kind 在旧项目上**惰性建目录节点**，不需要迁移步。
- file 节点 attrs：`fs_path`、`content_hash`、`kind`、`binding`、`size_bytes`。

## doctor 自检（`simulanka graph doctor`）

| 检查 | 级别 |
| --- | --- |
| schema/registry 版本不匹配（→ `graph migrate`） | error |
| content_hash 漂移（带外改动/损坏） | error |
| parent_id 缓存 ↔ contains 边不一致 | warn |
| 悬空端口/边端点 | error |
| 未注册类型、边端点类型违约、data_flow 缺端口/方向错 | error |
| file 节点缺 fs_path / 盘上文件消失 / 内容哈希漂移（reference 只查存在） | error |
| 受管目录下未登记的文件 | warn |
| SQLite 索引计数漂移 | warn，`--repair` 自动重建 |

修复原则：doctor 只自动修**派生**状态（索引）；实体与历史永不自动改写。

## CLI（内核面）

```
simulanka init [PATH]
simulanka graph node create|inspect
simulanka graph port create
simulanka graph file create|register        # 经 FileRegistry
simulanka graph connect                     # 建边
simulanka graph doctor [--repair] / migrate
simulanka graph index rebuild
simulanka graph export|import               # bundle
```
