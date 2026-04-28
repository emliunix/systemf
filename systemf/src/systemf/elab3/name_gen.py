from typing import Callable
from collections.abc import Iterable

from systemf.elab3.types import Name, REPLContext
from systemf.elab3.builtins import BUILTIN_NAMES
from systemf.elab3.types.protocols import NameGenerator
from systemf.elab3.types.ty import Id, Ty
from systemf.utils.location import Location
from systemf.utils.uniq import Uniq


class NameCacheImpl:
    """
    NameCache is only for toplevel names of a module.
    """

    def __init__(self):
        self.names = {
            (mod, name.surface): name
            for (mod, names) in BUILTIN_NAMES.items()
            for name in names
        }

    def get(self, module: str, name: str) -> Name | None:
        """Get Name for the given module and surface name."""
        key = (module, name)
        if key in self.names:
            return self.names[key]
        return None
    
    def put(self, name: Name):
        self.names[(name.mod, name.surface)] = name

    def put_all(self, names: Iterable[Name]):
        for name in names:
            self.put(name)


class NameGeneratorImpl(NameGenerator):
    mod_name: str
    uniq: Uniq

    def __init__(self, mod_name: str, uniq: Uniq):
        self.mod_name = mod_name
        self.uniq = uniq

    def new_name(self, name: str | Callable[[int], str], loc: Location | None) -> Name:
        if isinstance(name, str):
            return Name(self.mod_name, name, self.uniq.make_uniq(), loc)
        else:
            u = self.uniq.make_uniq()
            return Name(self.mod_name, name(u), u, loc)

    def new_id(self, name: str | Callable[[int], str], ty: Ty) -> Id:
        return Id(self.new_name(name, None), ty)
    

def check_dups(names: Iterable[str], loc: Location | None = None):
    s: set[str] = set()
    for n in names:
        if n in s:
            raise Exception(f"duplicate param names: {n} at {loc}")
        s.add(n)
