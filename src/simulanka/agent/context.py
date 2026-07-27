"""Deterministic, explicitly selected supplemental context for provider turns.

This module is deliberately independent from provider prompts and transcripts.
It compiles graph references into immutable, content-addressed reference data;
the session layer decides how a newly sent bundle reaches a provider.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from simulanka.layout.project import ProjectLayout
from simulanka.schema.entities import Edge, Node, Port
from simulanka.storage.entity_store import load_edge, load_node, load_port

CONTEXT_SCHEMA_VERSION = "1"
CONTEXT_COMPILER_VERSION = "1"
MissingReferencePolicy: TypeAlias = Literal["error", "omit"]
DeliveryAction: TypeAlias = Literal["send", "skip"]
ReferenceKind: TypeAlias = Literal["node", "edge", "port"]


class ContextReferenceError(ValueError):
    """An explicitly selected graph reference cannot be resolved."""


class ContextSnapshotError(ValueError):
    """The graph changed while a context bundle was being compiled."""


def canonical_json_bytes(value: object) -> bytes:
    """Encode JSON in the one format used for context identity."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _ordered_unique(refs: Iterable[ContextRef]) -> tuple[ContextRef, ...]:
    result: list[ContextRef] = []
    seen: set[ContextRef] = set()
    for ref in refs:
        if not isinstance(ref, ContextRef):
            raise ValueError("context references must be ContextRef values")
        if ref not in seen:
            seen.add(ref)
            result.append(ref)
    return tuple(result)


@dataclass(frozen=True)
class ContextRef:
    """One explicitly selected graph entity."""

    kind: ReferenceKind
    ref_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"node", "edge", "port"}:
            raise ValueError("context reference kind must be node, edge, or port")
        if not self.ref_id:
            raise ValueError("context reference id must be non-empty")

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref_id": self.ref_id}


@dataclass(frozen=True)
class RefSet:
    """An ordered, de-duplicated set of explicitly selected graph entities."""

    refs: tuple[ContextRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "refs", _ordered_unique(self.refs))

    def as_list(self) -> list[dict[str, str]]:
        return [ref.as_dict() for ref in self.refs]


@dataclass(frozen=True)
class ContextOmission:
    """A selected reference intentionally left out of a compiled bundle."""

    kind: ReferenceKind
    ref_id: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref_id": self.ref_id, "reason": self.reason}


@dataclass(frozen=True)
class ContextBundle:
    """Immutable context content identified by the digest of its canonical body."""

    schema_version: str
    compiler_version: str
    missing_policy: MissingReferencePolicy
    refs: RefSet
    graph_version: int
    payload: bytes
    omissions: tuple[ContextOmission, ...]
    digest: str

    def payload_object(self) -> dict[str, Any]:
        value = json.loads(self.payload)
        if not isinstance(value, dict):  # defensive: compiler always creates an object
            raise ValueError("context payload must be a JSON object")
        return value

    def canonical_body(self) -> bytes:
        return canonical_json_bytes(
            {
                "compiler_version": self.compiler_version,
                "graph_version": self.graph_version,
                "missing_policy": self.missing_policy,
                "omissions": [omission.as_dict() for omission in self.omissions],
                "payload": self.payload_object(),
                "refs": self.refs.as_list(),
                "schema_version": self.schema_version,
            }
        )

    def as_record(self) -> dict[str, Any]:
        return {**json.loads(self.canonical_body()), "digest": self.digest}


@dataclass(frozen=True)
class ContextDelivery:
    """The per-native-session decision for one immutable bundle."""

    action: DeliveryAction
    native_session_id: str
    digest: str


def compile_context(
    layout: ProjectLayout,
    refs: RefSet,
    *,
    missing: MissingReferencePolicy = "error",
    expected_graph_version: int | None = None,
    schema_version: str = CONTEXT_SCHEMA_VERSION,
    compiler_version: str = CONTEXT_COMPILER_VERSION,
) -> ContextBundle:
    """Resolve only ``refs`` into deterministic, untrusted reference material."""
    if missing not in {"error", "omit"}:
        raise ValueError("missing must be 'error' or 'omit'")

    start_graph_version = layout.load_manifest().graph_version
    if expected_graph_version is not None and expected_graph_version != start_graph_version:
        raise ContextSnapshotError(
            f"expected graph_version={expected_graph_version}, found {start_graph_version}"
        )

    omissions: list[ContextOmission] = []
    references: list[dict[str, Any]] = []
    resolvers: dict[ReferenceKind, Any] = {
        "node": load_node,
        "edge": load_edge,
        "port": load_port,
    }
    for ref in refs.refs:
        try:
            entity = resolvers[ref.kind](layout, ref.ref_id)
        except (FileNotFoundError, OSError, ValueError) as exc:
            message = f"{ref.kind} reference {ref.ref_id!r} cannot be resolved: {exc}"
            if missing == "error":
                raise ContextReferenceError(message) from exc
            omissions.append(ContextOmission(kind=ref.kind, ref_id=ref.ref_id, reason="not_found"))
            continue
        references.append(_reference_record(ref.kind, entity))

    payload_object: dict[str, Any] = {
        "instruction": [],
        "reference": references,
    }
    payload = canonical_json_bytes(payload_object)
    end_graph_version = layout.load_manifest().graph_version
    if end_graph_version != start_graph_version:
        raise ContextSnapshotError(
            "graph changed while compiling context "
            f"(start={start_graph_version}, end={end_graph_version})"
        )
    body = canonical_json_bytes(
        {
            "compiler_version": compiler_version,
            "graph_version": start_graph_version,
            "missing_policy": missing,
            "omissions": [omission.as_dict() for omission in omissions],
            "payload": payload_object,
            "refs": refs.as_list(),
            "schema_version": schema_version,
        }
    )
    return ContextBundle(
        schema_version=schema_version,
        compiler_version=compiler_version,
        missing_policy=missing,
        refs=refs,
        graph_version=start_graph_version,
        payload=payload,
        omissions=tuple(omissions),
        digest=hashlib.sha256(body).hexdigest(),
    )


def context_bundle_path(layout: ProjectLayout, digest: str) -> Path:
    _validate_digest(digest)
    return layout.dot_dir / "agent" / "contexts" / f"{digest}.json"


def store_context_bundle(layout: ProjectLayout, bundle: ContextBundle) -> Path:
    """Store a bundle once under its digest and return its content-addressed path."""
    if hashlib.sha256(bundle.canonical_body()).hexdigest() != bundle.digest:
        raise ValueError("context bundle digest does not match its canonical body")
    path = context_bundle_path(layout, bundle.digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = canonical_json_bytes(bundle.as_record())
    if not path.exists():
        _atomic_write(path, expected)
    elif path.read_bytes() != expected:
        raise ValueError(f"context bundle corruption or digest collision at {path}")
    return path


def decide_context_delivery(
    layout: ProjectLayout, native_session_id: str, bundle: ContextBundle
) -> ContextDelivery:
    """Read whether a native session needs this bundle this turn.

    Callers MUST invoke :func:`mark_context_sent` only after their provider
    actually accepts the supplement; this function never changes the ledger.
    """
    if not native_session_id:
        raise ValueError("native_session_id must be non-empty")
    path = _sent_context_path(layout, native_session_id)
    sent = _read_sent_digests(path)
    digests = sent.get("digests", [])
    if bundle.digest in digests:
        return ContextDelivery("skip", native_session_id, bundle.digest)
    return ContextDelivery("send", native_session_id, bundle.digest)


def mark_context_sent(
    layout: ProjectLayout, native_session_id: str, bundle: ContextBundle
) -> None:
    """Persist an immutable bundle after a successful provider send."""
    if not native_session_id:
        raise ValueError("native_session_id must be non-empty")
    store_context_bundle(layout, bundle)
    path = _sent_context_path(layout, native_session_id)
    sent = _read_sent_digests(path)
    digests = sent.setdefault("digests", [])
    if bundle.digest not in digests:
        digests.append(bundle.digest)
        sent["native_session_id"] = native_session_id
        _atomic_write(path, canonical_json_bytes(sent))


def _reference_record(kind: str, entity: Node | Edge | Port) -> dict[str, Any]:
    # attrs are deliberately kept below the reference boundary, never elevated
    # to an instruction or provider system-prompt channel.
    source = MappingProxyType({"kind": kind, "id": entity.id})
    return {
        "source": dict(source),
        "entity": entity.model_dump(mode="json"),
    }


def _sent_context_path(layout: ProjectLayout, native_session_id: str) -> Path:
    session_hash = hashlib.sha256(native_session_id.encode("utf-8")).hexdigest()
    return layout.dot_dir / "agent" / "sent-contexts" / f"{session_hash}.json"


def _read_sent_digests(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("sent context digest store must be a JSON object")
    session_id = raw.get("native_session_id")
    digests = raw.get("digests")
    if not isinstance(session_id, str) or not isinstance(digests, list):
        raise ValueError("sent context digest store has an invalid entry")
    if not all(isinstance(digest, str) for digest in digests):
        raise ValueError("sent context digest store has a non-string digest")
    return {"native_session_id": session_id, "digests": list(dict.fromkeys(digests))}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _validate_digest(digest: str) -> None:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("digest must be a lowercase SHA-256 hex digest")
