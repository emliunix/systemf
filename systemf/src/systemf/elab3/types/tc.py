from dataclasses import dataclass
from typing import Callable

from .ty import Ref, Ty, Id, TyVar
from .wrapper import Wrapper
from .core import CoreTm


@dataclass
class Infer:
    lvl: int
    ref: Ref[Ty]

    def set(self, ty: Ty):
        self.ref.set(ty)


@dataclass
class Check:
    ty: Ty


type Expect = Infer | Check

type TyCk[T] = Callable[[], T]
type TyCkRes = TyCk[CoreTm]


# =============================================================================
# AbsBinds — Typechecker output for generalized binding groups
# =============================================================================

@dataclass
class ABExport:
    """Maps external poly name to internal mono name.

    Analogous to GHC's ABExport. The wrapper handles impedance matching
    when the group-generalized type differs from the individual poly type.
    """
    poly_id: Id      # Exported polymorphic id
    mono_id: Id      # Internal monomorphic id
    wrap: Wrapper    # Poly -> mono conversion (usually identity)


@dataclass
class AbsBinds:
    """Typechecker output for a generalized binding group.

    Analogous to GHC's AbsBinds. Faithfully records:
    - tvs: quantified type variables (from joint generalization)
    - exports: poly/mono pairs for each exported binding
    - binds: the monomorphic bindings (RHS thunks)

    Core generation (ds_abs_binds) reads this and produces Core.
    """
    tvs: list[TyVar]
    exports: list[ABExport]
    binds: list[tuple[Id, TyCkRes]]


# =============================================================================
# BindingGroup — Discriminated union for recursive vs non-recursive
# =============================================================================

type BindingGroup = NonRecGroup | RecGroup


@dataclass
class NonRecGroup:
    """Non-recursive bindings processed independently."""
    bndr: Id
    rhs: TyCkRes


@dataclass
class RecGroup:
    """Recursive binding group with joint generalization."""
    abs_binds: AbsBinds
