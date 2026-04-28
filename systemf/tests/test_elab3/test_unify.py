"""Unification tests ported from elab2.

Tests for TcCtx.unify() covering:
- Same type unification (no-op)
- Forall rejection
- Meta variable binding
- Structural unification (function types)
- Meta linking and resolution
- Bound meta unwrapping
- Occurrence check
- Skolem handling
"""

import pytest

from systemf.elab3.tc_ctx import Unifier
from systemf.elab3.types.ty import (
    BoundTv,
    MetaTv,
    Name,
    Ref,
    SkolemTv,
    Ty,
    TyConApp,
    TyForall,
    TyFun,
    TyInt,
    TyString,
    TyVar,
    zonk_type,
)
from systemf.utils.uniq import Uniq


class FakeUnifier(Unifier):
    def __init__(self) -> None:
        super().__init__("UnifyTest", Uniq(1000))

    def lookup_gbl(self, name: Name):
        raise KeyError(name)


def _ctx() -> FakeUnifier:
    return FakeUnifier()


INT = TyInt()
STRING = TyString()
BOOL = TyConApp(Name("Test", "Bool", 999), [])


# =============================================================================
# Forall rejection
# =============================================================================


def test_forall_lhs_rejected():
    a = BoundTv(name=Name("Test", "a", 1))
    forall_ty = TyForall([a], a)
    ctx = _ctx()
    with pytest.raises(Exception, match="Cannot unify|Unexpected"):
        ctx.unify(forall_ty, INT)


def test_forall_rhs_rejected():
    a = BoundTv(name=Name("Test", "a", 1))
    forall_ty = TyForall([a], a)
    ctx = _ctx()
    with pytest.raises(Exception, match="Cannot unify|Unexpected"):
        ctx.unify(INT, forall_ty)


# =============================================================================
# Same type unification (no-op)
# =============================================================================


def test_same_skolem_unifies():
    ctx = _ctx()
    sk = ctx.make_skolem(Name("Test", "s", 1))
    ctx.unify(sk, sk)


def test_same_meta_unifies():
    ctx = _ctx()
    m = ctx.make_meta()
    ctx.unify(m, m)
    assert m.ref.inner is None


def test_same_tycon_unifies():
    ctx = _ctx()
    ctx.unify(INT, INT)


# =============================================================================
# Different rigid types fail
# =============================================================================


def test_different_skolems_fail():
    ctx = _ctx()
    sk1 = ctx.make_skolem(Name("Test", "s1", 1))
    sk2 = ctx.make_skolem(Name("Test", "s2", 2))
    with pytest.raises(Exception, match="Cannot unify"):
        ctx.unify(sk1, sk2)


def test_different_tycons_fail():
    ctx = _ctx()
    with pytest.raises(Exception, match="Cannot unify"):
        ctx.unify(INT, STRING)


def test_skolem_vs_tycon_fail():
    ctx = _ctx()
    sk = ctx.make_skolem(Name("Test", "s", 1))
    with pytest.raises(Exception, match="Cannot unify"):
        ctx.unify(sk, INT)


# =============================================================================
# Meta variable binding
# =============================================================================


def test_meta_binds_to_int():
    ctx = _ctx()
    m = ctx.make_meta()
    ctx.unify(m, INT)
    assert zonk_type(m) == INT


def test_meta_binds_to_int_reverse():
    ctx = _ctx()
    m = ctx.make_meta()
    ctx.unify(INT, m)
    assert zonk_type(m) == INT


# =============================================================================
# Meta binds to function of metas
# =============================================================================


def test_meta_binds_to_fun_of_metas():
    ctx = _ctx()
    m1 = ctx.make_meta()
    m2 = ctx.make_meta()
    m3 = ctx.make_meta()
    fun_ty = TyFun(m2, m3)
    ctx.unify(m1, fun_ty)
    assert zonk_type(m1) == fun_ty


def test_meta_binds_to_fun_of_metas_reverse():
    ctx = _ctx()
    m1 = ctx.make_meta()
    m2 = ctx.make_meta()
    m3 = ctx.make_meta()
    fun_ty = TyFun(m2, m3)
    ctx.unify(fun_ty, m1)
    assert zonk_type(m1) == fun_ty


# =============================================================================
# Structural unification
# =============================================================================


def test_fun_of_metas_unifies_structurally():
    ctx = _ctx()
    m1 = ctx.make_meta()
    m2 = ctx.make_meta()
    ctx.unify(TyFun(m1, m2), TyFun(INT, INT))
    assert zonk_type(m1) == INT
    assert zonk_type(m2) == INT


def test_fun_of_metas_unifies_structurally_reverse():
    ctx = _ctx()
    m1 = ctx.make_meta()
    m2 = ctx.make_meta()
    ctx.unify(TyFun(INT, INT), TyFun(m1, m2))
    assert zonk_type(m1) == INT
    assert zonk_type(m2) == INT


# =============================================================================
# Meta linking
# =============================================================================


def test_two_unbound_metas_link():
    ctx = _ctx()
    m1 = ctx.make_meta()
    m2 = ctx.make_meta()
    ctx.unify(m1, m2)
    assert m1.ref.inner == m2 or zonk_type(m1) == zonk_type(m2)


def test_linked_metas_resolve_on_later_unify():
    ctx = _ctx()
    m1 = ctx.make_meta()
    m2 = ctx.make_meta()
    ctx.unify(m1, m2)
    ctx.unify(m2, INT)
    assert zonk_type(m1) == INT
    assert zonk_type(m2) == INT


# =============================================================================
# Bound meta unwrapping
# =============================================================================


def test_bound_meta_unwraps_lhs():
    ctx = _ctx()
    m = ctx.make_meta()
    m.ref.set(INT)
    ctx.unify(m, INT)


def test_bound_meta_unwraps_rhs():
    ctx = _ctx()
    m = ctx.make_meta()
    m.ref.set(INT)
    ctx.unify(INT, m)


def test_bound_meta_mismatch_fails():
    ctx = _ctx()
    m = ctx.make_meta()
    m.ref.set(INT)
    with pytest.raises(Exception, match="Cannot unify"):
        ctx.unify(m, STRING)


# =============================================================================
# Occurrence check
# =============================================================================


def test_occurrence_check():
    ctx = _ctx()
    m = ctx.make_meta()
    with pytest.raises(Exception, match="[Oo]ccurrence"):
        ctx.unify(m, TyFun(m, INT))


# =============================================================================
# TyConApp structural unification
# =============================================================================


def test_tyconapp_same_name_unifies_args():
    list_name = Name("Test", "List", 10)
    ctx = _ctx()
    m = ctx.make_meta()
    ctx.unify(TyConApp(list_name, [m]), TyConApp(list_name, [INT]))
    assert zonk_type(m) == INT


def test_tyconapp_different_names_fail():
    ctx = _ctx()
    with pytest.raises(Exception, match="Cannot unify"):
        ctx.unify(
            TyConApp(Name("Test", "List", 10), []),
            TyConApp(Name("Test", "Maybe", 11), []),
        )


def test_tyconapp_arity_mismatch_fails():
    ctx = _ctx()
    with pytest.raises(Exception, match="Cannot unify"):
        ctx.unify(
            TyConApp(Name("Test", "List", 10), [INT]),
            TyConApp(Name("Test", "List", 10), [INT, STRING]),
        )
