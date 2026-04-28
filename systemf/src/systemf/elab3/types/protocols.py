from collections.abc import Iterable
from typing import Callable, Protocol

from systemf.utils.location import Location

from .ast import ImportDecl
from .mod import Module
from .ty import Id, Name, Ty
from .val import Val
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
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None: ...


class REPLSessionProto(TyLookup, Protocol):
    def fork(self) -> REPLSessionProto: ...
    def cmd_add_args(self, args: list[tuple[str, Val, Ty]]) -> None: ...
    def cmd_add_return(self, ref: list[Val | None], ty: Ty) -> None: ...
    def cmd_import(self, decl: ImportDecl) -> None: ...
    def eval(self, input: str) -> tuple[Val, Ty] | None: ...


class NameGenerator(Protocol):
    def new_name(self, name: str | Callable[[int], str], loc: Location | None) -> Name: ...
    def new_id(self, name: str | Callable[[int], str], ty: Ty) -> Id: ...


class Synthesizer(Protocol):
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None: ...


class PrimOpsSynth(Synthesizer):
    """A simple synthesizer that provides primitive operations from a given dictionary."""
    ops: dict[str, Val]

    def __init__(self, ops: dict[str, Val]):
        self.ops = ops

    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        return self.ops.get(name.surface)


class Ext(Protocol):
    @property
    def name(self) -> str: ...
    def search_paths(self) -> list[str]: ...
    def synthesizer(self) -> dict[str, Synthesizer] | None: ...
