import pytest

from systemf.elab2.unify import unify
from systemf.elab2.types import *

# ---
# forall rejected

def test_forall_lhs_rejected():
    """forall on either side is unexpected during unification"""
    ty = TY.forall([TY.bound_var("a")], TY.bound_var("a"))
    with pytest.raises(TyCkException, match="Cannot unify"):
        unify(ty, INT)

def test_forall_rhs_rejected():
    ty = TY.forall([TY.bound_var("a")], TY.bound_var("a"))
    with pytest.raises(TyCkException, match="Cannot unify"):
        unify(INT, ty)

# ---
# same pair does nothing

def test_same_skolem_unifies():
    """identical skolem pair is a no-op"""
    sk = TY.skolem("s", 1)
    unify(sk, sk)  # should not raise

def test_same_meta_unifies():
    """identical meta pair is a no-op (same object)"""
    m = TY.meta(1)
    unify(m, m)
    assert m.ref.get() is None  # still unbound

def test_same_tycon_unifies():
    """identical type constructors unify"""
    unify(INT, INT)  # should not raise

# ---
# different skolem / tyvar fails

def test_different_skolems_fail():
    """two distinct skolems cannot unify"""
    sk1 = TY.skolem("s", 1)
    sk2 = TY.skolem("s", 2)
    with pytest.raises(TyCkException, match="Cannot unify"):
        unify(sk1, sk2)

def test_different_tycons_fail():
    """two distinct type constructors cannot unify"""
    with pytest.raises(TyCkException, match="Cannot unify"):
        unify(TyCon("Int"), TyCon("Bool"))

def test_skolem_vs_tycon_fail():
    """skolem and tycon cannot unify"""
    sk = TY.skolem("s", 1)
    with pytest.raises(TyCkException, match="Cannot unify"):
        unify(sk, INT)

# ---
# unify(m, int) gives int

def test_meta_binds_to_int():
    """unify(m, Int) binds m to Int"""
    m = TY.meta(1)
    unify(m, INT)
    assert m.ref.get() == INT

def test_meta_binds_to_int_reverse():
    """unify(Int, m) binds m to Int"""
    m = TY.meta(1)
    unify(INT, m)
    assert m.ref.get() == INT

# ---
# unify(m1, m2 -> m3) gives zonk(m1) = m2 -> m3

def test_meta_binds_to_fun_of_metas():
    """unify(m1, m2 -> m3) binds m1 to the function type"""
    m1 = TY.meta(1)
    m2 = TY.meta(2)
    m3 = TY.meta(3)
    fun_ty = TY.fun(m2, m3)
    unify(m1, fun_ty)
    assert zonk_type(m1) == fun_ty

def test_meta_binds_to_fun_of_metas_reverse():
    """unify(m2 -> m3, m1) binds m1 to the function type"""
    m1 = TY.meta(1)
    m2 = TY.meta(2)
    m3 = TY.meta(3)
    fun_ty = TY.fun(m2, m3)
    unify(fun_ty, m1)
    assert zonk_type(m1) == fun_ty

# ---
# unify(m1 -> m2, int -> int) gives m1: int, m2: int

def test_fun_of_metas_unifies_structurally():
    """unifying m1 -> m2 with Int -> Int binds both metas to Int"""
    m1 = TY.meta(1)
    m2 = TY.meta(2)
    unify(TY.fun(m1, m2), TY.fun(INT, INT))
    assert m1.ref.get() == INT
    assert m2.ref.get() == INT

def test_fun_of_metas_unifies_structurally_reverse():
    """unifying Int -> Int with m1 -> m2 binds both metas to Int"""
    m1 = TY.meta(1)
    m2 = TY.meta(2)
    unify(TY.fun(INT, INT), TY.fun(m1, m2))
    assert m1.ref.get() == INT
    assert m2.ref.get() == INT

# ---
# two unbound metas link together

def test_two_unbound_metas_link():
    """two unbound metas unify by linking m1 -> m2"""
    m1 = TY.meta(1)
    m2 = TY.meta(2)
    unify(m1, m2)
    assert m1.ref.get() == m2

def test_linked_metas_resolve_on_later_unify():
    """after linking m1 -> m2, unifying m2 with Int resolves both"""
    m1 = TY.meta(1)
    m2 = TY.meta(2)
    unify(m1, m2)
    unify(m2, INT)
    assert zonk_type(m1) == INT
    assert zonk_type(m2) == INT

# ---
# already-bound meta unwraps correctly

def test_bound_meta_unwraps_lhs():
    """meta already bound to Int unifies with Int via unwrap"""
    m = TY.meta(1)
    m.ref.set(INT)
    unify(m, INT)  # should not raise

def test_bound_meta_unwraps_rhs():
    """Int unifies with meta already bound to Int via unwrap"""
    m = TY.meta(1)
    m.ref.set(INT)
    unify(INT, m)  # should not raise

def test_bound_meta_mismatch_fails():
    """meta bound to Int cannot unify with a different tycon"""
    m = TY.meta(1)
    m.ref.set(INT)
    with pytest.raises(TyCkException, match="Cannot unify"):
        unify(m, TyCon("Bool"))

# ---
# occurrence check

def test_occurrence_check():
    """meta cannot unify with a type containing itself (infinite type)"""
    m = TY.meta(1)
    with pytest.raises(TyCkException, match="Occurrence check"):
        unify(m, TY.fun(m, INT))
