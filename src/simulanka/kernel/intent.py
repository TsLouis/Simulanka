from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from simulanka.registry.types import PortDirection


class CreateNodeOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["create_node"] = "create_node"
    type: str
    name: str
    parent: str | None = None  # selector: id or absolute path; None = root
    attrs: dict[str, Any] = Field(default_factory=dict)


class CreatePortOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["create_port"] = "create_port"
    node: str             # node selector
    name: str
    direction: PortDirection
    port_type: str = "any"
    attrs: dict[str, Any] = Field(default_factory=dict)


class CreateEdgeOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["create_edge"] = "create_edge"
    type: str
    source: str          # node or port selector
    target: str
    attrs: dict[str, Any] = Field(default_factory=dict)


class UpdateAttrsOp(BaseModel):
    """Shallow-merge ``attrs`` into an existing node's ``attrs`` dict.

    Keys present in ``attrs`` overwrite existing keys; keys not mentioned are
    preserved. There is no delete semantics in this op — to remove a key, use
    a future ``delete_attr`` op (not in Alpha).
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["update_attrs"] = "update_attrs"
    target: str           # node selector
    attrs: dict[str, Any] = Field(default_factory=dict)


IntentOp = Annotated[
    CreateNodeOp | CreatePortOp | CreateEdgeOp | UpdateAttrsOp,
    Field(discriminator="kind"),
]


class PatchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ops: list[IntentOp]
    actor: str
    base_graph_version: int
    note: str | None = None


class Receipt(BaseModel):
    graph_version: int
    event_id: str
    nodes: list[str] = Field(default_factory=list)
    edges: list[str] = Field(default_factory=list)
    ports: list[str] = Field(default_factory=list)
    updated_nodes: list[str] = Field(default_factory=list)
