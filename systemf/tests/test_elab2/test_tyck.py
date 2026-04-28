import itertools
from typing import Callable

from systemf.elab2.tyck import Defer, TyCk, TyCkImpl, allnames, quantify, run_infer
from systemf.elab2.types import C, INT, TY, CoreTm, Lit, LitInt, SyntaxDSL, Ty, zonk_type

# ---
# test quantify
#
# quantify should correctly replace meta vars with bound vars

def test_quantify_replaces_meta_vars():
    # create two meta type variables
    m1 = TY.meta(1)
    m2 = TY.meta(2)
    # build a type: m1 -> (Int -> m2)
    ty = TY.fun(m1, TY.fun(TY.int_ty(), m2))
    binders, q = quantify([m1, m2], ty)

    # result should be: forall a b. a -> (Int -> b)
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    expected = TY.forall(
        [a, b],
        TY.fun(a, TY.fun(INT, b)),
    )
    assert binders == [a, b]
    assert q == expected

    # the original metas should have their refs set to the bound vars
    assert m1.ref.get() == a
    assert m2.ref.get() == b

# ---
# misc

def test_allnames():
    """
    allnames generates names correctly
    """
    assert list(itertools.islice(allnames(), 3)) == ["a", "b", "c"]
    assert list(itertools.islice(allnames(), 29))[-3:] == ["a1", "b1", "c1"]
