from systemf.elab2.types import *

# \forall a sk1. a -> sk1
_a = TY.bound_var("a")
_sk1 = TY.skolem("sk1", 1)
TEST_TY = TY.forall([_a, _sk1], TY.fun(_a, _sk1))

# (\forall a sk1. a -> sk1) -> b -> sk2
TEST_TY2 = TY.fun(TEST_TY, TY.fun(TY.bound_var("b"), TY.skolem("sk2", 2)))

# m1 -> m2
M3 = TY.meta(3)
M3.ref.set(INT)
M1 = TY.meta(1)
M1.ref.set(M3)
TEST_TY3 = TY.fun(M1, TY.meta(2))

# ---
# free types

def test_get_free_vars():
    """get variables, exclude nested forall bound vars"""
    assert get_free_vars([TEST_TY2]) == [TY.bound_var("b"), TY.skolem("sk2", 2)]

def test_get_meta_vars():
    """get remaining meta variables, after zonk (unifed meta vars excluded)"""
    assert get_meta_vars([TEST_TY3]) == [TY.meta(2)]

# ---
# zonk type

def test_zonk_type():
    """zonk gets final type for unifed meta variables"""
    assert zonk_type(TEST_TY3) == TY.fun(INT, TY.meta(2))

def test_zonk_type_shortcircuit():
    """zonk shortcircuits long chain of meta variables"""
    M3 = TY.meta(3)
    M3.ref.set(INT)
    M1 = TY.meta(1)
    M1.ref.set(M3)
    assert zonk_type(M1) == INT
    assert M1.ref == Ref(INT)

# ---
# pretty printer
P = TyPrinter()

def test_show_prec():
    assert P.show_prec(INT, 0) == "Int"
    assert P.show_prec(TY.fun(INT, INT), 2) == "(Int -> Int)"
    assert P.show_prec(TY.forall([TY.bound_var("a")], TY.fun(TY.bound_var("a"), INT)), 0) == "forall a. a -> Int"
    assert P.show_prec(TY.meta(1), 0) == "$m1"
    assert P.show_prec(TY.fun(TY.forall([TY.bound_var("a")], INT), INT), 0) == "(forall a. Int) -> Int"

# ---
# subst_ty
#
# test spec:
# - vars in test substituted
# - vars shadowed by forall not substituted
# - vars not in test not substituted
# - vars free in nested forall are substituted

def test_subst_ty_replaces_vars_in_type():
    """Variables that appear in the type are substituted."""
    a = TY.bound_var("a")
    ty = TY.fun(a, TY.int_ty())
    res = subst_ty([a], [TY.int_ty()], ty)
    assert res == TY.fun(TY.int_ty(), TY.int_ty())

def test_subst_ty_respects_forall_shadowing():
    """Variables bound by a forall are shadowed and should not be substituted."""
    a = TY.bound_var("a")
    forall_ty = TY.forall([a], TY.fun(a, TY.int_ty()))
    res = subst_ty([a], [TY.int_ty()], forall_ty)
    # substitution shouldn't penetrate the bound variable 'a'
    assert res == forall_ty

def test_subst_ty_ignores_unrelated_vars():
    """Substitutions for variables not present in the type leave it unchanged."""
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    ty = TY.fun(a, TY.int_ty())
    res = subst_ty([b], [TY.int_ty()], ty)
    assert res == ty

def test_subst_ty_substitutes_free_vars_in_nested_forall():
    """Variables free in nested forall (not bound by it) are substituted."""
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    # \forall a. b -> a
    # Here 'b' is free in the forall, only 'a' is bound
    forall_ty = TY.forall([a], TY.fun(b, a))
    res = subst_ty([b], [TY.int_ty()], forall_ty)
    # 'b' should be substituted even though it's inside the forall
    assert res == TY.forall([a], TY.fun(TY.int_ty(), a))

def test_subst_ty_arg_forall():
    """Substitution in forall argument is respected."""
    # [a/INT] (forall b. a -> b) -> a -> b
    # => (forall b. INT -> b) -> INT -> b
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    ty = TY.fun(TY.forall([b], TY.fun(a, b)), TY.fun(a, b))
    res = subst_ty([a], [INT], ty)
    assert res == TY.fun(TY.forall([b], TY.fun(INT, b)), TY.fun(INT, b))
