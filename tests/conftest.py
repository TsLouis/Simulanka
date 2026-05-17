"""Shared test helpers."""

from __future__ import annotations


def fake_argv(script_body: str) -> str:
    """Build a SIMULANKA_AGENT_FAKE_ARGV value running *script_body* via sh -c.

    The trailing ``sh {prompt}`` slot lets the prompt land as argv[2] of the
    inner shell, where it's discarded — same trick the sync wrapper tests use.
    """
    return f"sh -c '{script_body}' sh {{prompt}}"
