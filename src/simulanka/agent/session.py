"""Normalized event stream for embedded, non-interactive agent sessions."""

from __future__ import annotations

import json
import os
import subprocess
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, TypeAlias

from simulanka.agent.harness import HarnessError, session_id_from_events

SessionEventType: TypeAlias = Literal[
    "user_msg",
    "agent_text",
    "tool_call",
    "tool_result",
    "status",
    "error",
]
StreamRunner: TypeAlias = Callable[[list[str], Mapping[str, str]], Iterable[str]]


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider features the session runtime may safely rely on."""

    native_resume: bool
    native_fork: bool
    interrupt: bool
    tool_events: bool
    usage: bool


@dataclass(frozen=True)
class ProviderTurn:
    """A single provider turn represented by normalized frontend events."""

    events: Iterator[SessionEvent]
    handle: TurnHandle


class TurnHandle(Protocol):
    """Control surface for an active provider turn."""

    def cancel(self) -> None:
        """Request cancellation of the active turn."""


@dataclass(frozen=True)
class UnsupportedTurnHandle:
    """Explicit control surface for providers without interruption support."""

    provider_id: str

    def cancel(self) -> None:
        raise HarnessError(f"provider {self.provider_id!r} does not support turn interruption")


class ProviderAdapter(Protocol):
    """Boundary between a provider CLI and Simulanka's session runtime."""

    provider_id: str
    capabilities: ProviderCapabilities

    def start_turn(
        self,
        message: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> ProviderTurn: ...

    def resume_turn(
        self,
        native_session_id: str,
        message: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> ProviderTurn: ...


ProviderAdapterFactory: TypeAlias = Callable[..., ProviderAdapter]


class ProviderAdapterRegistry:
    """Construct adapters by their stable provider identifier."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderAdapterFactory] = {}

    def register(self, provider_id: str, factory: ProviderAdapterFactory) -> None:
        if not provider_id:
            raise ValueError("provider_id must be non-empty")
        if provider_id in self._factories:
            raise ValueError(f"provider adapter {provider_id!r} is already registered")
        self._factories[provider_id] = factory

    def create(self, provider_id: str, **kwargs: Any) -> ProviderAdapter:
        try:
            factory = self._factories[provider_id]
        except KeyError as exc:
            raise HarnessError(f"unknown provider adapter {provider_id!r}") from exc
        return factory(**kwargs)


@dataclass(frozen=True)
class SessionEvent:
    """One frontend-facing event in the stable S8 vocabulary."""

    type: SessionEventType
    text: str | None = None
    status: str | None = None
    tool_name: str | None = None
    call_id: str | None = None
    input: Any = None
    output: Any = None
    provider_session_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type}
        for key in (
            "text",
            "status",
            "tool_name",
            "call_id",
            "input",
            "output",
            "provider_session_id",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.details:
            payload["details"] = self.details
        return payload


def normalize_opencode_event(raw: dict[str, Any]) -> list[SessionEvent]:
    """Translate one OpenCode JSON event; retained as a compatibility facade."""
    return OpenCodeAdapter.normalize_event(raw)


class OpenCodeAdapter:
    """OpenCode CLI transport and raw-event translation."""

    provider_id = "opencode"
    capabilities = ProviderCapabilities(
        native_resume=True,
        native_fork=False,
        interrupt=False,
        tool_events=True,
        usage=False,
    )

    def __init__(self, *, runner: StreamRunner | None = None) -> None:
        self._runner = runner

    def start_turn(
        self,
        message: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> ProviderTurn:
        return ProviderTurn(
            events=self._stream_events(message, model=model, agent=agent, session_id=None),
            handle=UnsupportedTurnHandle(self.provider_id),
        )

    def resume_turn(
        self,
        native_session_id: str,
        message: str,
        *,
        model: str | None = None,
        agent: str | None = None,
    ) -> ProviderTurn:
        return ProviderTurn(
            events=self._stream_events(
                message,
                model=model,
                agent=agent,
                session_id=native_session_id,
            ),
            handle=UnsupportedTurnHandle(self.provider_id),
        )

    @staticmethod
    def normalize_event(raw: dict[str, Any]) -> list[SessionEvent]:
        """Translate one OpenCode JSON event without exposing its raw shape."""
        part = raw.get("part")
        if isinstance(part, dict):
            part_type = part.get("type")
            if part_type == "text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    return [SessionEvent(type="agent_text", text=text)]
                return []
            if part_type == "tool":
                return _normalize_tool_part(part)
            if part_type in {"step-start", "step_start"}:
                return [SessionEvent(type="status", status="running", text="Agent 正在处理…")]
            if part_type in {"step-finish", "step_finish"}:
                return [SessionEvent(type="status", status="step_done", text="步骤完成")]

        event_type = raw.get("type")
        if event_type == "error":
            message = _first_string(raw, "message", "error", "text") or "Agent 返回错误"
            return [SessionEvent(type="error", status="failed", text=message)]

        text = _assistant_text(raw)
        if text:
            return [SessionEvent(type="agent_text", text=text)]

        label = event_type if isinstance(event_type, str) and event_type else "unknown"
        return [
            SessionEvent(
                type="status",
                status="event",
                text=f"Agent 事件：{label}",
                details={"event_type": label},
            )
        ]

    def _stream_events(
        self,
        message: str,
        *,
        session_id: str | None,
        model: str | None,
        agent: str | None,
    ) -> Iterator[SessionEvent]:
        if not message.strip():
            raise HarnessError("message must be non-empty.")

        args = ["opencode", "run", "--print-logs", "--format", "json"]
        if model:
            args.extend(["-m", model])
        if agent:
            args.extend(["--agent", agent])
        if session_id:
            args.extend(["-s", session_id])
        args.append(message)

        env = dict(os.environ)
        env["SIMULANKA_ACTOR"] = "agent"
        lines = self._runner(args, env) if self._runner is not None else _run_stream(args, env)
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                yield SessionEvent(
                    type="status",
                    status="event",
                    text="Agent 正在处理非结构化输出…",
                )
                continue
            if not isinstance(raw, dict):
                continue
            provider_session_id = session_id_from_events([raw])
            for event in self.normalize_event(raw):
                if provider_session_id and event.provider_session_id is None:
                    event = replace(event, provider_session_id=provider_session_id)
                yield event


def stream_opencode_events(
    message: str,
    *,
    session_id: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    runner: StreamRunner | None = None,
) -> Iterator[SessionEvent]:
    """Run one OpenCode turn; retained as the existing public facade."""
    adapter = OpenCodeAdapter(runner=runner)
    turn = (
        adapter.resume_turn(session_id, message, model=model, agent=agent)
        if session_id
        else adapter.start_turn(message, model=model, agent=agent)
    )
    yield from turn.events


provider_adapters = ProviderAdapterRegistry()
provider_adapters.register(OpenCodeAdapter.provider_id, OpenCodeAdapter)


def _normalize_tool_part(part: dict[str, Any]) -> list[SessionEvent]:
    state = part.get("state")
    state_dict = state if isinstance(state, dict) else {}
    tool_name = _first_string(part, "tool", "name") or "tool"
    call_id = _first_string(part, "callID", "call_id", "id")
    status = _first_string(state_dict, "status") or "running"
    tool_input = state_dict.get("input")
    tool_output = state_dict.get("output")
    error = state_dict.get("error")

    call = SessionEvent(
        type="tool_call",
        status=status,
        tool_name=tool_name,
        call_id=call_id,
        input=tool_input,
    )
    if tool_output is None and error is None and status not in {"completed", "error", "failed"}:
        return [call]
    result_status = "failed" if error is not None or status in {"error", "failed"} else "done"
    result = SessionEvent(
        type="tool_result",
        status=result_status,
        tool_name=tool_name,
        call_id=call_id,
        output=error if error is not None else tool_output,
    )
    return [call, result]


def _assistant_text(raw: dict[str, Any]) -> str | None:
    role = raw.get("role")
    if role is not None and role != "assistant":
        return None
    return _first_string(raw, "text", "delta", "content")


def _first_string(value: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return None


def _run_stream(args: list[str], env: Mapping[str, str]) -> Iterator[str]:
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=dict(env),
        )
    except FileNotFoundError as exc:
        raise HarnessError("`opencode` CLI not found on PATH.") from exc

    assert proc.stdout is not None
    tail: deque[str] = deque(maxlen=20)
    try:
        for line in proc.stdout:
            tail.append(line.rstrip())
            yield line
        returncode = proc.wait()
        if returncode != 0:
            detail = "\n".join(tail)[-500:]
            raise HarnessError(f"opencode exited {returncode}: {detail}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
