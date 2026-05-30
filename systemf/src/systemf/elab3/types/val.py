from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pyrsistent import PMap, pmap

from .ty import Lit, Id
from .core import CoreTm


# Environment: Name.unique -> Val
type Env = PMap[int, Val]


class Val:
    pass

@dataclass
class VLit(Val):
    lit: Lit


@dataclass
class VPrim(Val):
    val: Any


@dataclass
class VAsync(Val):
    val: Coroutine[None, None, Val]


@dataclass
class VData(Val):
    """Fully-applied data constructor."""
    tag: int
    vals: list[Val]


@dataclass
class VClosure(Val):
    """Lambda closure."""
    env: Env
    param: Id
    body: CoreTm


@dataclass
class Trap(Val):
    """Mutable forward reference used to implement letrec."""
    v: Val | None = None

    def set(self, v: Val) -> None:
        self.v = v


@dataclass(repr=False)
class CoreValUnsafe(CoreTm):
    """Special value wrapper for passing Val to unsafe_eval."""
    val: Val


@runtime_checkable
class HasDoc(Protocol):
    """Protocol for values that has doc attached."""

    def doc(self) -> str:
        """Return a human-readable documentation string for this value."""
        ...
