import itertools

from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from functools import reduce
from typing import Protocol, cast

from systemf.elab3 import name_gen

from .builtins import BUILTIN_FALSE, BUILTIN_BIN_OPS, BUILTIN_LIST, BUILTIN_LIST_CONS, BUILTIN_LIST_NIL, BUILTIN_MK_UNIT, BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR, BUILTIN_TRUE, BUILTIN_UNIT

from .reader_env import ImportRdrElt, ImportSpec, LocalRdrElt, QualName, RdrElt, RdrName, ReaderEnv, UnqualName
from .types import Module, NameGenerator
from .types.ty import Lit, LitInt, LitString, Name, Ty, TyConApp, TyForall, TyFun, TyInt, TyString, TyVar, BoundTv
from .types.tything import ACon, TyThing
from .types.ast import (
    Ann, AnnotName, App, Binding, Case, CaseBranch, ConPat, Expr, ImportDecl,
    Lam, Let, LitExpr, LitPat, Pat, RnDataDecl, RnTermDecl, Var, VarPat, WildcardPat
)

from systemf.surface.types import (
    SurfaceAbs, SurfaceAnn, SurfaceApp, SurfaceBranch, SurfaceCase,
    SurfaceDataDeclaration, SurfaceDeclaration, SurfaceDeclarationRepr,
    SurfaceIf, SurfaceLet, SurfaceList, SurfaceListPattern, SurfaceListType,SurfaceLit, SurfaceLitPattern, SurfaceOp, SurfacePattern,
    SurfacePatternBase, SurfacePatternCons, SurfacePatternSeq, SurfacePatternTuple, SurfaceTerm, SurfaceUnit, SurfaceUnitPattern, SurfaceUnitType,
    SurfaceWildcardPattern,
    SurfaceTermDeclaration, SurfaceTuple, SurfaceType, SurfaceTypeArrow,
    SurfaceTypeConstructor, SurfaceTypeForall, SurfaceTypeTuple, SurfaceTypeVar,
    SurfaceVar, SurfaceVarPattern, ValBind
)

from systemf.utils import capture_return
from systemf.utils.location import Location


class RenameExpr:
    reader_env: ReaderEnv
    local_env: list[tuple[str, Name]]
    mod_name: str
    name_gen: NameGenerator

    def __init__(self, reader_env: ReaderEnv, mod_name: str, name_gen: NameGenerator):
        self.reader_env = reader_env
        self.mod_name = mod_name
        self.name_gen = name_gen
        self.local_env = []

    def new_name(self, name: str, loc: Location | None) -> Name:
        return self.name_gen.new_name(name, loc)

    def new_names(self, names: list[str], loc: Location | None) -> list[Name]:
        name_gen.check_dups(names, loc)
        return [self.new_name(name, loc) for name in names]

    def lookup(self, name: RdrName, loc: Location | None = None) -> Name:
        match self.lookup_maybe(name):
            case [] | None:
                raise Exception(f"unresolved variable: {name} at {loc}")
            case [n]:
                return n
            case xs:
                raise Exception(f"ambiguous name: {name} (candidates: {xs}) at {loc}")

    def lookup_maybe(self, name: RdrName) -> list[Name] | None:
        match name:
            case UnqualName(name_) if (n := self.lookup_local_name(name_)) is not None:
                return [n]
            case _:
                return self.lookup_gbl_name(name)

    def lookup_local_name(self, name: str) -> Name | None:
        for (occ, n) in reversed(self.local_env):
            if occ == name:
                return n
        return None

    def lookup_gbl_name(self, name: RdrName) -> list[Name]:
        return [n.name for n in self.reader_env.lookup(name)]

    @contextmanager
    def extend_local(self, names: list[Name]) -> Generator[None, None, None]:
        self.local_env.extend((name.surface, name) for name in names)
        yield
        for _ in range(len(names)):
            _ = self.local_env.pop()

    def rename_expr(self, ast: SurfaceTerm) -> Expr:
        match ast:
            case SurfaceVar(name=name, location=loc):
                return Var(self.lookup(UnqualName(name), loc))

            case SurfaceLit(prim_type=prim_type, value=value):
                return LitExpr(prim_to_lit(prim_type, value))

            case SurfaceAbs(params=params, body=body, location=loc):
                names = self.new_names([
                    param
                    for (param, _) in params
                ], loc)
                params_ = [
                    (AnnotName(name, self.rename_type(ty))) if ty else name
                    for ((_, ty), name) in zip(params, names)
                ]
                with self.extend_local(names):
                    body_ = self.rename_expr(body)
                return Lam(params_, body_)

            case SurfaceApp(func=func, arg=arg):
                return App(self.rename_expr(func), self.rename_expr(arg))

            case SurfaceLet(bindings=bindings, body=body):
                name_ty_locs = binding_names(bindings)
                names = [self.new_name(n, loc) for (n, _, loc) in name_ty_locs]
                anno_names = [
                    AnnotName(n, self.rename_type(ty)) if ty else n
                    for (n, (_, ty, _)) in zip (names, name_ty_locs)]

                with self.extend_local(names):
                    binding_rhss = [
                        self.rename_expr(b.value)
                        for b in bindings]
                    body_ = self.rename_expr(body)
                bindings_ = [
                    Binding(n, b)
                    for (n, b) in zip(anno_names, binding_rhss)]
                return Let(bindings_, body_)

            case SurfaceAnn(term=term, type=type_):
                return Ann(self.rename_expr(term), self.rename_type(type_))

            case SurfaceIf(cond=cond, then_branch=then_b, else_branch=else_b):
                return Case(self.rename_expr(cond), [
                    CaseBranch(ConPat(BUILTIN_TRUE, []), self.rename_expr(then_b)),
                    CaseBranch(ConPat(BUILTIN_FALSE, []), self.rename_expr(else_b)),
                ])

            case SurfaceOp(left=left, op=op, right=right):
                if (op_f := BUILTIN_BIN_OPS.get(op)) is None:
                    raise Exception(f"unknown operator: {op}")
                return App(App(Var(op_f), self.rename_expr(left)), self.rename_expr(right))

            case SurfaceTuple(elements=elements):
                return reduce(lambda acc, curr: App(App(Var(BUILTIN_PAIR_MKPAIR), curr), acc), reversed([
                    self.rename_expr(e) for e in elements
                ]))

            case SurfaceCase(scrutinee=scrutinee, branches=branches):
                # Case: case x of Pat -> body
                return Case(self.rename_expr(scrutinee), [
                    self.rename_case_branch(b) for b in branches
                ])

            case SurfaceList(elements=elements):
                return reduce(lambda acc, curr: App(App(Var(BUILTIN_LIST_CONS), curr), acc), reversed([
                    self.rename_expr(e) for e in elements
                ]), Var(BUILTIN_LIST_NIL))

            case SurfaceUnit():
                return Var(BUILTIN_MK_UNIT)

            case _:
                raise Exception(f"unknown expr: {ast}")

    def rename_case_branch(self, branch: SurfaceBranch) -> CaseBranch:
        names, pat = self.rename_pattern(branch.pattern)
        with self.extend_local(names):
            body = self.rename_expr(branch.body)
        return CaseBranch(pat, body)

    def rename_pattern(self, pat: SurfacePatternBase) -> tuple[list[Name], Pat]:
        """
        Desugar and rename to ast.Pat
        """

        def _con_pat(con: Name, pats: list[SurfacePatternBase]) -> Generator[Name, None, Pat]:
            res: list[Pat] = []
            for pat in pats:
                pat_ = yield from _rename_pat(pat)
                res.append(pat_)
            return ConPat(con, res)

        def _rename_pat_tuple(els: list[SurfacePatternBase]) -> Generator[Name, None, Pat]:
            match els:
                case [e1, e2]:
                    pat1 = yield from _rename_pat(e1)
                    pat2 = yield from _rename_pat(e2)
                    return ConPat(BUILTIN_PAIR_MKPAIR, [pat1, pat2])
                case [e, *es]:
                    pat1 = yield from _rename_pat(e)
                    pat2 = yield from _rename_pat_tuple(es)
                    return ConPat(BUILTIN_PAIR_MKPAIR, [pat1, pat2])
                case _:
                    raise Exception(f"invalid tuple pattern: {els}")

        def _rename_pat(pat: SurfacePatternBase) -> Generator[Name, None, Pat]:
            # TODO: check surface multi pattern support, though current language doesn't support it yet 
            match pat:
                case SurfaceVarPattern(name=var, location=loc):
                    match self.lookup_maybe(UnqualName(var)):
                        case [] | None:
                            name = self.new_name(var, loc)
                            yield name
                            return VarPat(name)
                        case [name]:
                            # NOTE: it's hacky, but works, if the name is defined, it suggests it's likely a data constructor, 
                            # hence a no-arg constructor pattern
                            return ConPat(name, [])
                        case xs:
                            raise Exception(f"multiple definition found for {var} at {loc}: {xs}")
                case SurfacePatternSeq(patterns=[SurfaceVarPattern(name=con), *pats]):
                    r = yield from _con_pat(self.lookup(UnqualName(con)), pats)
                    return r
                case SurfacePatternCons(head=x, tail=xs):
                    r = yield from _con_pat(BUILTIN_LIST_CONS, [x, xs])
                    return r
                case SurfacePatternTuple(elements=els):
                    r = yield from _rename_pat_tuple(els)
                    return r
                case SurfaceLitPattern(prim_type=prim_ty, value=val):
                    return LitPat(prim_to_lit(prim_ty, val))
                case SurfaceWildcardPattern():
                    return WildcardPat()
                case SurfaceUnitPattern():
                    return ConPat(BUILTIN_MK_UNIT, [])
                case SurfaceListPattern(elements=elements):
                    el_pats = []
                    for el in elements:
                        pel = yield from _rename_pat(el)
                        el_pats.append(pel)
                    return reduce(lambda acc, curr: ConPat(BUILTIN_LIST_CONS, [curr, acc]), reversed(el_pats), ConPat(BUILTIN_LIST_NIL, []))
                case _:
                    raise Exception(f"unknown pattern: {pat}")

        with capture_return(_rename_pat(pat)) as (gen_vars, res):
            vars = list(gen_vars)
            name_gen.check_dups([v.surface for v in vars], pat.location)
            names = [v for v in vars]
            return names, res[0]

    def rename_type(self, ty: SurfaceType) -> Ty:
        match ty:
            case SurfaceTypeVar(name=name, location=loc):
                return BoundTv(self.lookup(UnqualName(name)))
            case SurfaceTypeArrow(arg=arg, ret=ret):
                return TyFun(
                    self.rename_type(arg),
                    self.rename_type(ret),
                )
            case SurfaceTypeForall(vars=vars, body=body, location=loc):
                names = [self.new_name(v, loc) for v in vars]
                body_ = self.rename_forall_type(names, body)
                return TyForall([BoundTv(n) for n in names], body_)
            case SurfaceTypeConstructor(name=name, args=args):
                match name:
                    case "Int":
                        return TyInt()
                    case "String":
                        return TyString()
                    case _:
                        pass
                tycon = self.lookup(UnqualName(name))
                args = [self.rename_type(a) for a in args]
                return TyConApp(tycon, args)
            case SurfaceTypeTuple(elements=elements):
                return reduce(lambda acc, curr: TyConApp(BUILTIN_PAIR, [curr, acc]), reversed([
                    self.rename_type(e) for e in elements
                ]))
            case SurfaceUnitType():
                return TyConApp(BUILTIN_UNIT, [])
            case SurfaceListType(element=elem_ty):
                return TyConApp(BUILTIN_LIST, [self.rename_type(elem_ty)])
            case _:
                raise Exception(f"unknown type: {ty}")

    def rename_forall_type(self, names: list[Name], ty: SurfaceType) -> Ty:
        """
        Rename forall bounded types, so make it standalone to support data declarations.
        """
        with self.extend_local(names):
            return self.rename_type(ty)


def binding_names(bindings: Iterable[ValBind]) -> list[tuple[str, SurfaceType | None, Location | None]]:
    return [(b.name, b.type_ann, b.location) for b in bindings]


def prim_to_lit(prim_type: str, value: object) -> Lit:
    match prim_type.lower():
        case "string":
            return LitString(cast(str, value))
        case "int":
            return LitInt(cast(int, value))
        case _:
            raise Exception(f"unknown literal type: {prim_type}")
