from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from simulanka.registry.types import PortDirection


class CreateNodeOp(BaseModel):
    """``ref`` is an intent-local handle: later ops in the same PatchIntent may
    select this not-yet-committed node as ``@<ref>`` (create_node.parent and
    create_edge endpoints). Never persisted — events record real ids only.
    Exists so multi-entity narratives (§14.7 plan ingest) can land atomically;
    the disk resolver cannot see pending nodes by design.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["create_node"] = "create_node"
    type: str
    name: str
    parent: str | None = None  # selector: id, absolute path, or @ref; None = root
    attrs: dict[str, Any] = Field(default_factory=dict)
    ref: str | None = None


class CreatePortOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["create_port"] = "create_port"
    node: str             # node selector
    name: str
    direction: PortDirection
    port_type: str = "any"
    attrs: dict[str, Any] = Field(default_factory=dict)


class UpdatePortOp(BaseModel):
    """Update one Port without implicitly rewriting incident Edges.

    ``attrs`` is a bounded shallow merge.  The kernel owns the allow-list so
    non-HTTP callers cannot bypass the authoring contract.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["update_port"] = "update_port"
    port: str
    name: str | None = None
    direction: PortDirection | None = None
    port_type: str | None = None
    attrs: dict[str, Any] | None = None


class DeletePortOp(BaseModel):
    """Delete one unconnected Port; incident Edges are never cascaded."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["delete_port"] = "delete_port"
    port: str


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
    """Remove one edge by id.

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


class DeleteNodeOp(BaseModel):
    """Remove one **empty** node, cascading everything that is *of* the node:
    its ports, and every edge incident to it — including the structural
    ``contains`` edge from its parent, whose removal here is the sanctioned
    reversal of the create-time dual-write (a lone DeleteEdgeOp still refuses
    it). A node with children is refused: subtree deletion must be explicit
    and bottom-up, so one op can never silently take out a hierarchy.
    Which node *types* a surface offers to delete is caller policy (the
    server restricts the canvas to module/model); the kernel enforces only
    structural integrity.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["delete_node"] = "delete_node"
    node: str  # node selector: id or absolute path


IntentOp = Annotated[
    CreateNodeOp
    | CreatePortOp
    | UpdatePortOp
    | DeletePortOp
    | CreateEdgeOp
    | UpdateAttrsOp
    | RenameNodeOp
    | DeleteEdgeOp
    | DeleteNodeOp,
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
    updated_ports: list[str] = Field(default_factory=list)
    deleted_edges: list[str] = Field(default_factory=list)
    deleted_nodes: list[str] = Field(default_factory=list)
    deleted_ports: list[str] = Field(default_factory=list)
