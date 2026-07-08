---
name: simulanka-baseline-manifest
description: Create or repair `simulanka_builds/manifest.yaml` and build functions for Simulanka baseline imports. Use when Codex needs to import a PyTorch baseline, write a lintable coverage manifest, choose top-level versus focused traces, add explicit child skip waivers, or run `simulanka import baseline --check`.
---

# Simulanka Baseline Manifest

## Purpose

Build a declarative import package that lets Simulanka capture a full PyTorch baseline structure plus focused child data-flow traces without silent coverage gaps.

## Directory Contract

Place import helpers inside the baseline repo:

```text
simulanka_builds/
  __init__.py
  manifest.yaml
  builds.py
```

Build specs in the manifest must be importable as `pkg.module:function`, for example `simulanka_builds.builds:build_top_level`.

## Manifest Shape

```yaml
top_level:
  build: simulanka_builds.builds:build_top_level
children:
  child_attr:
    build: simulanka_builds.builds:build_child_attr
  another_child:
    skip: "explicit reason this child is not traced"
    note: "optional context"
```

Rules:

- `top_level.build` must return the full top-level model, not a hand-picked component.
- `children` keys must exactly equal `set(top_level_model.named_children())`.
- Each child entry must specify exactly one of `build` or `skip`.
- A skip is a waiver, not an omission; always give a concrete reason.
- Focused child imports are committed as sibling model nodes under the same parent, not merged into the top-level subtree.

## Build Function Contract

Every build function is zero-argument and returns:

```python
(model, example_inputs)
```

- `model` is an already constructed `torch.nn.Module`.
- `example_inputs` is a tuple of positional args for `model(*example_inputs)`.
- Use `example_inputs=None` for structure-only import, especially for the top-level model when full forward inputs are expensive or pipeline-shaped.
- Use real representative inputs for focused child traces when data-flow edges are needed.
- Put models in eval mode when appropriate; never train during import.
- Keep checkpoint/config resolution deterministic and local to the baseline.

## Workflow

1. Inspect the top-level constructor and identify the true root module.
2. Instantiate the root and list exact direct child names with `named_children()`.
3. Write `build_top_level()` to return the full root model with `example_inputs=None` unless a full trace is genuinely cheap and meaningful.
4. For each direct child, either write a focused build function with real inputs or add `skip: "<reason>"`.
5. Run `simulanka import baseline <baseline_dir> --check` from a Simulanka project.
6. Fix every lint error. Missing or unknown children are manifest bugs.
7. Import with `simulanka import baseline <baseline_dir> --parent /baselines` or an explicit parent directory.

## Common Failure Modes

- Top-level build returns `model.image_encoder` instead of the full model.
- Child key uses a class name instead of the top-level attribute name.
- A child entry contains both `build` and `skip`, or neither.
- The manifest imports only the child that was easy to trace and silently omits the rest.
- Build functions require arguments or depend on the current working directory in fragile ways.
- The baseline root is not importable, so `simulanka_builds...` cannot resolve.
