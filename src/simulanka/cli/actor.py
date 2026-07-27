"""Shared caller identity option for graph-mutating CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

ACTOR_ENV_VAR = "SIMULANKA_ACTOR"

ActorOption = Annotated[
    str | None,
    typer.Option(
        "--actor",
        envvar=ACTOR_ENV_VAR,
        help=(
            "Identity recorded on graph events. Explicit value overrides "
            f"{ACTOR_ENV_VAR}; default: user."
        ),
    ),
]


def resolve_actor(value: str | None) -> str:
    """Return the CLI-resolved actor, falling back to the public default."""
    return "user" if value is None else value
