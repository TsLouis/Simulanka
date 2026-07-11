"""Run executor: invoke a shell command, capture I/O, register as a `run` node."""

from __future__ import annotations

from simulanka.runner.bracket import BeginResult, EndResult, begin_run, end_run
from simulanka.runner.detached import (
    RunNotFound,
    StartResult,
    kill_run,
    reconcile_run,
    start_run,
    wait_run,
)
from simulanka.runner.exec import ExecResult, RunnerError, exec_run

__all__ = [
    "BeginResult",
    "EndResult",
    "ExecResult",
    "RunNotFound",
    "RunnerError",
    "StartResult",
    "begin_run",
    "end_run",
    "exec_run",
    "kill_run",
    "reconcile_run",
    "start_run",
    "wait_run",
]
