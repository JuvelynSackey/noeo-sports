"""Shared helper for defensively parsing provider strings into our enums."""
from __future__ import annotations

from typing import TypeVar

E = TypeVar("E")


def safe_enum(enum_cls: type[E], value: str | None, default: E) -> E:
    if value is None:
        return default
    try:
        return enum_cls(value)  # type: ignore[call-arg]
    except ValueError:
        return default
