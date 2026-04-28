from typing import Any, Callable

import pytest

from systemf.elab2.tyck import Check, Defer, Env, Infer, TyCk, TyCkImpl, run_infer, extend_env
from systemf.elab2.types import (
    C, INT, STRING, TY, CoreTm, Lit, LitInt, Ty, TyCkException, WP_HOLE,
    zonk_type
)

# =============================================================================
# Test Framework - Functional API
# =============================================================================

def check(
    term_builder: Callable[[TyCkImpl[CoreTm]], TyCk[Defer[CoreTm]]],
    expected_ty: Ty,
    cb_core: Callable[[CoreTm], None],
    env: Env = None,
) -> Callable[[TyCkImpl[CoreTm]], None]:
    """Build a check-mode runner.

    Returns a function that takes t, runs check, and calls cb_core with result.
    """
    def _run(t: TyCkImpl[CoreTm]) -> None:
        result = term_builder(t)(env, Check(expected_ty))
        cb_core(result())
    return _run

def infer(
    term_builder: Callable[[TyCkImpl[CoreTm]], TyCk[Defer[CoreTm]]],
    cb_ty: Callable[[Ty], None],
    cb_core: Callable[[CoreTm], None],
    env: Env = None,
) -> Callable[[TyCkImpl[CoreTm]], None]:
    """Build an infer-mode runner.

    Returns a function that takes t, runs infer, and calls callbacks.
    """
    def _run(t: TyCkImpl[CoreTm]) -> None:
        poly_term = t.poly(term_builder(t))
        ty, res = run_infer(env, poly_term)
        cb_ty(ty)
        cb_core(res())
    return _run

def run_tyck(runnable: Callable[[TyCkImpl[CoreTm]], Any]):
    """Execute a test runnable with a fresh TyCkImpl."""
    impl = TyCkImpl(C)
    return runnable(impl)

# =============================================================================
# Callback Helpers
# =============================================================================

def check_type(expected: Ty) -> Callable[[Ty], None]:
    def _cb(ty: Ty):
        assert zonk_type(ty) == expected
    return _cb

def equals_term(expected: CoreTm) -> Callable[[CoreTm], None]:
    def _cb(term: CoreTm):
        assert term == expected
    return _cb

def ignore_term(_term: CoreTm):
    pass

def ignore_ty(_ty: Ty):
    pass

# =============================================================================
# Figure 8: Bidirectional Type Checking Rules
# =============================================================================

# -----------------------------------------------------------------------------
# INT — Integer Literal
# -----------------------------------------------------------------------------

def test_int_infer():
    """INT (infer): 42 synthesizes Int."""
    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.lit(LitInt(42)),
            cb_ty=check_type(INT),
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

def test_int_check():
    """INT (check): 42 checks against Int."""
    def _run(t: TyCkImpl[CoreTm]):
        check(
            lambda t: t.lit(LitInt(42)),
            expected_ty=INT,
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

def test_int_check_fail():
    """INT (check anti): 42 checking against String fails."""
    with pytest.raises(TyCkException):
        def _run(t: TyCkImpl[CoreTm]):
            check(
                lambda t: t.lit(LitInt(42)),
                expected_ty=STRING,
                cb_core=ignore_term,
            )(t)
        run_tyck(_run)

# -----------------------------------------------------------------------------
# VAR — Variable Lookup
# -----------------------------------------------------------------------------

def test_var_mono():
    """VAR: x:Int in env yields Int."""
    env = extend_env("x", INT, None)

    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.var("x"),
            cb_ty=check_type(INT),
            cb_core=ignore_term,
            env=env,
        )(t)
    run_tyck(_run)

def test_var_poly():
    """VAR: id:∀a.a→a instantiates to ?1→?1."""
    a = TY.bound_var("a")
    id_ty = TY.forall([a], TY.fun(a, a))
    env = extend_env("id", id_ty, None)

    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.var("id"),
            cb_ty=ignore_ty,  # Will be $m0 -> $m0, spot check only
            cb_core=ignore_term,
            env=env,
        )(t)
    run_tyck(_run)

# -----------------------------------------------------------------------------
# ABS — Lambda
# -----------------------------------------------------------------------------

def test_abs1_infer():
    """ABS1 (infer): λx.x infers ?1→?1."""
    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.lam("x", t.var("x")),
            cb_ty=ignore_ty,  # Will be $m0 -> $m0
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

def test_abs2_check():
    """ABS2 (check): λx.x checks against Int→Int."""
    def _run(t: TyCkImpl[CoreTm]):
        check(
            lambda t: t.lam("x", t.var("x")),
            expected_ty=TY.fun(INT, INT),
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

def test_abs2_check_fail():
    """ABS2 (check anti): λx.x checking against Int→String fails."""
    with pytest.raises(TyCkException):
        def _run(t: TyCkImpl[CoreTm]):
            check(
                lambda t: t.lam("x", t.var("x")),
                expected_ty=TY.fun(INT, STRING),
                cb_core=ignore_term,
            )(t)
        run_tyck(_run)

# -----------------------------------------------------------------------------
# AABS — Annotated Lambda
# -----------------------------------------------------------------------------

def test_aabs_infer():
    """AABS1 (infer): λx:Int.x infers Int→Int."""
    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.alam("x", INT, t.var("x")),
            cb_ty=check_type(TY.fun(INT, INT)),
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

def test_aabs_check():
    """AABS2 (check): λx:Int.x checks against Int→Int."""
    def _run(t: TyCkImpl[CoreTm]):
        check(
            lambda t: t.alam("x", INT, t.var("x")),
            expected_ty=TY.fun(INT, INT),
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

# -----------------------------------------------------------------------------
# APP — Application
# -----------------------------------------------------------------------------

def test_app_mono():
    """APP (mono): id 42 where id:Int→Int yields Int."""
    env = extend_env("id", TY.fun(INT, INT), None)

    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.app(t.var("id"), t.lit(LitInt(42))),
            cb_ty=check_type(INT),
            cb_core=ignore_term,
            env=env,
        )(t)
    run_tyck(_run)

def test_app_poly():
    """APP (poly): id 42 where id:∀a.a→a yields Int."""
    a = TY.bound_var("a")
    id_ty = TY.forall([a], TY.fun(a, a))
    env = extend_env("id", id_ty, None)

    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.app(t.var("id"), t.lit(LitInt(42))),
            cb_ty=check_type(INT),
            cb_core=ignore_term,
            env=env,
        )(t)
    run_tyck(_run)

# -----------------------------------------------------------------------------
# LET — Let Binding
# -----------------------------------------------------------------------------

def test_let_simple():
    """LET: let x = 42 in x yields Int."""
    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.let("x", t.lit(LitInt(42)), t.var("x")),
            cb_ty=check_type(INT),
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

def test_let_poly():
    """LET (poly): let id = λx.x in id 42 yields Int."""
    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.let("id", t.lam("x", t.var("x")),
                t.app(t.var("id"), t.lit(LitInt(1)))),
            cb_ty=check_type(INT),
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

# -----------------------------------------------------------------------------
# GEN — Generalization
# -----------------------------------------------------------------------------

def test_gen1_infer():
    """GEN1 (infer): λx.x generalizes to ∀a.a→a."""
    a = TY.bound_var("a")
    expected = TY.forall([a], TY.fun(a, a))

    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.lam("x", t.var("x")),
            cb_ty=check_type(expected),
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

def test_gen2_check():
    """GEN2 (check): λx.x checks against ∀a.a→a."""
    a = TY.bound_var("a")
    expected = TY.forall([a], TY.fun(a, a))

    def _run(t: TyCkImpl[CoreTm]):
        check(
            lambda t: t.poly(t.lam("x", t.var("x"))),
            expected_ty=expected,
            cb_core=ignore_term,
        )(t)
    run_tyck(_run)

# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------

def test_integration_identity():
    """End-to-end: let id = λx.x in id 42"""
    a = TY.bound_var("a")

    def _run(t: TyCkImpl[CoreTm]):
        infer(
            lambda t: t.let("id", t.lam("x", t.var("x")),
                t.app(t.var("id"), t.lit(LitInt(1)))),
            cb_ty=check_type(INT),
            cb_core=equals_term(
                C.let(
                    "id",
                    TY.forall([a], TY.fun(a, a)),
                    C.tylam(a, C.lam("x", a, C.var("x", a))),
                    C.app(
                        C.tyapp(C.var("id", TY.forall([a], TY.fun(a, a))), INT),
                        C.lit(LitInt(1))
                    )
                )
            ),
        )(t)
    run_tyck(_run)
