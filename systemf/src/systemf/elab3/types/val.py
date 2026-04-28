from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
class VPartial(Val):
    """Partially-applied constructor or primop."""
    name: str
    arity: int
    done: list[Val]
    finish: Callable[[list[Val]], Val]

    @staticmethod
    def create(name: str, arity: int, finish: Callable[[list[Val]], Val]) -> Val:
        if arity == 0:
            return finish([])
        else:
            return VPartial(name, arity, [], finish)


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
