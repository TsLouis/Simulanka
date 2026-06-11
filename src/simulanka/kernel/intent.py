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
    """Shallow-merge ``attrs`` into an existing node's or edge's ``attrs`` dict.

    Keys present in ``attrs`` overwrite existing keys; keys not mentioned are
    preserved. There is no delete semantics in this op — to remove a key, use
    a future ``delete_attr`` op (not in Alpha).

    Edges are addressed by id only (``edg_…``) — they have no path selectors.
    Added for the §13.6 verify-discuss loop (verdict/note write-back onto
    ``data_flow`` edges); the kernel keeps it general for any edge attrs.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["update_attrs"] = "update_attrs"
    target: str           # node selector, or edge id ("edg_…")
    attrs: dict[str, Any] = Field(default_factory=dict)


class RenameNodeOp(BaseModel):
    """Change a node's ``name`` field. Sibling-unique under the same parent.

    Callers that also need to update side-effect attrs (e.g. ``fs_path`` on
    file/directory nodes) should pair this with an ``UpdateAttrsOp`` in the
    same ``PatchIntent`` — the kernel touches graph state only.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rename_node"] = "rename_node"
    target: str           # node selector
    new_name: str


class DeleteEdgeOp(BaseModel):
    """Remove one edge by id. The only deletion op in the kernel (Alpha).

    Refuses structural ``contains`` edges: they are dual-written with their
    child node and back the denormalised ``parent_id`` cache, so dropping one
    in isolation would orphan the hierarchy. Non-structural relations
    (``data_flow`` and the like) are free to delete — nothing holds a foreign
    key to an edge. Intended for the §13 draw/undo loop (remove a user-drawn
    or agent-rejected ``data_flow`` edge); the kernel keeps the primitive
    general and leaves "which edges a UI offers to remove" policy to callers.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["delete_edge"] = "delete_edge"
    edge: str  # edge id (e.g. "edg_…")


IntentOp = Annotated[
    CreateNodeOp
    | CreatePortOp
    | CreateEdgeOp
    | UpdateAttrsOp
    | RenameNodeOp
    | DeleteEdgeOp,
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
    updated_edges: list[str] = Field(default_factory=list)
    deleted_edges: list[str] = Field(default_factory=list)
