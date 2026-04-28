from typing import Any, Callable

import pytest

from systemf.elab2.tyck import Check, Defer, TyCk, TyCkImpl, run_infer
from systemf.elab2.types import (
    C, INT, STRING, TY, CoreTm, Lit, LitInt, Ref, Ty, TyCkException, WP_HOLE,
    WpCast, WpFun, WpTyApp, WpTyLam, wp_compose, wp_fun, zonk_type, zonk_wrapper
)

# =============================================================================
# Figure 9: Skolemization Tests (PR Rules)
# =============================================================================
# Tests for pr(sigma) - converting polymorphic types to weak-prenex form
# See tyck_examples.md "Figure 9: Subsumption and Skolemization"

def test_skolemise_mono():
    """PRMONO: pr(Int) = Int ↦ λx.x

    See tyck_examples.md "Figure 9: Subsumption and Skolemization" for full spec.
    """
    def _run(impl: TyCkImpl[Any]):
        sks, ty, w = impl.skolemise(INT)
        assert sks == []
        assert ty == INT
        assert w == WP_HOLE
    run_tyck(_run)


def test_skolemise_prpoly():
    """PRPOLY: pr(∀a. a → a) = sk_a → sk_a ↦ Λsk_a.[HOLE]

    See tyck_examples.md "PRPOLY — Polymorphic Type" for full spec.
    """
    a = TY.bound_var("a")
    t = TY.forall([a], TY.fun(a, a))
    def _run(impl: TyCkImpl[Any]):
        sks, ty, w = impl.skolemise(t)
        sk = TY.skolem("a", 0)
        assert sks == [sk]
        assert ty == TY.fun(sk, sk)
        # PRFUN on (sk_a → sk_a) produces WpFun(sk_a, WP_HOLE, WP_HOLE)
        # Then PRPOLY: WpCompose(WpTyLam(sk), WpFun(...))
        # No simplification applies (neither is WP_HOLE)
        prfun = wp_fun(sk, WP_HOLE, WP_HOLE)
        assert w == WpTyLam(sk)  # WpCompose(WpTyLam(sk), prfun)
    run_tyck(_run)


def test_skolemise_prfun():
    """PRFUN: pr(Int → ∀a. a) = Int → sk_a ↦ WpFun(Int, WP_HOLE, WpTyLam(sk_a))

    See tyck_examples.md "PRFUN — Function Type with Prenex Result" for full spec.
    """
    a = TY.bound_var("a")
    t = TY.fun(INT, TY.forall([a], a))
    def _run(impl: TyCkImpl[Any]):
        sks, ty, w = impl.skolemise(t)
        sk = TY.skolem("a", 0)
        assert sks == [sk]
        assert ty == TY.fun(INT, sk)
        # Inner wrap from PRPOLY: WpCompose(WpTyLam(sk), WP_HOLE) simplifies to WpTyLam(sk)
        inner_wrap = wp_compose(WpTyLam(sk), WP_HOLE)
        assert w == WpFun(INT, WP_HOLE, inner_wrap)
    run_tyck(_run)


def test_skolemise_prfun_poly_arg():
    """PRFUN with polymorphic argument: pr((∀a.a→a) → Int) = (∀a.a→a) → Int (no change)

    Forall in contravariant position is not prenex - no skolemization.
    """
    a = TY.bound_var("a")
    poly_id = TY.forall([a], TY.fun(a, a))
    t = TY.fun(poly_id, INT)
    def _run(impl: TyCkImpl[Any]):
        sks, ty, w = impl.skolemise(t)
        # No skolems introduced since forall is in contravariant position
        assert sks == []
        assert ty == TY.fun(poly_id, INT)
        assert w == wp_fun(poly_id, WP_HOLE, WP_HOLE)
    run_tyck(_run)


def test_skolemise_nested():
    """PRPOLY nested: pr(∀a.∀b. a → b → a) = sk_a → sk_b → sk_a

    See tyck_examples.md "Nested: ∀a. ∀b. a → b → a" for full spec.
    """
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    t = TY.forall([a], TY.forall([b], TY.fun(a, TY.fun(b, a))))
    def _run(impl: TyCkImpl[Any]):
        sks, ty, w = impl.skolemise(t)
        sk1, sk2 = TY.skolem("a", 0), TY.skolem("b", 1)
        assert sks == [sk1, sk2]
        assert ty == TY.fun(sk1, TY.fun(sk2, sk1))
        # Inner: PRFUN on (sk_b → sk_a) with PRMONO result
        inner_prfun = wp_fun(sk2, WP_HOLE, WP_HOLE)
        # Middle: PRFUN on (sk_a → (sk_b → sk_a))
        middle_prfun = wp_fun(sk1, WP_HOLE, inner_prfun)
        # Outer PRPOLY on b: WpCompose(WpTyLam(sk2), middle_prfun)
        # No simplification (neither is WP_HOLE)
        middle_prpoly = wp_compose(WpTyLam(sk2), middle_prfun)
        # Outer PRPOLY on a: WpCompose(WpTyLam(sk1), middle_prpoly)
        # No simplification (neither is WP_HOLE)
        assert w == wp_compose(WpTyLam(sk1), middle_prpoly)
    run_tyck(_run)


def test_skolemise_complex():
    """Complex: pr(∀a. a → ∀b. b → a) from the paper example

    See tyck_examples.md "Complex Case: ∀a. a → ∀b. b → a" for full spec.
    """
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    t = TY.forall([a], TY.fun(a, TY.forall([b], TY.fun(b, a))))
    def _run(impl: TyCkImpl[Any]):
        sks, ty, w = impl.skolemise(t)
        assert sks == [TY.skolem("a", 0), TY.skolem("b", 1)]
        sk1, sk2 = sks
        assert ty == TY.fun(sk1, TY.fun(sk2, sk1))
        # Innermost: PRFUN on (sk_b → sk_a) with PRMONO
        inner_prfun = wp_fun(sk2, WP_HOLE, WP_HOLE)
        # Inner PRPOLY on b: WpCompose(WpTyLam(sk2), inner_prfun)
        # No simplification (inner_prfun is not WP_HOLE)
        inner_prpoly = wp_compose(WpTyLam(sk2), inner_prfun)
        # Middle PRFUN: (sk_a → res)
        middle_prfun = wp_fun(sk1, WP_HOLE, inner_prpoly)
        # Outer PRPOLY on a: WpCompose(WpTyLam(sk1), middle_prfun)
        assert w == wp_compose(WpTyLam(sk1), middle_prfun)
    run_tyck(_run)

# =============================================================================
# Subsumption Tests (DSK Rules)
# =============================================================================
# Tests for subs_check(sigma1, sigma2) - checking sigma1 ≤ sigma2
# See tyck_examples.md "Subsumption Rules"

def test_subs_check_mono():
    """MONO: Int ≤ Int - monomorphic types unify directly.

    See tyck_examples.md "MONO" for full spec.
    """
    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(INT, INT)
        wrap = zonk_wrapper(wrap)
        # Unification succeeds, WpCast(Int, Int) simplifies to WP_HOLE
        assert wrap == WP_HOLE
    run_tyck(_run)


def test_subs_check_deep_skol():
    """DEEP-SKOL: ∀a.a→a ≤ Int→Int - polymorphic to monomorphic subsumption.

    See tyck_examples.md "DEEP-SKOL" for full spec.
    """
    a = TY.bound_var("a")
    poly_id = TY.forall([a], TY.fun(a, a))
    mono_id = TY.fun(INT, INT)

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(poly_id, mono_id)
        wrap = zonk_wrapper(wrap)
        assert wrap == WpTyApp(INT)
    run_tyck(_run)

def test_subs_check_anti_base():
    """ANTI-CASE: Int ≤ ∀a.a MUST FAIL.

    RHS skolemizes to sk_a; sk_a cannot unify with Int (rigid).
    See tyck_examples.md "Anti-Tests (Must Fail)" for full spec.
    """
    a = TY.bound_var("a")
    rhs = TY.forall([a], a)

    def _run(impl: TyCkImpl[Any]):
        with pytest.raises(TyCkException):
            impl.subs_check(INT, rhs)
    run_tyck(_run)

def test_subs_check_deep_skol_anti():
    """ANTI-CASE: Int→String ≤ ∀a.a→a MUST FAIL

    Rigid skolem cannot satisfy conflicting constraints.
    See tyck_examples.md "Anti-case explanation" for full spec.
    """
    a = TY.bound_var("a")
    poly_id = TY.forall([a], TY.fun(a, a))
    bad_mono = TY.fun(INT, STRING)

    def _run(impl: TyCkImpl[Any]):
        with pytest.raises(TyCkException):
            impl.subs_check(bad_mono, poly_id)
    run_tyck(_run)


def test_subs_check_spec_simple():
    """SPEC: ∀a.a ≤ Int - simple instantiation with fresh meta.

    See tyck_examples.md "SPEC — Instantiate Left" for full spec.
    """
    a = TY.bound_var("a")
    poly_a = TY.forall([a], a)

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(poly_a, INT)
        wrap = zonk_wrapper(wrap)
        # Instantiation creates WpTyApp(Int)
        assert wrap == WpTyApp(INT)
    run_tyck(_run)


def test_subs_check_spec_fun():
    """SPEC: ∀a.a→a ≤ Int→Int - instantiate in function position.

    See tyck_examples.md "SPEC — Instantiate Left" for full spec.
    """
    a = TY.bound_var("a")
    poly_id = TY.forall([a], TY.fun(a, a))
    mono_id = TY.fun(INT, INT)

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(poly_id, mono_id)
        wrap = zonk_wrapper(wrap)
        assert wrap == WpTyApp(INT)
    run_tyck(_run)


def test_subs_check_spec_nested():
    """SPEC: ∀a.∀b.a→b ≤ Int→String - nested foralls instantiate to metas.

    See tyck_examples.md "SPEC — Instantiate Left" for full spec.
    """
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    poly_fun = TY.forall([a], TY.forall([b], TY.fun(a, b)))
    mono_fun = TY.fun(INT, STRING)

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(poly_fun, mono_fun)
        wrap = zonk_wrapper(wrap)
        # Instantiation: TyApp(m_b) <*> TyApp(m_a) with m_a=Int, m_b=String
        # Subsumption: Fun(Int, ID, ID) from function check
        w_inst = wp_compose(WpTyApp(STRING), WpTyApp(INT))
        w_fun = wp_fun(INT, WP_HOLE, WP_HOLE)
        assert wrap == wp_compose(w_fun, w_inst)
    run_tyck(_run)


def test_subs_check_spec_paper():
    """SPEC (Paper §4.6.2): Bool→(∀a.a→a) ≤ Bool→Int→Int.

    RHS is Bool→(Int→Int), so ∀a.a→a instantiates to Int→Int.
    See tyck_examples.md "SPEC — Instantiate Left" for full spec.
    """
    a = TY.bound_var("a")
    lhs = TY.fun(INT, TY.forall([a], TY.fun(a, a)))  # Using INT as Bool proxy
    rhs = TY.fun(INT, TY.fun(INT, INT))

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(lhs, rhs)
        wrap = zonk_wrapper(wrap)
        # Wrapper composes the argument coercion with result coercion
        assert wrap == wp_fun(INT, WP_HOLE, WpTyApp(INT))
    run_tyck(_run)


def test_subs_check_fun_identity():
    """FUN: Int→String ≤ Int→String - monomorphic function identity.

    See tyck_examples.md "FUN — Function Subsumption" for full spec.
    """
    fun_ty = TY.fun(INT, STRING)

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(fun_ty, fun_ty)
        # Both arg and res unify, wrapper is identity function
        assert wrap == wp_fun(INT, WpCast(INT, INT), WpCast(STRING, STRING))
    run_tyck(_run)


def test_subs_check_fun_contra():
    """FUN: (Int→Int)→String ≤ (∀a.a→a)→String - contravariant arg.

    See tyck_examples.md "FUN — Function Subsumption" for full spec.
    """
    a = TY.bound_var("a")
    poly_arg = TY.forall([a], TY.fun(a, a))
    lhs = TY.fun(TY.fun(INT, INT), STRING)
    rhs = TY.fun(poly_arg, STRING)

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(lhs, rhs)
        wrap = zonk_wrapper(wrap)

        assert wrap == wp_fun(poly_arg, WpTyApp(INT), WP_HOLE)
    run_tyck(_run)

#
# WpFun(arg_ty=Int -> Int, wp_arg=WpTyApp(ty_arg=Int), wp_res=WpHole())
# WpFun(arg_ty=forall a. a -> a, wp_arg=WpTyApp(ty_arg=Int), wp_res=WpHole())
def test_subs_check_fun_paper():
    """FUN (Paper §4.6.2): (Int→Int)→Bool ≤ (∀a.a→a)→Bool.

    See tyck_examples.md "FUN — Function Subsumption" for full spec.
    """
    a = TY.bound_var("a")
    poly_arg = TY.forall([a], TY.fun(a, a))
    lhs = TY.fun(TY.fun(INT, INT), INT)  # Using INT as Bool proxy
    rhs = TY.fun(poly_arg, INT)

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(lhs, rhs)
        wrap = zonk_wrapper(wrap)
        # Arg coercion: ∀a.a→a to Int→Int via instantiation
        assert wrap == wp_fun(poly_arg, WpTyApp(INT), WP_HOLE)
    run_tyck(_run)


def test_subs_check_deep_skol_alpha():
    """DEEP-SKOL: ∀a.a→a ≤ ∀b.b→b - alpha equivalence.

    See tyck_examples.md "DEEP-SKOL — Skolemize Right" for full spec.
    """
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    lhs = TY.forall([a], TY.fun(a, a))
    rhs = TY.forall([b], TY.fun(b, b))

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(lhs, rhs)
        wrap = zonk_wrapper(wrap)
        # Skolemize: TyLam(sk_b) <*> Fun(sk_b, ID, ID)
        # Subsumption: Fun(sk_b, ID, ID)
        # Instantiation: TyApp(m_a) with m_a=sk_b
        sk_b = TY.skolem("b", 0)
        w_sk = wp_compose(WpTyLam(sk_b), wp_fun(sk_b, WP_HOLE, WP_HOLE))
        w_subs = wp_fun(sk_b, WP_HOLE, WP_HOLE)
        w_inst = WpTyApp(sk_b)
        assert wrap == wp_compose(w_sk, wp_compose(w_subs, w_inst))
    run_tyck(_run)


def test_subs_check_deep_skol_prenex_fwd():
    """DEEP-SKOL (Paper §4.6.2): ∀ab.a→b→b ≤ ∀a.a→(∀b.b→b).

    RHS skolemizes to sk_a→sk_b→sk_b via PRFUN.
    See tyck_examples.md "DEEP-SKOL — Weak Prenex Equivalences" for full spec.
    """
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    lhs = TY.forall([a], TY.forall([b], TY.fun(a, TY.fun(b, b))))
    rhs = TY.forall([a], TY.fun(a, TY.forall([b], TY.fun(b, b))))

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(lhs, rhs)
        wrap = zonk_wrapper(wrap)

        sk_a = TY.skolem("a", 0)
        sk_b = TY.skolem("b", 1)

        # Skolemization: TyLam(sk_a) <*> Fun(sk_a, ID, TyLam(sk_b) <*> Fun(sk_b, ID, ID))
        w_sk_inner = wp_fun(sk_b, WP_HOLE, WP_HOLE)
        w_sk_poly_b = wp_compose(WpTyLam(sk_b), w_sk_inner)
        w_sk_fun = wp_fun(sk_a, WP_HOLE, w_sk_poly_b)
        w_sk = wp_compose(WpTyLam(sk_a), w_sk_fun)

        # Subsumption: Fun(sk_a, ID, Fun(sk_b, ID, ID))
        w_subs_inner = wp_fun(sk_b, WP_HOLE, WP_HOLE)
        w_subs = wp_fun(sk_a, WP_HOLE, w_subs_inner)

        # Instantiation: TyApp(sk_b) <*> TyApp(sk_a) (metas unified with skolems)
        w_inst = wp_compose(WpTyApp(sk_b), WpTyApp(sk_a))

        expected = wp_compose(w_sk, wp_compose(w_subs, w_inst))
        assert wrap == expected
    run_tyck(_run)


def test_subs_check_deep_skol_prenex_rev():
    """DEEP-SKOL (Paper §4.6.2): ∀a.a→(∀b.b→b) ≤ ∀ab.a→b→b.

    Reverse: pr(RHS) floats ∀b to top, creating sk_a→sk_b→sk_b.
    See tyck_examples.md "DEEP-SKOL — Weak Prenex Equivalences" for full spec.
    """
    a = TY.bound_var("a")
    b = TY.bound_var("b")
    lhs = TY.forall([a], TY.fun(a, TY.forall([b], TY.fun(b, b))))
    rhs = TY.forall([a], TY.forall([b], TY.fun(a, TY.fun(b, b))))

    def _run(impl: TyCkImpl[Any]):
        wrap = impl.subs_check(lhs, rhs)
        wrap = zonk_wrapper(wrap)
        sk_a = TY.skolem("a", 0)
        sk_b = TY.skolem("b", 1)
        # Skolemization: TyLam(sk_a) <*> TyLam(sk_b) <*> Fun(sk_a, ID, Fun(sk_b, ID, ID))
        w_sk = wp_compose(WpTyLam(sk_a), wp_compose(WpTyLam(sk_b),
            wp_fun(sk_a, WP_HOLE, wp_fun(sk_b, WP_HOLE, WP_HOLE))))
        # Subsumption: Fun(sk_a, ID, Fun(sk_b, ID, ID) <*> TyApp(sk_b))
        w_subs_inner = wp_compose(wp_fun(sk_b, WP_HOLE, WP_HOLE), WpTyApp(sk_b))
        w_subs = wp_fun(sk_a, WP_HOLE, w_subs_inner)
        # Instantiation: TyApp(sk_a) (outer), with TyApp(sk_b) nested in subsumption
        w_inst = WpTyApp(sk_a)
        expected = wp_compose(w_sk, wp_compose(w_subs, w_inst))
        assert wrap == expected
    run_tyck(_run)


def test_subs_check_anti_diff_res():
    """ANTI-CASE: Int→String ≤ Int→Bool MUST FAIL.

    Different result types cannot unify.
    """
    lhs = TY.fun(INT, STRING)
    rhs = TY.fun(INT, INT)  # Using INT as Bool proxy

    def _run(impl: TyCkImpl[Any]):
        with pytest.raises(TyCkException):
            impl.subs_check(lhs, rhs)
    run_tyck(_run)


def test_subs_check_anti_contra():
    """ANTI-CASE: (∀a.a→a)→Int ≤ (Int→Int)→Int MUST FAIL.

    Contravariant arg: Int→Int ≤ ∀a.a→a fails (skolem rigid).
    See tyck_examples.md "FUN — Function Subsumption" for full spec.
    """
    a = TY.bound_var("a")
    poly_arg = TY.forall([a], TY.fun(a, a))
    lhs = TY.fun(poly_arg, INT)
    rhs = TY.fun(TY.fun(INT, INT), INT)

    def _run(impl: TyCkImpl[Any]):
        with pytest.raises(TyCkException):
            impl.subs_check(lhs, rhs)
    run_tyck(_run)


def test_subs_check_anti_int_poly():
    """ANTI-CASE: Int→Int ≤ ∀a.a→a MUST FAIL.

    RHS skolemizes to sk_a→sk_a; sk_a cannot unify with Int (rigid).
    """
    a = TY.bound_var("a")
    rhs = TY.forall([a], TY.fun(a, a))
    lhs = TY.fun(INT, INT)

    def _run(impl: TyCkImpl[Any]):
        with pytest.raises(TyCkException):
            impl.subs_check(lhs, rhs)
    run_tyck(_run)


# =============================================================================
# INST Tests (inst method)
# =============================================================================

def test_inst_infer_forall():
    """INST1: ∀a.a infers to ?1 with WpTyApp(?1)"""
    def _run(impl: TyCkImpl[Any]):
        a = TY.bound_var("a")
        ty = TY.forall([a], a)

        ty_result, wrap = run_infer(None, impl.inst(ty))

        assert ty_result == TY.meta(0)
        assert wrap == WpTyApp(ty_result)
    run_tyck(_run)


def test_inst_infer_mono():
    """INST1: Int infers to Int with WP_HOLE"""
    def _run(impl: TyCkImpl[Any]):
        ty, wrap = run_infer(None, impl.inst(INT))

        assert ty == INT
        assert wrap == WP_HOLE
    run_tyck(_run)


def test_inst_check_contra():
    """INST2: ∀a.a→a checks against Int→Int via contravariant unification"""
    def _run(impl: TyCkImpl[Any]):
        a = TY.bound_var("a")
        ty = TY.forall([a], TY.fun(a, a))
        ty2 = TY.fun(INT, INT)

        wrap = impl.inst(ty)(None, Check(ty2))
        wrap = zonk_wrapper(wrap)

        assert wrap == WpTyApp(INT)
    run_tyck(_run)


# =============================================================================
# Test Helpers
# =============================================================================

def run_tyck(run: Callable[[TyCkImpl[CoreTm]], None]):
    impl = TyCkImpl(C)
    run(impl)
