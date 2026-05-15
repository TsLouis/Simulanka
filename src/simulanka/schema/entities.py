from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    name: str
    parent_id: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str


class Port(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    node_id: str
    name: str
    direction: Literal["in", "out"]
    port_type: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    source_id: str
    target_id: str
    source_port_id: str | None = None
    target_port_id: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str
