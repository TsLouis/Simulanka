from typing import Literal

from ulid import ULID

IdPrefix = Literal["nod", "edg", "prt", "prj", "evt"]


def new_id(prefix: IdPrefix) -> str:
    return f"{prefix}_{ULID()}"
