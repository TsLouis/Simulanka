"""Thin wrapper around external agent CLIs (codex, claude, ...) on top of the runner."""

from __future__ import annotations

from simulanka.agent.detached import (
    AgentDiffSummary,
    AgentStartResult,
    finalize_agent_diff,
    start_agent_run,
)
from simulanka.agent.wrapper import (
    AGENT_TEMPLATES,
    AgentError,
    AgentRunResult,
    run_agent,
)
from simulanka.contract import (
    AcceptanceSpec,
    BudgetSpec,
    ContractCheckResult,
    TaskContract,
)

__all__ = [
    "AGENT_TEMPLATES",
    "AcceptanceSpec",
    "AgentDiffSummary",
    "AgentError",
    "AgentRunResult",
    "AgentStartResult",
    "BudgetSpec",
    "ContractCheckResult",
    "TaskContract",
    "finalize_agent_diff",
    "run_agent",
    "start_agent_run",
]
