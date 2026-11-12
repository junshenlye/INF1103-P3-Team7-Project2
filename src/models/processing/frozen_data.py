"""Helpers for preserving nested processing data as detached read-only values."""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping


def freeze(value: Any) -> Any:
    """Return a recursively detached, immutable representation of ``value``."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze(item) for item in value)
    return deepcopy(value)
