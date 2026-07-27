from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from simulanka.cli.app import app
from simulanka.kernel.events import iter_events
from simulanka.kernel.resolver import resolve_node
from simulanka.layout.project import ProjectLayout


@pytest.mark.parametrize(
    "command",
    [
        ["propose"],
        ["graph", "node", "create"],
        ["graph", "port", "create"],
        ["graph", "connect"],
        ["graph", "file", "create"],
        ["graph", "file", "register"],
        ["graph", "migrate"],
        ["import", "torch"],
        ["import", "baseline"],
        ["run", "exec"],
        ["run", "agent"],
        ["run", "begin"],
        ["run", "end"],
        ["run", "status"],
        ["run", "wait"],
        ["run", "reconcile"],
        ["task", "create"],
        ["plan", "ingest"],
        ["brief", "export"],
        ["evidence", "extract"],
        ["note", "resolve"],
    ],
)
def test_graph_write_commands_expose_actor_option(command: list[str]) -> None:
    result = CliRunner().invoke(app, [*command, "--help"])

    assert result.exit_code == 0, result.output
    assert "--actor" in result.output


def test_cli_actor_precedence_and_task_event_accounting(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "project"
    initialized = runner.invoke(app, ["init", str(project)])
    assert initialized.exit_code == 0, initialized.output

    project_env = {"SIMULANKA_PROJECT": str(project)}

    defaulted = runner.invoke(
        app,
        ["graph", "node", "create", "--type", "directory", "--name", "tasks"],
        env=project_env,
    )
    assert defaulted.exit_code == 0, defaulted.output

    from_env = runner.invoke(
        app,
        ["graph", "node", "create", "--type", "directory", "--name", "agent-dir"],
        env={**project_env, "SIMULANKA_ACTOR": "agent"},
    )
    assert from_env.exit_code == 0, from_env.output

    explicit = runner.invoke(
        app,
        [
            "graph",
            "node",
            "create",
            "--type",
            "directory",
            "--name",
            "operator-dir",
            "--actor",
            "operator",
        ],
        env={**project_env, "SIMULANKA_ACTOR": "agent"},
    )
    assert explicit.exit_code == 0, explicit.output

    task = runner.invoke(
        app,
        [
            "task",
            "create",
            "--parent",
            "/tasks",
            "--name",
            "actor-check",
            "--goal",
            "verify actor accounting",
            "--actor",
            "operator",
        ],
        env={**project_env, "SIMULANKA_ACTOR": "agent"},
    )
    assert task.exit_code == 0, task.output

    layout = ProjectLayout(project.resolve())
    assert [event.actor for event in iter_events(layout)][-4:] == [
        "user",
        "agent",
        "operator",
        "operator",
    ]
    assert resolve_node(layout, "/tasks/actor-check").created_by == "operator"

    detached = runner.invoke(
        app,
        [
            "run",
            "exec",
            "--cmd",
            "true",
            "--parent",
            "/tasks",
            "--name",
            "actor-reconcile",
            "--detach",
        ],
        env={**project_env, "SIMULANKA_ACTOR": "agent"},
    )
    assert detached.exit_code == 0, detached.output

    waited = runner.invoke(
        app,
        [
            "run",
            "wait",
            "/tasks/actor-reconcile",
            "--timeout",
            "5",
            "--interval",
            "0.01",
            "--actor",
            "operator",
        ],
        env={**project_env, "SIMULANKA_ACTOR": "agent"},
    )
    assert waited.exit_code == 0, waited.output
    assert list(iter_events(layout))[-1].actor == "operator"
