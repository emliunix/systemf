"""
AST types for the systemf elaborator (elab3).

Two layers:

1. **Parsed declarations** (Parsed* prefix, str names) - pre-renaming form
   produced by converting surface AST into elab3 declarations. Used for
   import processing and Name allocation.

2. **Renamed declarations** (no prefix, Name-based) - post-renaming form
   where global identifiers are resolved to Name via ReaderEnv.
   Types use the Ty hierarchy from elab3.types (not a separate RnType layer).
   Variables use Id (Name + Type), following GHC's Var/Id design.

Pipeline:
    surface/types.py -> (convert to Parsed) -> (rename str->Name(w/ Id)) -> typecheck -> core.py

Design notes:
    - No separate renamed type layer: Ty (from types.py) IS the type representation.
      TyConApp uses Name for the type constructor, TyVar/BoundTv stay str (local binders).
    - Term variables use Id (Name + Ty), like GHC's Id.
    - Lambda/let parameters are Ids (carry Name + type), not bare strings.

Styles:

- No = field(default_factory=...)
- No `| None` type
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass

from .ty import Lit, Name, Ty, TyVar
from .tything import Metas


# =============================================================================
# Renamed Term Expressions
# =============================================================================


@dataclass(frozen=True)
class AnnotName:
    name: Name
    type_ann: Ty


def name_of(n: Name | AnnotName) -> Name:
    match n:
        case Name():
            return n
        case AnnotName(name=name):
            return name


class Expr:
    """Base for renamed term expressions."""
    pass


@dataclass(frozen=True)
class Var(Expr):
    """Local variable reference (lambda param, let-bound)."""
    name: Name


@dataclass(frozen=True)
class Lam(Expr):
    """Lambda: \\a b (x::T) -> body.

    param is an Id (Name + type). Like GHC's CoreLam where the binder
    is a full Id, not just a name string.
    """
    args: list[Name | AnnotName]
    body: Expr


@dataclass(frozen=True)
class App(Expr):
    """Application: f arg."""
    func: Expr
    arg: Expr


@dataclass(frozen=True)
class Let(Expr):
    """
    let: let x = expr in body.
    """
    bindings: list[Binding]
    body: Expr


@dataclass(frozen=True)
class Binding:
    name: Name | AnnotName
    expr: Expr


@dataclass(frozen=True)
class Ann(Expr):
    """Type annotation: expr : type."""
    expr: Expr
    ty: Ty


@dataclass(frozen=True)
class LitExpr(Expr):
    """Literal value: 42, "hello"."""
    lit: Lit


@dataclass(frozen=True)
class Case(Expr):
    """Pattern match: case scrutinee of { branches }.

    scrutinee_type records the type being matched (needed for
    determining which constructors are valid).
    """
    scrutinee: Expr
    branches: list[CaseBranch]


# =============================================================================
# Patterns
# =============================================================================


class Pat:
    """The pattern lanuage."""
    pass


@dataclass(frozen=True)
class VarPat(Pat):
    """Variable pattern that binds an identifier: x."""
    name: Name | AnnotName


@dataclass(frozen=True)
class ConPat(Pat):
    """Constructor pattern: Con arg1 arg2 ...

    con is resolved via ReaderEnv. args are nested Pat nodes,
    allowing arbitrary nesting (e.g. Cons (Pair x y) zs).
    """
    con: Name
    args: list[Pat]


@dataclass(frozen=True)
class LitPat(Pat):
    """Literal pattern: 42, "hello"."""
    lit: Lit


@dataclass(frozen=True)
class WildcardPat(Pat):
    """Default/wildcard pattern: _"""
    pass


@dataclass(frozen=True)
class CaseBranch:
    """Case branch: pattern -> body."""
    pattern: Pat
    body: Expr


# =============================================================================
# Renamed Declarations
# =============================================================================


@dataclass
class RnDataConDecl:
    """Parsed data constructor (str names)."""
    name: Name
    tycon: RnDataDecl
    fields: list[Ty]
    metas: Metas | None


@dataclass
class RnDataDecl:
    """Parsed data type declaration (str names)."""
    name: Name
    tyvars: list[TyVar]
    constructors: list[RnDataConDecl]
    metas: Metas | None


@dataclass
class RnTermDecl:
    """Parsed term declaration (str names)."""
    name: Name | AnnotName
    expr: Expr
    metas: Metas | None


@dataclass
class RnPrimTyDecl:
    name: Name
    tyvars: list[TyVar]
    metas: Metas | None


@dataclass
class RnPrimOpDecl:
    name: AnnotName
    metas: Metas | None


# =============================================================================
# Import Declarations (always str - module names, not term/type names)
# =============================================================================

@dataclass
class ImportDecl:
    """Import declaration.

    items captures three cases:
    - None: import all exported names
    - ImportItems([...]): import only these names
    - HidingItems([...]): import all except these names
    """
    module: str
    qualified: bool = False
    alias: str | None = None
    import_items: list[str] | None = None
    hiding_items: list[str] | None = None


@dataclass
class ModuleDecls:
    """All declarations in a module (pre-renaming)."""
    data_decls: list[RnDataDecl]
    term_decls: list[RnTermDecl]
    prim_ty_decls: list[RnPrimTyDecl]
    prim_op_decls: list[RnPrimOpDecl]


def expr_names(expr: Expr) -> Generator[Name, None, None]:
    match expr:
        case Var(name):
            yield name
        case Lam(_, body):
            yield from expr_names(body)
        case App(func, arg):
            yield from expr_names(func)
            yield from expr_names(arg)
        case Let(bindings, body):
            for b in bindings:
                yield from expr_names(b.expr)
            yield from expr_names(body)
        case Ann(expr, _):
            yield from expr_names(expr)  # ignore types for name collection
        case LitExpr(_):
            pass
        case Case(scrutinee, branches):
            yield from expr_names(scrutinee)
            for b in branches:
                yield from expr_names(b.body)
        case _:
            raise Exception(f"unexpected expr: {expr}")
