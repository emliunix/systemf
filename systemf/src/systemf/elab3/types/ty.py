"""
Core types for the systemf elaborator (elab3).

Self-contained — no imports from elab2 or core packages.

Design:
- Name: globally unique identifier (from NameCache)
- Id: Name + Type (like GHC's Id), used in Core
- Ty: type hierarchy with TyConApp using Name
- Lit: runtime literal values
"""
from __future__ import annotations

from abc import ABC
from collections.abc import Generator
from dataclasses import dataclass, field
import json
from typing import Any, Generic, TypeVar, override

from systemf.utils.location import Location

T = TypeVar("T")


# =============================================================================
# Mutable reference (for MetaTv unification)
# =============================================================================


@dataclass
class Ref(Generic[T]):
    """Mutable reference cell."""
    inner: T | None = field(default=None)

    def set(self, value: T) -> None:
        self.inner = value

    def get(self) -> T | None:
        return self.inner


# =============================================================================
# Name
# =============================================================================


@dataclass(frozen=True)
class Name:
    """Globally unique identifier. Uses unique field for O(1) equality.

    Like GHC's Name: human-readable surface form + globally unique ID +
    defining module provenance.
    """
    mod: str
    surface: str
    unique: int
    loc: Location | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Name):
            return NotImplemented
        return self.unique == other.unique

    def __hash__(self) -> int:
        return hash(self.unique)


# =============================================================================
# Id (Name + Type)
# =============================================================================


@dataclass(frozen=True)
class Id:
    """Term-level variable: Name + Type.

    Like GHC's Id (Var with Id constructor). Used in renamed and core terms
    wherever a variable reference carries both identity and type information.
    """
    name: Name
    ty: Ty


# =============================================================================
# Type hierarchy
# =============================================================================


@dataclass(frozen=True, repr=False)
class Ty:
    """Base for all types."""
    @override
    def __repr__(self) -> str:
        return _ty_repr(self, 0)


@dataclass(frozen=True, repr=False)
class TyLit(Ty):
    pass


@dataclass(frozen=True, repr=False)
class TyInt(TyLit):
    pass


@dataclass(frozen=True, repr=False)
class TyString(TyLit):
    pass


@dataclass(frozen=True, repr=False)
class TyPrim(Ty):
    name: str


@dataclass(frozen=True, repr=False)
class TyVar(Ty):
    """Base for type variables."""
    pass


def varnames(vars: list[TyVar]) -> list[Name]:
    def _name(v: TyVar) -> Name:
        match v:
            case BoundTv(name=name) | SkolemTv(name=name):
                return name
            case _:
                raise TypeError(f"Expected a bound type variable, got {v}")

    return [_name(v) for v in vars]


@dataclass(frozen=True, repr=False)
class BoundTv(TyVar):
    """Bound type variable (local binder in forall/tylam).

    Like GHC's TyVar with Internal NameSort. Stays as str — bound type vars
    don't need global identity.
    """
    name: Name


@dataclass(frozen=True, repr=False)
class SkolemTv(TyVar):
    """Skolem type variable (from type signature instantiation).

    Like GHC's TyVar with skolem details — rigid type variable introduced
    during polymorphic type checking.
    """
    name: Name
    uniq: int
    level: int


@dataclass(frozen=True, repr=False)
class MetaTv(Ty):
    """Meta type variable (unification variable).

    Like GHC's TcTyVar — exists only during type inference, gets solved
    (zonked) away before entering core terms.
    """
    uniq: int
    level: int
    ref: Ref[Ty]


@dataclass(frozen=True, repr=False)
class TyConApp(Ty):
    """Type constructor application: T arg1 arg2 ...

    Like GHC's TyConApp constructor of Type. The head is a Name (resolved
    type constructor), args are a flat list of types.

    Invariant (from GHC): the arg list may be undersaturated but never
    oversaturated.
    """
    name: Name
    args: list[Ty]


@dataclass(frozen=True, repr=False)
class TyFun(Ty):
    """Function type: arg -> result."""
    arg: Ty
    result: Ty


@dataclass(frozen=True, repr=False)
class TyForall(Ty):
    """Universally quantified type: forall a b. body."""
    vars: list[TyVar]
    body: Ty


# =============================================================================
# Runtime literals
# =============================================================================


class Lit(ABC):
    """Base for runtime literal values."""

    @property
    def ty(self) -> Ty: ...

    @property
    def v(self) -> Any: ...


@dataclass(frozen=True)
class LitInt(Lit):
    """Integer literal."""
    value: int

    @property
    @override
    def ty(self) -> Ty:
        return TyInt()

    @property
    @override
    def v(self) -> Any:
        return self.value

    @override
    def __repr__(self) -> str:
        return self.value.__repr__()


@dataclass(frozen=True)
class LitString(Lit):
    """String literal."""
    value: str

    @property
    @override
    def ty(self) -> Ty:
        return TyString()

    @property
    @override
    def v(self) -> Any:
        return self.value

    @override
    def __repr__(self) -> str:
        return json.dumps(self.value)


# =============================================================================
# Type utilities
# =============================================================================


def zonk_type(ty: Ty) -> Ty:
    """Resolve all meta variables to their solutions."""
    match ty:
        case TyVar() | TyLit() | TyPrim():
            return ty
        case TyConApp(name, args):
            return TyConApp(name, [zonk_type(a) for a in args])
        case TyFun():
            return TyFun(zonk_type(ty.arg), zonk_type(ty.result))
        case TyForall():
            return TyForall(ty.vars, zonk_type(ty.body))
        case MetaTv(ref=ref) if ref is not None and ref.inner is not None:
            solved = zonk_type(ref.inner)
            ref.set(solved)
            return solved
        case MetaTv():
            return ty
        case _:
            raise ValueError(f"Unknown type: {ty}")

def get_free_vars(tys: list[Ty]) -> list[TyVar]:
    def _free_tv(ty: Ty) -> Generator[TyVar, None, None]:
        match ty:
            case TyVar():  # BoundTv | Skolem
                yield ty
            case TyFun(arg, res):
                yield from _free_tv(arg)
                yield from _free_tv(res)
            case TyForall(vars, body):
                for var in _free_tv(body):
                    if var not in vars:  # ignore bound variables
                        yield var
            case TyConApp(args=args):
                for a in args:
                    yield from _free_tv(a)
            case MetaTv():
                pass
            case _:
                pass

    return [v for ty in tys for v in _free_tv(zonk_type(ty))]


def get_meta_vars(tys: list[Ty]) -> list[MetaTv]:
    def _meta_tv(ty: Ty) -> Generator[MetaTv, None, None]:
        match ty:
            # after zonking, only unsolved meta vars remain, so we can just check for MetaTv
            case MetaTv() as m:
                yield m
            case TyFun(arg, res):
                yield from _meta_tv(arg)
                yield from _meta_tv(res)
            case TyForall(_, body):
                yield from _meta_tv(body)
            case _:
                pass

    seen: set[int] = set()  # for deduplication
    result: list[MetaTv] = []
    for ty in tys:
        # zonk to make sure substitutions applied
        for v in _meta_tv(zonk_type(ty)):
            if v.uniq not in seen:
                seen.add(v.uniq)
                result.append(v)
    return result


def subst_ty(vars: list[TyVar], tys: list[Ty], ty: Ty) -> Ty:
    def _subst(env: dict[TyVar, Ty], ty: Ty) -> Ty:
        match ty:
            case TyVar():
                return env.get(ty, ty)
            case TyFun(arg, res):
                return TyFun(_subst(env, arg), _subst(env, res))
            case TyForall(vars_, body):
                env_ = {n: t for n, t in env.items() if n not in vars_}
                return TyForall(vars_, _subst(env_, body))
            case TyConApp(name, args):
                return TyConApp(name, [_subst(env, a) for a in args])
            case _:
                return ty

    return _subst({n: t for n, t in zip(vars, tys)}, ty)


def _ty_repr(ty: Ty, prec: int) -> str:
    def _show() -> tuple[int, str]:
        match ty:
            case TyInt():
                return 3, "Int"
            case TyString():
                return 3, "String"
            case TyPrim(name=name):
                return 3, name
            case BoundTv(name=name):
                return 3, name.surface
            case SkolemTv(name=name):
                return 3, f"${name.surface}"
            case TyConApp(name=name, args=[] | None):
                    return 3, name.surface
            case TyConApp(name=name, args=args):
                args_str = " ".join(_ty_repr(a, 2) for a in args)
                return 2, f"{name.surface} {args_str}"
            case TyFun(arg=arg, result=res):
                return 1, f"{_ty_repr(arg, 2)} -> {_ty_repr(res, 1)}"
            case TyForall(vars=vars, body=body):
                var_strs = " ".join(_ty_repr(v, 0) for v in vars)
                return 0, f"forall {var_strs}. {_ty_repr(body, 0)}"
            case MetaTv(uniq=uniq):
                return 1, f"?{uniq}"
            case _:
                raise TypeError(f"Unexpected type in repr: {type(ty)}")

    p, s = _show()
    if p < prec:
        return f"({s})"
    return s
