"""
Module system: Module, NameCache.
"""

from dataclasses import dataclass

from . import core
from .ty import Name
from .tything import TyThing

@dataclass
class Module:
    """Complete compilation result. Stored in HPT."""
    name: str
    tythings: list[tuple[Name, TyThing]]
    bindings: list[core.Binding]
    exports: list[Name]
    _tythings_map: dict[Name, TyThing]
    source_path: str | None = None

    @staticmethod
    def create(name, tythings, bindings) -> Module:
        exports = [n for n, _ in tythings]
        tythings_map = {n: t for n, t in tythings}
        return Module(name=name, tythings=tythings, bindings=bindings, exports=exports, _tythings_map=tythings_map)

    def lookup_tything(self, name: Name) -> TyThing | None:
        return self._tythings_map.get(name)
