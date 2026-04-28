"""
TyThing (type environment entries)
"""
from abc import ABC
from dataclasses import dataclass

from .ty import Id, Name, Ty, TyVar


@dataclass
class Metas:
    pragma: dict[str, str]
    doc: str | None
    arg_docs: list[str | None]

    @staticmethod
    def create(pragma: dict[str, str] | None, doc: str | None, arg_docs: list[str | None]) -> Metas:
        return Metas(pragma or {}, doc, arg_docs)


class TyThing(ABC):
    pass


@dataclass
class AnId(TyThing):
    """Term-level binding: variable or function."""
    name: Name
    id: Id
    is_prim: bool
    metas: Metas | None

    @staticmethod
    def create(id: Id, is_prim: bool = False, metas: Metas | None = None) -> AnId:
        return AnId(id.name, id, is_prim, metas)


@dataclass
class ATyCon(TyThing):
    """Type constructor (data type or type synonym)."""
    name: Name
    tyvars: list[TyVar]
    constructors: list[ACon]
    metas: Metas | None



@dataclass
class ACon(TyThing):
    """Data constructor."""
    name: Name
    tag: int
    arity: int
    field_types: list[Ty]
    parent: Name
    metas: Metas | None


@dataclass
class APrimTy(TyThing):
    """Primitives"""
    name: Name
    tyvars: list[TyVar]
    metas: Metas | None


type TypeEnv = dict[Name, TyThing]


def tything_name(thing: TyThing) -> Name:
    match thing:
        case AnId(name=name):
            return name
        case ATyCon(name=name):
            return name
        case ACon(name=name):
            return name
        case APrimTy(name=name):
            return name
        case _:
            raise Exception(f"Unknown TyThing {thing}")
