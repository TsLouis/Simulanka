# Simulanka

A semi-automated scientific research system built around a Research Graph Kernel.

This repository is past the **Kernel Alpha** milestone. See `docs/overview.md` for what the system is and how it splits into parts; `docs/archive/` holds the frozen decision history.

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
- `tests/` — pytest suite, mirrors `src/`
- `docs/overview.md` — entry point; `kernel.md` / `assembly.md` / `frontend.md` — current architecture
- `docs/archive/` — frozen decision history (`design.md`) and pre-Alpha notes
