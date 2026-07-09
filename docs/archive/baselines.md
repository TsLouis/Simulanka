# Baselines & Remote Experiment Workspace

Date: 2026-05-19 · Status: **已归档（2026-07-09）**，远端工作区约定仍有效（prose rules, not enforced by code）；manifest/成图部分现行版见 `docs/assembly.md`

Simulanka 的 graph state 在本地（`.simulanka/`），但**真正跑实验的代码和数据在远端 a100-118**。本文档约定远端工作区的组织方式和实验生命周期。规则由 codex / claude 等 agent 自觉遵守，不在 kernel 层强制。

## 1. 远端目录约定

```
/data4/yf/
  tot/                              ← 当前科研项目根（topic / theme）
    baselines/
      DS_r/                         ← 一个 baseline = 一个独立 git 仓库
        .git/                       ← main = baseline 快照，分支 exp/<id> = 实验
        .gitignore                  ← 屏蔽权重、experiments/*/results/、didi-workspace/{cache,...}
        sam2/  tracker/  ...        ← 代码
    runs/
      DS_r/
        <exp_id>/                   ← git worktree，挂在 exp/<exp_id> 分支
  DS_r/                             ← 原始只读快照，作 ground truth，不参与工作流

# 以后做第二个科研主题：/data4/yf/tot2/ 或 /data4/yf/<topic>/，结构同上。
```

**为什么 baseline 一个独立 git 仓库，不做 monorepo**：每个 baseline 上下游不同、依赖不同、.gitignore 不同；跨 baseline 的对比语义由 Simulanka graph 的 experiment 节点承担，git 不重复承担。

## 2. 实验生命周期

```bash
# 在 baseline 仓库里开分支
cd /data4/yf/tot/baselines/DS_r
git checkout -b exp/<exp_id>

# 物化成 worktree（每个 run 一个独立目录，不在 baseline 目录里切来切去）
git worktree add /data4/yf/tot/runs/DS_r/<exp_id> exp/<exp_id>

# Agent 在 worktree 内修改代码、跑训练/评测
# 产物落在 worktree 下相对路径（experiments/<exp_id>/results/...），不入 git
# 代码改动要能 git diff 出来，然后 commit

# Run 结束时 finalize：记录 git_sha、产物路径
# Simulanka run 节点 attrs：
#   { "baseline": "DS_r",
#     "branch":   "exp/<exp_id>",
#     "git_sha":  "<commit sha>",
#     "worktree_path": "/data4/yf/tot/runs/DS_r/<exp_id>" }
```

清理 run：`git worktree remove /data4/yf/tot/runs/DS_r/<exp_id>`（分支保留，方便复现）。

## 3. Agent 规则

- **代码改动必须能 `git diff`**：二进制权重、>10MB 的数据文件不准入 git。
- **产物路径相对 worktree 根**：方便 worktree 自包含；不要写绝对路径或跨 worktree 的引用。
- **一个 worktree 一个 run**：不在同一个 worktree 顺序跑两个不同实验；要新实验就新建 worktree。
- **切分支前必须 commit 或 stash**：worktree 模型下其实不切分支，但万一手贱在 baseline 目录里切了，要先清理。
- **修 baseline 本身**（修 bug、加通用工具）：直接在 baseline 的 `main` 上 commit；不开实验分支。

## 4. Simulanka graph 怎么挂

不为 baseline / git 引入新的节点类型——直接复用现有 node + attrs：

- **baseline** 用一个 `type="reference"` 节点，attrs 含 `{kind: "git_baseline", remote_path, head_sha}`
- **experiment** 节点 attrs 加 `{baseline_ref: <node_id>, branch: "exp/<id>"}`
- **run** 节点 attrs 加 `{git_sha, worktree_path}`（已有 attrs 浅 merge，不破坏现状）

这样 FileRegistry 不需要改，TaskContract 的 `allowed_outputs` 仍然是 worktree 内的 glob。

## 5. 增加新 baseline

```bash
mkdir -p /data4/yf/tot/baselines/<NewBaseline>
cd /data4/yf/tot/baselines/<NewBaseline>
# 拷代码进来（不带 .git 不带产物），写好 .gitignore
git init -b main
git add -A
git commit -m "Baseline: <NewBaseline> snapshot"
mkdir -p /data4/yf/tot/runs/<NewBaseline>
```

然后在 Simulanka 里建对应的 `reference` 节点。

## 6. 当前已落地状态（2026-05-19）

- `/data4/yf/tot/baselines/DS_r/`：main = `3a96b43`，372 文件，纯代码。
- `/data4/yf/tot/runs/DS_r/`：空，等首个实验。
- `/data4/yf/DS_r/`：原始版本，含 checkpoints / 历史 experiments 产物，只读保留。
- Simulanka graph 这边还没建 `reference` 节点（等真有实验要跑时再建）。
