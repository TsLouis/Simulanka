from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FileBinding = Literal["managed", "reference"]


@dataclass(frozen=True)
class FileKindSpec:
    name: str
    dir_name: str                       # top-level directory under project root
    binding: FileBinding
    default_extension: str | None = None
    name_prefix: str | None = None


FILE_KINDS: dict[str, FileKindSpec] = {
    "code": FileKindSpec(
        name="code", dir_name="src", binding="managed", default_extension=".py",
    ),
    "test": FileKindSpec(
        name="test", dir_name="tests", binding="managed",
        default_extension=".py", name_prefix="test_",
    ),
    "doc": FileKindSpec(
        name="doc", dir_name="docs", binding="managed", default_extension=".md",
    ),
    "paper": FileKindSpec(
        name="paper", dir_name="papers", binding="managed", default_extension=".md",
    ),
    "baseline": FileKindSpec(
        name="baseline", dir_name="baselines", binding="reference",
    ),
    "config": FileKindSpec(
        name="config", dir_name="configs", binding="managed",
        default_extension=".yaml",
    ),
    "artifact": FileKindSpec(
        name="artifact", dir_name=".simulanka/artifacts", binding="managed",
    ),
    # §14 research loop: analyst plans and their deterministic inverse, briefs.
    # One shared top-level dir; the prefix alone tells the round's artefacts apart.
    "plan": FileKindSpec(
        name="plan", dir_name="research", binding="managed",
        default_extension=".md", name_prefix="plan-",
    ),
    "brief": FileKindSpec(
        name="brief", dir_name="research", binding="managed",
        default_extension=".md", name_prefix="brief-",
    ),
}


def managed_dir_names() -> set[str]:
    """Top-level directory names that FileRegistry owns."""
    return {spec.dir_name for spec in FILE_KINDS.values()}
