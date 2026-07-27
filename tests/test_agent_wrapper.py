"""Agent wrapper tests.

To avoid depending on real ``codex`` / ``claude`` binaries being installed,
each test overrides the agent template via ``SIMULANKA_AGENT_FAKE_ARGV``
pointing at a bash one-liner that simulates an agent's effect on the
workspace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulanka.agent import AgentError, run_agent
from simulanka.agent.wrapper import AGENT_TEMPLATES, build_command
from simulanka.kernel.apply import apply_patch
from simulanka.kernel.doctor import run_doctor
from simulanka.kernel.intent import CreateNodeOp, PatchIntent
from simulanka.layout.project import ProjectLayout, init_project
from simulanka.storage.entity_store import load_node
from tests.conftest import fake_argv


def _seed(layout: ProjectLayout) -> None:
    apply_patch(
        layout,
        PatchIntent(
            ops=[CreateNodeOp(type="directory", name="research")],
            actor="test",
            base_graph_version=layout.load_manifest().graph_version,
        ),
    )


def test_known_agent_templates_compose_correctly() -> None:
    """The built-in templates substitute `{prompt}` positionally and shell-quote safely."""
    import shlex

    assert "codex" in AGENT_TEMPLATES
    assert "claude" in AGENT_TEMPLATES
    nasty = "hello 'world' && echo bye"
    cmd = build_command("codex", nasty)
    # Round-trip: a POSIX shell would parse the cmd back into argv where the
    # prompt is a single token, not multiple shell-interpreted ones.
    parsed = shlex.split(cmd)
    assert parsed[0] == "codex"
    assert parsed[1] == "exec"
    assert parsed[2] == nasty


def test_unknown_agent_without_override_raises() -> None:
    with pytest.raises(AgentError):
        build_command("nonexistent", "any prompt")


def test_env_override_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMULANKA_AGENT_CODEX_ARGV", "/usr/bin/echo prefix {prompt}")
    cmd = build_command("codex", "the goal")
    assert cmd.startswith("/usr/bin/echo prefix")
    assert "the goal" in cmd


def test_run_agent_injects_agent_actor_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    actor_file = tmp_path / "actor.txt"
    monkeypatch.setenv("SIMULANKA_ACTOR", "operator")
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        fake_argv(f'printf %s "$SIMULANKA_ACTOR" > {actor_file}'),
    )

    result = run_agent(
        layout,
        agent="fake",
        prompt="record actor",
        parent="/research",
        name="actor-env",
    )

    assert result.status == "done"
    assert actor_file.read_text(encoding="utf-8") == "agent"


def test_fake_agent_modifies_workspace_and_diff_is_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)

    # Seed workspace with two files we'll touch via the "agent".
    (tmp_path / "a.txt").write_text("original-a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("original-b\n", encoding="utf-8")

    # The fake agent: prints something, creates one file, modifies another,
    # deletes a third. {prompt} ends up as an argument we ignore.
    fake_script = (
        f"sh -c 'echo got: \"$2\"; "
        f"echo new > {tmp_path}/c.txt; "
        f"echo updated > {tmp_path}/a.txt; "
        f"rm {tmp_path}/b.txt' "
        f"sh {{prompt}}"
    )
    monkeypatch.setenv("SIMULANKA_AGENT_FAKE_ARGV", fake_script)

    result = run_agent(
        layout,
        agent="fake",
        prompt="please mutate the workspace",
        parent="/research",
        name="agent1",
    )
    assert result.status == "done"
    assert result.exit_code == 0

    # The diff should contain exactly: +c.txt, ~a.txt, -b.txt.
    assert "c.txt" in result.files_added
    assert "a.txt" in result.files_modified
    assert "b.txt" in result.files_deleted

    # prompt.txt and changes.json live in run_dir.
    prompt_path = layout.root / result.prompt_path
    changes_path = layout.root / result.changes_path
    assert prompt_path.read_text(encoding="utf-8") == "please mutate the workspace"
    changes = json.loads(changes_path.read_text(encoding="utf-8"))
    assert changes["agent"] == "fake"
    assert changes["added"] == ["c.txt"]
    assert changes["modified"] == ["a.txt"]
    assert changes["deleted"] == ["b.txt"]

    # The run node attrs include the agent label.
    run_node = load_node(layout, result.run_node_id)
    assert run_node.attrs["agent"] == "fake"
    # The prompt was shell-quoted, not interpolated — it survives as one argv token.
    assert "'please mutate the workspace'" in run_node.attrs["command"]

    # Doctor stays green even with files added/deleted under workdir, since
    # those aren't registered as graph nodes.
    assert run_doctor(layout).ok


def test_track_scope_restricts_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    (tmp_path / "watched").mkdir()
    (tmp_path / "ignored").mkdir()
    (tmp_path / "watched" / "a.txt").write_text("a\n")
    (tmp_path / "ignored" / "z.txt").write_text("z\n")

    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        (
            f"sh -c 'echo new > {tmp_path}/watched/b.txt; "
            f"echo new > {tmp_path}/ignored/y.txt' "
            f"sh {{prompt}}"
        ),
    )
    result = run_agent(
        layout,
        agent="fake",
        prompt="ignored",
        parent="/research",
        name="scoped",
        track_scope=["watched"],
    )
    assert "watched/b.txt" in result.files_added
    assert all("ignored" not in p for p in result.files_added)


def test_track_scope_missing_dir_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    monkeypatch.setenv("SIMULANKA_AGENT_FAKE_ARGV", "true {prompt}")
    with pytest.raises(AgentError):
        run_agent(
            layout,
            agent="fake",
            prompt="x",
            parent="/research",
            name="bad_scope",
            track_scope=["does/not/exist"],
        )


def test_track_scope_escaping_workdir_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "proj"
    layout = init_project(project, with_scaffold=False).layout
    _seed(layout)
    (tmp_path / "outside").mkdir()
    monkeypatch.setenv("SIMULANKA_AGENT_FAKE_ARGV", "true {prompt}")
    with pytest.raises(AgentError, match="escapes workdir"):
        run_agent(
            layout,
            agent="fake",
            prompt="x",
            parent="/research",
            name="escape_scope",
            track_scope=["../outside"],
        )


def test_default_ignored_dirs_not_in_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.simulanka/`, `.git/`, `__pycache__/` etc. should never appear in changes."""
    layout = init_project(tmp_path, with_scaffold=False).layout
    _seed(layout)
    # Ensure the .simulanka dir exists (init creates it) — exec_run will add
    # files under .simulanka/runs/<handle>/ which would be huge diff noise
    # if not ignored.
    monkeypatch.setenv(
        "SIMULANKA_AGENT_FAKE_ARGV",
        f"sh -c 'echo new > {tmp_path}/payload.txt' sh {{prompt}}",
    )
    result = run_agent(
        layout, agent="fake", prompt="x", parent="/research", name="quiet",
    )
    assert result.files_added == ["payload.txt"]
    assert not any(p.startswith(".simulanka") for p in result.files_added)
