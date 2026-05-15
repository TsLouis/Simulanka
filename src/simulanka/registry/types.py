from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PortDirection = Literal["in", "out"]
ANY = "*"


@dataclass(frozen=True)
class NodeTypeSpec:
    name: str
    allow_parents: frozenset[str | None]  # `None` means root is allowed; `"*"` means any type

    def accepts_parent(self, parent_type: str | None) -> bool:
        if parent_type is None:
            return None in self.allow_parents
        return ANY in self.allow_parents or parent_type in self.allow_parents


@dataclass(frozen=True)
class EdgeTypeSpec:
    name: str
    needs_ports: bool
    source_node_types: frozenset[str]   # `"*"` = any
    target_node_types: frozenset[str]
    source_port_direction: PortDirection | None = None
    target_port_direction: PortDirection | None = None

    def accepts_source_type(self, t: str) -> bool:
        return ANY in self.source_node_types or t in self.source_node_types

    def accepts_target_type(self, t: str) -> bool:
        return ANY in self.target_node_types or t in self.target_node_types
