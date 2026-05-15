# Simulanka

A semi-automated scientific research system built around a Research Graph Kernel.

This repository is at the **Kernel Alpha** milestone. See `docs/design.md` for the architecture and `researcher-handoff/` for prior-art notes.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

simulanka init ./demo-project
pytest
```

## Layout

- `src/simulanka/` — Python package
- `docs/design.md` — Kernel Alpha design (single source of truth for the architecture)
- `references/` — Reference projects (DeepScientist, OpenResearch); not built by Simulanka
- `researcher-handoff/` — Notes carried over from the prior local MVP
