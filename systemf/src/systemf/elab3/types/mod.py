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
