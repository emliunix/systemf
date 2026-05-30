from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")
K = TypeVar("K")


def get_or_create(d: dict[K, T], key: K, factory: Callable[[K], T]) -> T:
    if key not in d:
        d[key] = factory(key)
    return d[key]
