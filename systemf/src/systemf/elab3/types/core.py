"""
Core language AST for systemf elaborator (elab3).

Self-contained — imports only from elab3.types.
Core terms use Id (Name + Type) for all variable references.
"""

from abc import ABC
from dataclasses import dataclass
from typing import Any, cast

from .ty import Id, Lit, Name, Ty, TyVar, zonk_type


# =============================================================================
# Core Terms
# =============================================================================

pp_core: Any = None


class CoreTm(ABC):
    """Base class for core language terms."""

    def __repr__(self) -> str:
        global pp_core
        if pp_core is None:
            from .core_pp import pp_core as pp
            pp_core = pp
        return pp_core(self)


@dataclass(repr=False)
class CoreLit(CoreTm):
    """Literal value."""
    value: Lit


@dataclass(repr=False)
class CoreVar(CoreTm):
    """Local variable reference (lambda param, let-bound)."""
    id: Id


@dataclass(repr=False)
class CoreGlobalVar(CoreTm):
    """Top-level / module-level variable reference.

    Unlike CoreVar (local), a global var is defined at module scope and
    resolved via the module's type/value environment. Not substituted by
    local let/lambda binders.
    """
    id: Id


@dataclass(repr=False)
class CoreLam(CoreTm):
    """Lambda abstraction."""
    param: Id
    body: CoreTm


@dataclass(repr=False)
class CoreApp(CoreTm):
    """Function application."""
    fun: CoreTm
    arg: CoreTm


@dataclass(repr=False)
class CoreTyLam(CoreTm):
    """Type abstraction (polymorphic lambda)."""
    var: TyVar
    body: CoreTm


@dataclass(repr=False)
class CoreTyApp(CoreTm):
    """Type application (explicit instantiation)."""
    fun: CoreTm
    tyarg: Ty


# =============================================================================
# Bindings
# =============================================================================


type Binding = Rec | NonRec


@dataclass(repr=False)
class NonRec:
    """Non-recursive binding: let x = expr in body"""
    binder: Id
    expr: CoreTm


@dataclass(repr=False)
class Rec:
    """Recursive bindings: letrec { x = e1; y = e2 } in body

    All names are in scope for all expressions (mutual recursion).
    """
    bindings: list[tuple[Id, CoreTm]]


@dataclass(repr=False)
class CoreLet(CoreTm):
    """Let binding with NonRec or Rec."""
    binding: Binding
    body: CoreTm


def binding_names(binding: Binding) -> list[Name]:
    match binding:
        case NonRec(bndr, _):
            return [bndr.name]
        case Rec(bx):
            return [
                b.name
                for b, _ in bx
            ]


# =============================================================================
# patterns
# =============================================================================


@dataclass(repr=False)
class CoreCase(CoreTm):
    scrut: CoreTm
    var: Id
    res_ty: Ty
    alts: list[tuple[Alt, CoreTm]]


@dataclass(repr=False)
class DataAlt:
    con: Name
    tag: int
    vars: list[Id]


@dataclass(repr=False)
class LitAlt:
    lit: Lit


@dataclass(repr=False)
class DefaultAlt:
    pass


type Alt = DataAlt | LitAlt | DefaultAlt


# =============================================================================
# Core Term Builder
# =============================================================================


class CoreBuilder:
    """Builder for constructing core terms."""

    def lit(self, value: Lit) -> CoreTm:
        return CoreLit(value)

    def var(self, id: Id) -> CoreTm:
        return CoreVar(Id(id.name, zonk_type(id.ty)))

    def lam(self, param: Id, body: CoreTm) -> CoreTm:
        return CoreLam(Id(param.name, zonk_type(param.ty)), body)

    def app(self, fun: CoreTm, arg: CoreTm) -> CoreTm:
        return CoreApp(fun, arg)

    def tylam(self, var: TyVar, body: CoreTm) -> CoreTm:
        return CoreTyLam(var, body)

    def tyapp(self, fun: CoreTm, tyarg: Ty) -> CoreTm:
        return CoreTyApp(fun, zonk_type(tyarg))

    def let(self, binder: Id, expr: CoreTm, body: CoreTm) -> CoreTm:
        return CoreLet(NonRec(binder, expr), body)

    def letrec(self, bindings: list[tuple[Id, CoreTm]], body: CoreTm) -> CoreTm:
        return CoreLet(Rec(bindings), body)

    def case_expr(self, scrut: CoreTm, v: Id, res_ty: Ty,
                  alts: list[tuple[Alt, CoreTm]]) -> CoreTm:
        return CoreCase(scrut, v, res_ty, alts)

    def subst(self, substs: dict[Id, CoreTm], expr: CoreTm) -> CoreTm:
        return subst_coretm(substs, expr)


def subst_coretm(substs: dict[Id, CoreTm], expr: CoreTm) -> CoreTm:
    """Substitute variable named `target` with `replacement` in `expr`."""
    match expr:
        case CoreVar(id) if id in substs:
            return substs[id]
        case CoreTyApp(fun, ty_arg):
            return CoreTyApp(subst_coretm(substs, fun), ty_arg)
        case CoreTyLam(var, body):
            return CoreTyLam(var, subst_coretm(substs, body))
        case CoreLam(param, body):
            substs_ = shift_substs(substs, [param])
            if len(substs_) > 0:
                return CoreLam(param, subst_coretm(substs_, body))
            else:
                return expr
        case CoreApp(fun, arg):
            return CoreApp(
                subst_coretm(substs, fun),
                subst_coretm(substs, arg),
            )
        case CoreLet(NonRec(binder, expr), body):
            expr_ = subst_coretm(substs, expr)
            substs_ = shift_substs(substs, [binder])
            if len(substs_) > 0:
                return CoreLet(NonRec(binder, expr_), subst_coretm(substs_, body))
            else:
                return CoreLet(NonRec(binder, expr_), body)
        case CoreLet(Rec(bindings), body):
            substs_ = shift_substs(substs, [b for b, _ in bindings])
            if len(substs_) > 0:
                bindings_ = [(b, subst_coretm(substs, e)) for b, e in bindings]
                body_ = subst_coretm(substs, body)
                return CoreLet(Rec(bindings_), body_)
            else:
                return expr
        case CoreCase(scrut, var, res_ty, alts):
            return CoreCase(
                subst_coretm(substs, scrut),
                var,
                res_ty,
                [(alt, _subst_alt(substs, var, alt, tm)) for alt, tm in alts]
            )
        case CoreLit() | CoreTm():
            return expr


def _subst_alt(substs: dict[Id, CoreTm], scrut_var: Id, alt: Alt, tm: CoreTm) -> CoreTm:
    """
    Substitute Alt RHS, handling scrut_var and alt vars
    """
    substs1 = shift_substs(substs, [scrut_var])
    match alt:
        case DataAlt(vars=vars):
            substs2 = shift_substs(substs1, vars)
            if len(substs2) > 0:
                return subst_coretm(substs2, tm)
            else:
                return tm
        case LitAlt() | DefaultAlt():
            return subst_coretm(substs1, tm)


def shift_substs(substs: dict[Id, CoreTm], ids: list[Id]) -> dict[Id, CoreTm]:
    id_set = set(ids)
    return {k: v for k, v in substs.items() if k not in id_set}


C = CoreBuilder()
