from abc import ABC
from dataclasses import dataclass
import functools
from typing import Callable

from systemf.utils.uniq import Uniq

from .ty import Id, Ty, TyVar, TyFun, zonk_type
from .core import CoreTm, C
from .protocols import NameGenerator


class Wrapper(ABC): ...
"""
like HsWrapper, the translation snippets from Surface to Core, produced by type inference
"""


@dataclass
class WpHole(Wrapper): ...


WP_HOLE = WpHole()


@dataclass
class WpCast(Wrapper):
    """
    A type cast wrapper.

    TODO: I think it's just temporary to witness the fact that meta tv == some type.
          which after type inference should be equivalent to WpHole. Needs confirmation.
    """

    ty_from: Ty
    ty_to: Ty


@dataclass
class WpFun(Wrapper):
    """
    This wraps a function.
    say it's e: a -> b, then builds: \\x:arg_ty -> wp_res (e (wp_arg x))
    """

    arg_ty: Ty
    wp_arg: Wrapper
    wp_res: Wrapper


def wp_fun(arg_ty: Ty, wp_arg: Wrapper, wp_res: Wrapper) -> Wrapper:
    if wp_arg == WP_HOLE and wp_res == WP_HOLE:
        return WP_HOLE
    return WpFun(arg_ty, wp_arg, wp_res)


def mk_wp_eta(ty: Ty, wp_body: Wrapper) -> Wrapper:
    """
    Constructs Eta conversion wrapper with WpFun.
    eg. a -> b -> c, wp_body creates \\x:a -> \\y:b -> wp_body (e x y)
    binders are not relevant here, it's created and used all by us.
    but should be not in fv(e)
    """

    # supose to be used in skolemise, but our skolemise process layer by layer
    # so each layer it constructs it's own WpFun
    def _go(ty: Ty) -> Wrapper:
        match ty:
            case TyFun(arg_ty, res_ty):
                return wp_fun(arg_ty, WP_HOLE, _go(res_ty))
            case _:
                return wp_body

    return _go(ty)


@dataclass
class WpTyApp(Wrapper):
    ty_arg: Ty


@dataclass
class WpTyLam(Wrapper):
    ty_var: TyVar


def mk_wp_ty_lams(tvs: list[TyVar], w: Wrapper) -> Wrapper:
    if tvs:
        return functools.reduce(lambda acc, tv: WpCompose(WpTyLam(tv), acc), reversed(tvs), w)
    return w


@dataclass
class WpCompose(Wrapper):
    """
    apply f first, then g.
    g . f
    """

    wp_g: Wrapper
    wp_f: Wrapper


def wp_compose(wp_g: Wrapper, wp_f: Wrapper) -> Wrapper:
    """
    Smart WpCompose that simplifies WP_HOLE cases.
    """
    if wp_g == WP_HOLE:
        return wp_f
    if wp_f == WP_HOLE:
        return wp_g
    return WpCompose(wp_g, wp_f)


def zonk_wrapper(wp: Wrapper) -> Wrapper:
    match wp:
        case WpCompose(wp_g, wp_f):
            return wp_compose(zonk_wrapper(wp_g), zonk_wrapper(wp_f))
        case WpFun(arg_ty, wp_arg, wp_res):
            return wp_fun(zonk_type(arg_ty), zonk_wrapper(wp_arg), zonk_wrapper(wp_res))
        case WpTyApp(ty_arg):
            return WpTyApp(zonk_type(ty_arg))
        case WpCast(ty_from, ty_to):
            zty_from = zonk_type(ty_from)
            zty_to = zonk_type(ty_to)
            if zty_from == zty_to:
                return WP_HOLE
            return WpCast(zty_from, zty_to)
        case _:
            return wp


class WrapperRunner:
    """
    Run a wrapper to get a CoreTm.
    """
    name_gen: NameGenerator

    def __init__(self, name_gen: NameGenerator):
        self.name_gen = name_gen
    
    def _make_uniq_var(self):
        return self.name_gen.new_name(lambda i: f"_gensym_{i}", None)

    def run_wrapper(self, wp: Wrapper, term: CoreTm) -> CoreTm:
        """
        Run the wrapper on the term, producing a new CoreTm.
        """
    
        def _go(wp, e) -> CoreTm:
            match wp:
                case WpHole():
                    return e
                case WpCast(ty_from, ty_to) if ty_from == ty_to:
                    return e
                case WpCast(ty_from, ty_to):
                    raise Exception(f"type mismatch: expected {ty_from}, got {ty_to}")
                case WpFun(arg_ty, wp_arg, wp_res):
                    var = Id(self._make_uniq_var(), arg_ty)
                    arg = _go(wp_arg, C.var(var))
                    res = _go(wp_res, C.app(e, arg))
                    return C.lam(var, res)
                case WpTyApp(ty_arg):
                    return C.tyapp(e, ty_arg)
                case WpTyLam(ty_var):
                    # BoundTv, SkolemTv, both are valid
                    return C.tylam(ty_var, e)
                case WpCompose(wp_g, wp_f):
                    return _go(wp_g, _go(wp_f, e))
                case _:
                    raise Exception("impossible")

        return _go(wp, term)
