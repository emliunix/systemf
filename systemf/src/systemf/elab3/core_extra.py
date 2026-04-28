import functools

from typing import cast

from .types import Ty
from .types.ty import Id, Name, TyConApp, TyForall, TyFun
from .types.tything import ACon, ATyCon
from .types.core import C, CoreTm
from .types.protocols import TyLookup

from . import builtins as bi


class CoreBuilderExtra:
    ctx: TyLookup

    def __init__(self, ctx: TyLookup) -> None:
        self.ctx = ctx

    def mk_tuple(self, elms: list[CoreTm], elm_tys: list[Ty]) -> tuple[CoreTm, Ty]:
        """Build a tuple term from a list of element terms."""
        if len(elms) != len(elm_tys):
            raise Exception(f"Number of elements {len(elms)} does not match number of types {len(elm_tys)}")
        if len(elms) < 2:
            raise Exception(f"Tuple must have at least 2 elements, got {len(elms)}")
        pair_tycon, mk_pair_con, mk_pair_ty = lookup_data_con(self.ctx, bi.BUILTIN_PAIR_MKPAIR)

        var_mk_pair = C.var(Id(mk_pair_con.name, mk_pair_ty))

        def _pair(right: tuple[CoreTm, Ty], left: tuple[CoreTm, Ty]) -> tuple[CoreTm, Ty]:
            left_tm, left_ty = left
            right_tm, right_ty = right
            res_ty = TyConApp(pair_tycon.name, [left_ty, right_ty])
            res_tm = C.app(C.app(C.tyapp(C.tyapp(var_mk_pair, left_ty), right_ty), left_tm), right_tm)
            return res_tm, res_ty

        return functools.reduce(_pair, reversed(list(zip(elms, elm_tys))))


def lookup_data_con_by_tag(ctx: TyLookup, tycon_name: Name, tag: int) -> tuple[ATyCon, ACon, Ty]:
    """Lookup a data constructor by its type constructor name and tag"""

    tycon = ctx.lookup(tycon_name)
    if not isinstance(tycon, ATyCon):
        raise Exception(f"Type constructor {tycon_name} not found")

    # ideally, it's just tycon.constructors[tag]
    # but let's just not make such assumpption
    for con in tycon.constructors:
        if con.tag == tag:
            return tycon, con, ty_con_fun(tycon, con)

    raise Exception(f"Data constructor with tag {tag} not found in type constructor {tycon_name}")


def lookup_data_con(ctx: TyLookup, name: Name) -> tuple[ATyCon, ACon, Ty]:
    """Lookup a data constructor by name, returning its type constructor and the constructor itself."""

    con = ctx.lookup(name)
    if not isinstance(con, ACon):
        raise Exception(f"Data constructor {name} not found")
    tycon = ctx.lookup(con.parent)
    if not isinstance(tycon, ATyCon):
        raise Exception(f"Type constructor {con.parent} for data constructor {name} not found")

    return tycon, con, ty_con_fun(tycon, con)

def ty_con_fun(tycon: ATyCon, con: ACon) -> Ty:
    res_ty = TyConApp(tycon.name, cast(list[Ty], tycon.tyvars))
    return TyForall(tycon.tyvars, functools.reduce(lambda res, arg: TyFun(arg, res), reversed(con.field_types), res_ty))
