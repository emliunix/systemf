from collections.abc import Iterable
from typing import Any, Callable, Protocol, runtime_checkable

from systemf.utils.location import Location

from .ast import ImportDecl
from .mod import Module
from .ty import Id, Name, Ty
from .val import Val
from .core import CoreTm
from .tything import AnId, TyThing

from systemf.utils.uniq import Uniq


class NameCache(Protocol):
    def get(self, module: str, name: str) -> Name | None:
        """Get Name for the given module and surface name."""
        ...
    def put(self, name: Name): ...
    def put_all(self, names: Iterable[Name]): ...


class TyLookup(Protocol):
    def lookup(self, name: Name) -> TyThing: ...


class REPLContext(Protocol):
    uniq: Uniq
    name_cache: NameCache

    def load(self, name: str) -> Module: ...
    def next_replmod_id(self) -> int: ...


class REPLSessionProto(TyLookup, Protocol):
    """
    For use in Synthesizer
    """
    @property
    def state(self) -> dict[str, Any]: ...
    def fork(self) -> REPLSessionProto: ...
    def add_args(self, args: list[tuple[str, Val, Ty]]) -> None: ...
    def add_return(self, ref: list[Val | None], ty: Ty) -> None: ...
    def add_import(self, decl: ImportDecl) -> None: ...
    async def eval(self, input: str) -> tuple[Val, Ty] | None: ...
    # for programmatic calling
    # 1. it's expr only, so no new def/bindings added
    # 2. we don't have a valid/easy way to input surface ast programmatically
    # 3. the use case is mainly for value passing like big chunk of LitString
    async def unsafe_eval(self, input: CoreTm) -> Val:
        """The untyped variant of eval"""
        ...


class NameGenerator(Protocol):
    def new_name(self, name: str | Callable[[int], str], loc: Location | None) -> Name: ...
    def new_id(self, name: str | Callable[[int], str], ty: Ty) -> Id: ...


@runtime_checkable
class Synthesizer(Protocol):
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None: ...


class Ext(Protocol):
    @property
    def name(self) -> str: ...
    def search_paths(self) -> list[str]: ...
    def synthesizers(self) -> list[dict[str, Synthesizer] | Synthesizer] | None: ...
