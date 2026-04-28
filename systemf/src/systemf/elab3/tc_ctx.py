"""
bidirectional type checking for the surface language.
supports:
    - data types
    - patterns
    - recursion groups (discovered by SCC analysis)
"""

import functools

from abc import ABC, abstractmethod
from contextlib import contextmanager
from collections.abc import Generator
from dataclasses import dataclass
from typing import Callable, cast

from systemf.elab3.builtins import BUILTIN_ERROR


from .types import Name
from .types.core import C, CoreTm
from .types.tything import ACon, APrimTy, ATyCon, AnId, TyThing, TypeEnv
from .types.wrapper import WP_HOLE, WpCast, WpTyApp, WpTyLam, Wrapper, wp_compose, wp_fun
from .types.ty import BoundTv, LitString, MetaTv, Ref, SkolemTv, Ty, TyConApp, TyForall, TyFun, TyInt, TyString, TyVar, get_meta_vars, subst_ty, varnames, zonk_type
from .types.tc import *

from systemf.utils.uniq import Uniq


class TcCtx(ABC):
    mod_name: str
    uniq: Uniq
    type_env: TypeEnv
    tc_level: int

    def __init__(self, mod_name: str, uniq: Uniq, init_type_env: TypeEnv | None = None):
        self.mod_name = mod_name
        self.uniq = uniq
        self.type_env = init_type_env if init_type_env is not None else {}
        self.tc_level = 0

    @contextmanager
    def extend_env(self, name_things: list[tuple[Name, TyThing]]) -> Generator[None, None, None]:
        for (name, thing) in name_things:
            self.type_env[name] = thing
        try:
            yield
        finally:
            for (name, _) in name_things:
                if name in self.type_env:
                    del self.type_env[name]

    @contextmanager
    def push_level(self) -> Generator[None, None, None]:
        self.tc_level += 1
        try:
            yield
        finally:
            self.tc_level -= 1

    # ---
    # type env

    @abstractmethod
    def lookup_gbl(self, name: Name) -> TyThing: ...

    def lookup_local(self, name: Name) -> TyThing | None:
        return self.type_env.get(name)

    def lookup(self, name: Name) -> TyThing:
        if (th := self.lookup_local(name)) is not None:
            return th
        if name.mod == self.mod_name:
            raise Exception(f"local name not found: {name}")
        return self.lookup_gbl(name)

    def lookup_tycon(self, name: Name) -> ATyCon:
        match self.lookup(name):
            case ATyCon() as a:
                return a
            case APrimTy() as a:
                raise Exception(f"Expected tycon, but got a prim type: {a}")
            case a:
                raise Exception(f"Expected tycon, but got: {a}")
            
    def lookup_datacon(self, name: Name) -> ACon:
        match self.lookup(name):
            case ACon() as a:
                return a
            case a:
                raise Exception(f"Expected datacon, but got: {a}")

    # ---
    # uniq vars

    def make_meta(self, gv_lvl: int | None = None) -> MetaTv:
        lvl = gv_lvl if gv_lvl is not None else self.tc_level
        return MetaTv(self.uniq.make_uniq(), lvl, Ref())

    def make_skolem(self, name: Name | Callable[[int], str], gv_lvl: int | None = None) -> SkolemTv:
        lvl = gv_lvl if gv_lvl is not None else self.tc_level
        uniq = self.uniq.make_uniq()
        if callable(name):
            name = Name(self.mod_name, name(uniq), uniq, None)
        return SkolemTv(name, uniq, lvl)

    # --
    # infer cell

    def make_infer(self, gv_lvl: int | None = None) -> Infer:
        lvl = gv_lvl if gv_lvl is not None else self.tc_level
        return Infer(lvl, Ref())


class Unifier(TcCtx, ABC):

    def __init__(self, mod_name: str, uniq: Uniq, init_type_env: TypeEnv | None = None):
        super().__init__(mod_name, uniq, init_type_env)

    # ---
    # subsumption check

    def subs_check(self, sigma1: Ty, sigma2: Ty) -> Wrapper:
        """
        Subsumption check between two types.

        sigma1 can be instantiated to sigma2.
        The wrapper is sigma1 ~~> sigma2.
        """
        with self.push_level():
            _, rho2, sks_wrap = self.skolemise(sigma2)  # rho2 ~~> sigma2
            subs_wrap = self.subs_check_rho(sigma1, rho2)  # sigma1 ~~> rho2
        # skolem var escape is not possible by construction with levels
        return wp_compose(sks_wrap, subs_wrap)

    def subs_check_rho(self, sigma: Ty, rho: Ty) -> Wrapper:
        sigma = zonk_type(sigma)
        rho = zonk_type(rho)
        match (sigma, rho):
            case (TyForall(), _):          # DSK/SPEC
                in_rho, in_wrap = self.instantiate(sigma)
                res_wrap = self.subs_check_rho(in_rho, rho)
                return wp_compose(res_wrap, in_wrap)
            case (rho1, TyFun(a2, r2)):    # DSK/FUN
                (a1, r1) = self.unify_fun(rho1)
                return self.subs_check_fun(a1, r1, a2, r2)
            case (TyFun(a1, r1), rho2):
                (a2, r2) = self.unify_fun(rho2)
                return self.subs_check_fun(a1, r1, a2, r2)
            case (tau1, tau2):             # DSK/MONO
                self.unify(tau1, tau2)
                return WpCast(tau1, tau2)

    def subs_check_fun(self, a1: Ty, r1: Ty, a2: Ty, r2: Ty) -> Wrapper:
        # a2 ~> a1
        arg_wrap = self.subs_check(a2, a1)     # contravariant
        # r1 ~> r2
        res_wrap = self.subs_check_rho(r1, r2) # covariant
        # (a1 -> r1) ~> (a2 -> r2)
        return wp_fun(a2, arg_wrap, res_wrap)

    # ---
    # helpers

    def skolemise_shallow(self, ty: Ty, gv_lvl: int | None = None) -> tuple[list[SkolemTv], Ty, Wrapper]:

        def _split_foralls(ty: Ty) -> tuple[list[TyVar], Ty]:
            match ty:
                case TyForall(tvs, body):
                    tvs2, body2 = _split_foralls(body)
                    return tvs + tvs2, body2
                case _: return [], ty

        tvs, body = _split_foralls(ty)
        sks = [self.make_skolem(name, gv_lvl) for name in varnames(tvs)]
        sks_ty = subst_ty(tvs, cast(list[Ty], sks), body)
        wrap = functools.reduce(lambda acc, w: wp_compose(WpTyLam(w), acc), reversed(sks), WP_HOLE)
        return sks, sks_ty, wrap
    
    def skolemise(self, ty: Ty) -> tuple[list[SkolemTv], Ty, Wrapper]:
        """
        Create weak prenex formed rho type with skolemise type vars filled

        The wrapper created is the witness of rho to sigma.
        eg. sa → sb → sa ~~> ∀a. a → ∀b. b → a
        where sa, sb are skolem vars
        """
        match ty:
            case TyForall(tvs, body):
                sks1 = [self.make_skolem(name) for name in varnames(tvs)]
                sks2, ty2, sk_wrap = self.skolemise(subst_ty(tvs, cast(list[Ty], sks1), body))
                # /\sk1. /\sk2. ... /\ skn. sk_wrap body
                res_wrap = functools.reduce(lambda acc, w: wp_compose(WpTyLam(w), acc), reversed(sks1), sk_wrap)
                return sks1 + sks2, ty2, res_wrap
            case TyFun(arg_ty, res_ty):
                sks, res_ty2, wrap = self.skolemise(res_ty)
                # a -> rho
                # => a -> sigma
                res_wrap = wp_fun(arg_ty, WP_HOLE, wrap)
                return sks, TyFun(arg_ty, res_ty2), res_wrap
            case _:
                # ~~subst_ty _ ty for type constructor~~
                # never gonna be the case, TyConApp args are always mono types
                return [], ty, WP_HOLE

    def instantiate(self: TcCtx, sigma: Ty) -> tuple[Ty, Wrapper]:
        """
        Instantiate top-level forall type variables in sigma with fresh meta variables.
        sigma -> rho
        """
        match sigma:
            case TyForall(vars, ty):
                mvs: list[Ty] = [self.make_meta() for _ in vars]
                inst_ty = subst_ty(vars, mvs, ty)
                wrap = functools.reduce(lambda acc, ty: wp_compose(WpTyApp(ty), acc), mvs, WP_HOLE)
                return inst_ty, wrap
            case _:  # not a sigma type
                return sigma, WP_HOLE

    def unify_fun(self, ty: Ty) -> tuple[Ty, Ty]:
        """
        Match a function type, or unify it to a function
        with new meta argument and result.
        """
        match ty:
            case TyFun(ty1, ty2):
                return (ty1, ty2)
            case MetaTv(level=lvl) as m: # it must be a meta
                arg_ty = self.make_meta(gv_lvl=lvl)
                res_ty = self.make_meta(gv_lvl=lvl)
                self.unify(ty, TyFun(arg_ty, res_ty))
                return (arg_ty, res_ty)
            case _: raise Exception(f"Cant unify to function type, got: {ty}")

    def exp_to_ty(self, exp: Expect) -> Ty:
        match exp:
            case Infer(ref=ref):
                if (ty := ref.get()) is not None:
                    return ty
                mty = self.make_meta()
                ref.set(mty)
                return mty
            case Check(ty):
                return ty

    def unify(self, ty1: Ty, ty2: Ty):
        match ty1, ty2:
            case (TyInt(), TyInt()):
                pass
            case (TyString(), TyString()):
                pass
            case (BoundTv(), _) | (_, BoundTv()):
                raise Exception(f"Unexpected bound type variables to unify, got {ty1} and {ty2}")
            case (SkolemTv() as sk1, SkolemTv() as sk2) if sk1 == sk2:
                pass
            case (MetaTv() as m1, MetaTv() as m2) if m1 == m2:
                pass
            case (TyConApp(n1, args1), TyConApp(n2, args2)):
                if n1 == n2 and len(args1) == len(args2):
                    # get arity from the real tycon to check args length with
                    for a1, a2 in zip(args1, args2):
                        self.unify(a1, a2)
                else:
                    raise Exception(f"Cannot unify type constructors, got {ty1} and {ty2}")
            case (MetaTv() as m, ty):
                self.unify_var(m, ty)
            case (ty, MetaTv() as m):
                self.unify_var(m, ty)
            case TyFun(a1, r1), TyFun(a2, r2):
                # that means on construction, fun type are probed and
                # fun of metas created instead of a single meta
                self.unify(a1, a2)
                self.unify(r1, r2)
            case _:
                raise Exception(f"Cannot unify types, got {ty1} and {ty2}")

    def unify_var(self, m: MetaTv, ty: Ty):
        """
        unify meta var to other type
        """
        match m:
            case MetaTv(ref=Ref(inner=None)):
                # bind right
                self.unify_unbound_var(m, ty)
            case MetaTv(ref=Ref(inner)) if inner:
                # unwrap left
                self.unify(inner, ty)

    def unify_unbound_var(self, m: MetaTv, ty: Ty):
        """
        unify unbound meta var to other type
        """
        if m in get_meta_vars([ty]):
            raise Exception(f"Occurrence check failed: got {m} in {ty}")
        match ty:
            case MetaTv(level=lvl2) as m2 if lvl2 > m.level:
                # promote
                mt = self.make_meta(m.level)
                m2.ref.set(mt)
                m.ref.set(mt)
            case SkolemTv(level=lvl2) as sk if lvl2 > m.level:
                raise Exception(f"Cannot unify meta variable {m} with skolem variable {sk}")
            case _:
                m.ref.set(ty)

    def fill_infer(self, infer: Infer, ty: Ty):
        match infer:
            case Infer(ref=Ref(ty2)) if ty2 is not None:
                self.unify(ty2, ty)
            case Infer(ref=ref):
                ref.set(ty)

    # ---
    # core terms helper

    def error_expr(self, ty: Ty, msg: str) -> CoreTm:
        match self.lookup(BUILTIN_ERROR):
            case AnId(id=id):
                return C.app(C.tyapp(C.var(id), ty), C.lit(LitString(msg)))
            case err: raise Exception(f"Builtin error has wrong type: {err}")

def binders_of_ty(ty: Ty) -> list[TyVar]:
    """
    Oppose to get_free_vars, this function returns the forall bound variables.
    """
    def _go(ty: Ty) -> Generator[TyVar, None, None]:
        match ty:
            case TyForall(vars, ty2):
                yield from vars
                yield from _go(ty2)
            case TyFun(arg_ty, res_ty):
                yield from _go(arg_ty)
                yield from _go(res_ty)
            case _:
                return None
    return list(_go(ty))
