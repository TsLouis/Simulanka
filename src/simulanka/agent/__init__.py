"""Thin wrapper around external agent CLIs (codex, claude, ...) on top of the runner."""

from __future__ import annotations

from simulanka.agent.wrapper import (
    AGENT_TEMPLATES,
    AgentError,
    AgentRunResult,
    run_agent,
)

__all__ = [
    "AGENT_TEMPLATES",
    "AgentError",
    "AgentRunResult",
    "run_agent",
]
