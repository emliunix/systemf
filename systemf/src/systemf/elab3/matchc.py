from collections import defaultdict
from dataclasses import dataclass
import functools
import itertools
from typing import Callable, TypeVar, cast

from systemf.elab3.builtins import BUILTIN_MK_UNIT, BUILTIN_UNIT
from systemf.elab3.tc_ctx import TcCtx
from systemf.elab3.types.tything import ACon
from systemf.utils import unzip

from .types import NameGenerator
from .types.ty import Id, Lit, Name, Ty, TyConApp, TyFun
from .types.core import Alt, CoreTm, C, DataAlt, DefaultAlt, LitAlt
from .types.wrapper import WrapperRunner
from .types.xpat import XPat, XPatCo, XPatLit, XPatCon, XPatVar, XPatWild


T = TypeVar("T")
R = TypeVar("R")


type DsWrapper = Callable[[CoreTm], CoreTm]


def dw_id(c: CoreTm) -> CoreTm:
    return c


def dw_compose(g: DsWrapper, f: DsWrapper) -> DsWrapper:
    if g == dw_id:
        return f
    elif f == dw_id:
        return g
    else:
        return lambda c: g(f(c))


@dataclass
class MRInfallible[T]:
    core: T


@dataclass
class MRFallible[T]:
    with_errorh: Callable[[CoreTm], T]


type MatchResult1[T] = MRInfallible[T] | MRFallible[T]
type MatchResult = MatchResult1[CoreTm]


type Equation = tuple[list[XPat], MatchResult]


@dataclass
class PGAny:
    pass


@dataclass
class PGCon:
    pass


@dataclass
class PGLit:
    pass


@dataclass
class PGCo:
    ty: Ty


type PG = PGAny | PGCon | PGLit | PGCo


def pat_group(pat: XPat) -> PG:
    match pat:
        case XPatLit():
            return PGLit()
        case XPatWild():
            return PGAny()
        case XPatCo(res_ty=ty):
            return PGCo(ty)
        case XPatCon():
            return PGCon()
        case _: raise Exception(f"unexpected pat, got: {pat}")


class MatchC:
    ctx: TcCtx
    name_gen: NameGenerator
    wp_runner: WrapperRunner

    def __init__(self, ctx: TcCtx, name_gen: NameGenerator):
        self.ctx = ctx
        self.name_gen = name_gen
        self.wp_runner = WrapperRunner(name_gen)

    def matchc(self, vars: list[Id], ty: Ty, eqns: list[Equation]) -> MatchResult:
        """Pattern matching compiler"""
        # base case
        if len(vars) == 0:
            def _check_eqn(eqn: Equation) -> MatchResult:
                ps, rhs = eqn
                if not len(ps) == 0:
                    raise Exception(f"invariant breaks, the equation doesn't match vars: {eqn}")
                return rhs
            return mr_chain([_check_eqn(eqn) for eqn in eqns])

        # column case
        [v, *vs] = vars  # split vars
        (col_, eqns_) = shift_eqn(eqns)

        # tidy
        def _tidy_eqn(p: XPat, eqn: Equation) -> tuple[XPat, Equation]:
            dw, p2 = self.tidy(v, p)
            # apply the binder to the RHS
            return p2, wrap_rhs(eqn, dw)
        (col_, eqns_) = unzip([_tidy_eqn(p, eqn) for p, eqn in zip(col_, eqns_)])

        # process groups
        def g_key(t: tuple[XPat, Equation]):
            p, _ = t
            return pat_group(p)
        groups = itertools.groupby([(pat, eqn) for pat, eqn in zip(col_, eqns_)], g_key)

        mrs = [self.mc_group(v, vs, ty, k, list(xs)) for k, xs in groups]
        return mr_chain(mrs)

    def tidy(self, v: Id, pat: XPat) -> tuple[DsWrapper, XPat]:
        match pat:
            case XPatWild():
                return (dw_id, pat)
            case XPatVar(v2):
                return (mk_bndr(v2, C.var(v)), XPatWild())
            case _:
                return (dw_id, pat)

    def mc_group(self, v: Id, vs: list[Id], ty: Ty, k: PG, pat_eqns: list[tuple[XPat, Equation]]) -> MatchResult:
        pats, eqns = unzip(pat_eqns)
        match k:
            case PGAny():
                return self.matchc(vs, ty, eqns)
            case PGCo(_):
                pat_co = cast(XPatCo, pats[0])
                co = self.wp_runner.run_wrapper(pat_co.co, C.var(v))
                v2 = self.name_gen.new_id(lambda i: f"_mc_co_{i}", pat_co.res_ty)
                return mr_map(
                    self.matchc([v2] + vs, ty, unshift_eqn([[cast(XPatCo, p).pat] for p in pats], eqns)),
                    mk_bndr(v2, co),
                )
            case PGCon():
                return self.mc_con(v, vs, ty, pats, eqns)
            case PGLit():
                return self.mc_lit(v, vs, ty, pats, eqns)

    def mc_lit(self, v: Id, vs: list[Id], ty: Ty, col: list[XPat], eqns: list[Equation]) -> MatchResult:
        def _by_lit(t: tuple[XPat, Equation]) -> Lit:
            match t:
                case (XPatLit(lit), _):
                    return lit
                case _: raise Exception("unreachable")

        groups = defaultdict(list)
        lit_order = []
        for t in zip(col, eqns):
            lit = _by_lit(t)
            if lit not in groups:
                lit_order.append(lit)
            groups[lit].append(t)

        def _go_grp(pat_eqns: list[tuple[XPat, Equation]]):
            _, eqns = unzip(pat_eqns)
            return self.matchc(vs, ty, eqns)

        return self.mk_lit_alts(v, ty, [(lit, _go_grp(list(groups[lit]))) for lit in lit_order])

    def mk_lit_alts(self, v: Id, ty: Ty, xs: list[tuple[Lit, MatchResult]]) -> MatchResult:
        def _go(eh: CoreTm) -> CoreTm:
            alts: list[tuple[Alt, CoreTm]] = []
            alts.extend((LitAlt(lit), mr_run(mr, eh)) for lit, mr in xs)
            alts.append((DefaultAlt(), eh))
            return C.case_expr(
                C.var(v),
                self.name_gen.new_id(lambda i: f"_mc_litalts_s_{i}", v.ty),
                ty,
                alts
            )
        return self.with_shared_error_handler(ty, MRFallible(_go))

    def mc_con(self, v: Id, vs: list[Id], ty: Ty, col: list[XPat], eqns: list[Equation]) -> MatchResult:
        def _by_con(t: tuple[XPat, Equation]) -> Name:
            match t:
                case (XPatCon(con, _), _):
                    return con
                case _: raise Exception("unreachable")

        # FIX: we must not use groupby (local grouping) here
        groups: dict[Name, list[tuple[XPat, Equation]]] = defaultdict(list)
        con_order: list[Name] = []
        for t in zip(col, eqns):
            con = _by_con(t)
            if con not in groups:
                con_order.append(con)
            groups[con].append(t)

        def _go_grp(con: Name, pat_eqns: list[tuple[XPat, Equation]]) -> tuple[Name, list[Id], MatchResult]:
            _, eqns = unzip(pat_eqns)
            # the column must be of the same type
            # so just take the first one's arg_tys
            arg_tys = cast(XPatCon, pat_eqns[0][0]).arg_tys
            ids = [self.name_gen.new_id(lambda i: f"_mc_con_{i}", ty) for ty in arg_tys]
            return (con, ids, self.matchc(ids + vs, ty, unshift_eqn([cast(XPatCon, p).args for p, _ in pat_eqns], eqns)))

        return self.mk_con_alts(v, ty, [_go_grp(con, list(groups[con])) for con in con_order])

    def mk_con_alts(self, v: Id, ty: Ty, xs: list[tuple[Name, list[Id], MatchResult]]) -> MatchResult:
        def _mk_alt1(con: Name, ids: list[Id], mr: MatchResult) -> MatchResult1[tuple[Name, list[Id], CoreTm]]:
            match mr:
                case MRInfallible(core):
                    return MRInfallible((con, ids, core))
                case MRFallible(wh):
                    return MRFallible(lambda eh: (con, ids, wh(eh)))
        mr_alts = mr_bundle([_mk_alt1(con, ids, mr) for con, ids, mr in xs])

        tycon = cast(TyConApp, v.ty).name
        cons = self.tycon_datacons(tycon)
        cons_map = {con.name: con for con in cons}
        all_cons = [c.name for c in cons]
        # just to decide if we need default alt
        unseen_cons = set(all_cons).difference([con for con, _, _ in xs])
        def _mk_defa() -> MatchResult1[None | CoreTm]:
            if unseen_cons:
                return MRFallible(lambda eh: eh)
            else:
                return MRInfallible(None)
        mr_default = _mk_defa()

        def _map_res(t: tuple[list[tuple[Name, list[Id], CoreTm]], None | CoreTm]) -> CoreTm:
            alts, defa = t
            alts_: list[tuple[Alt, CoreTm]] = []
            alts_.extend((DataAlt(con, cons_map[con].tag, ids), core) for con, ids, core in alts)
            if defa is not None:
                alts_.append((DefaultAlt(), defa))
            return C.case_expr(
                C.var(v),
                self.name_gen.new_id(lambda i: f"_mc_con_scrut_v_{i}", v.ty),
                ty,
                alts_
            )
        return mr_map(mr_bundle2(mr_alts, mr_default), _map_res)

    def with_shared_error_handler(self, ty: Ty, mr: MatchResult) -> MatchResult:
        match mr:
            case MRInfallible():
                return mr
            case MRFallible():
                def _go(eh: CoreTm) -> CoreTm:
                    w, eh2 = self.mk_unit_fun(ty, eh)
                    return w(mr.with_errorh(eh2))
                return MRFallible(_go)

    def mk_unit_fun(self, ty_body: Ty, body: CoreTm) -> tuple[DsWrapper, CoreTm]:
        ty_unit = TyConApp(BUILTIN_UNIT, [])
        ty = TyFun(ty_unit, ty_body)
        fun = C.lam(self.name_gen.new_id(lambda i: f"_mc_eh_unit_{i}", ty_unit), body)
        v_eh = self.name_gen.new_id(lambda i: f"_mc_eh_{i}", ty)
        unit = C.var(Id(BUILTIN_MK_UNIT, ty_unit))
        return (
            lambda c: C.let(v_eh, fun, c),
            C.app(C.var(v_eh), unit)
        )

    def tycon_datacons(self, tycon_name: Name) -> list[ACon]:
        tycon = self.ctx.lookup_tycon(tycon_name)
        return tycon.constructors


def mr_chain(resx: list[MatchResult]) -> MatchResult:
    def _merge2(left: MatchResult, right: MatchResult) -> MatchResult:
        match (left, right):
            case (MRInfallible(), _):
                return left
            case (MRFallible() as l, MRInfallible() as r):
                return _chain_mr_fi(l, r)
            case (MRFallible() as l, MRFallible() as r):
                return _chain_mr_ff(l, r)

    return functools.reduce(lambda r, l: _merge2(l, r), reversed(resx))


def _chain_mr_fi(left: MRFallible[CoreTm], right: MRInfallible[CoreTm]) -> MRInfallible[CoreTm]:
    return MRInfallible(left.with_errorh(right.core))


def _chain_mr_ff(left: MRFallible[CoreTm], right: MRFallible[CoreTm]) -> MRFallible[CoreTm]:
    return MRFallible(lambda eh: left.with_errorh(right.with_errorh(eh)))


def mr_map(mr: MatchResult1[T], c: Callable[[T], R]) -> MatchResult1[R]:
    match mr:
        case MRInfallible(ct):
            return MRInfallible(c(ct))
        case MRFallible():
            def _go(eh: CoreTm) -> R:
                inner = mr.with_errorh(eh)
                return c(inner)
            return MRFallible(_go)


def mr_run(mr: MatchResult1[T], error_handler: CoreTm) -> T:
    match mr:
        case MRInfallible(c):
            return c
        case MRFallible(wh):
            return wh(error_handler)


def mr_bundle(mrs: list[MatchResult1[T]]) -> MatchResult1[list[T]]:
    """
    Just not into the wonderlands of Applicative
    """
    if all(isinstance(x, MRInfallible) for x in mrs):
        return MRInfallible([cast(MRInfallible[T], x).core for x in mrs])
    else:
        return MRFallible(lambda eh: [mr_run(x, eh) for x in mrs])


def mr_bundle2(left: MatchResult1[T], right: MatchResult1[R]) -> MatchResult1[tuple[T, R]]:
    match (left, right):
        case (MRInfallible(l), MRInfallible(r)):
            return MRInfallible((l, r))
        case _:
            return MRFallible(lambda eh: (mr_run(left, eh), mr_run(right, eh)))


def shift_eqn(eqns: list[Equation]) -> tuple[list[XPat], list[Equation]]:
    col = [x for ([x, *_], _) in eqns]
    rest = [(xs, rhs) for ([_, *xs], rhs) in eqns]
    return (col, rest)


def unshift_eqn(pats: list[list[XPat]], eqns: list[Equation]) -> list[Equation]:
    return [(ps_ + ps, rhs) for (ps_, (ps, rhs)) in zip(pats, eqns)]


def wrap_rhs(eqn: Equation, dw: DsWrapper) -> Equation:
    ps, rhs = eqn
    return (ps, mr_map(rhs, dw))


def mk_bndr(bndr: Id, rhs: CoreTm) -> Callable[[CoreTm], CoreTm]:
    return lambda c: C.let(bndr, rhs, c)
