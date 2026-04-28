"""Subsumption, skolemization, and instantiation tests.

Ported from elab2 test_tyck_examples_util_rules.py.
Tests the core type inference rules from Putting2007 (JFP):
- PR rules: skolemization (PRMONO, PRPOLY, PRFUN)
- DSK rules: subsumption (DEEP-SKOL, SPEC, FUN)
- INST rules: instantiation
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
from systemf.elab3.types.wrapper import (
    WP_HOLE,
    WpCast,
    WpCompose,
    WpFun,
    WpTyApp,
    WpTyLam,
    wp_compose,
    wp_fun,
    zonk_wrapper,
)
from systemf.utils.uniq import Uniq


INT = TyInt()
STRING = TyString()


class FakeUnifier(Unifier):
    def __init__(self) -> None:
        super().__init__("PuttingTest", Uniq(5000))

    def lookup_gbl(self, name: Name):
        raise KeyError(name)


def _ctx() -> FakeUnifier:
    return FakeUnifier()


class FakeCtx:
    def __init__(self):
        self.uniq = Uniq(6000)


class FakeNameGen:
    def new_name(self, name, loc=None):
        return Name("PuttingTest", name, FakeCtx().uniq.make_uniq(), loc)


def _bound(name: str) -> BoundTv:
    return BoundTv(name=Name("PuttingTest", name, hash(name) % 10000))


# =============================================================================
# PR Rules: Skolemization
# =============================================================================


def test_skolemise_mono():
    ctx = _ctx()
    sks, ty, w = ctx.skolemise(INT)
    assert sks == []
    assert ty == INT
    assert w == WP_HOLE


def test_skolemise_prpoly():
    a = _bound("a")
    t = TyForall([a], TyFun(a, a))

    ctx = _ctx()
    sks, ty, w = ctx.skolemise(t)
    assert len(sks) == 1
    sk = sks[0]
    assert isinstance(sk, SkolemTv)
    assert ty == TyFun(sk, sk)


def test_skolemise_prfun():
    a = _bound("a")
    t = TyFun(INT, TyForall([a], a))

    ctx = _ctx()
    sks, ty, w = ctx.skolemise(t)
    assert len(sks) == 1
    assert isinstance(sks[0], SkolemTv)
    assert ty == TyFun(INT, sks[0])


def test_skolemise_prfun_poly_arg():
    a = _bound("a")
    poly_id = TyForall([a], TyFun(a, a))
    t = TyFun(poly_id, INT)

    ctx = _ctx()
    sks, ty, w = ctx.skolemise(t)
    assert sks == []
    assert ty == TyFun(poly_id, INT)


def test_skolemise_nested():
    a = _bound("a")
    b = _bound("b")
    t = TyForall([a], TyForall([b], TyFun(a, TyFun(b, a))))

    ctx = _ctx()
    sks, ty, w = ctx.skolemise(t)
    assert len(sks) == 2
    sk1, sk2 = sks
    assert ty == TyFun(sk1, TyFun(sk2, sk1))


def test_skolemise_complex():
    a = _bound("a")
    b = _bound("b")
    t = TyForall([a], TyFun(a, TyForall([b], TyFun(b, a))))

    ctx = _ctx()
    sks, ty, w = ctx.skolemise(t)
    assert len(sks) == 2
    sk1, sk2 = sks
    assert ty == TyFun(sk1, TyFun(sk2, sk1))


# =============================================================================
# Subsumption Tests
# =============================================================================


def test_subs_check_mono():
    ctx = _ctx()
    wrap = ctx.subs_check(INT, INT)
    wrap = zonk_wrapper(wrap)
    assert wrap == WP_HOLE


def test_subs_check_deep_skol():
    a = _bound("a")
    poly_id = TyForall([a], TyFun(a, a))
    mono_id = TyFun(INT, INT)

    ctx = _ctx()
    wrap = ctx.subs_check(poly_id, mono_id)
    wrap = zonk_wrapper(wrap)
    assert wrap == WpTyApp(INT)


def test_subs_check_anti_base():
    a = _bound("a")
    rhs = TyForall([a], a)

    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.subs_check(INT, rhs)


def test_subs_check_deep_skol_anti():
    a = _bound("a")
    poly_id = TyForall([a], TyFun(a, a))
    bad_mono = TyFun(INT, STRING)

    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.subs_check(bad_mono, poly_id)


def test_subs_check_spec_simple():
    a = _bound("a")
    poly_a = TyForall([a], a)

    ctx = _ctx()
    wrap = ctx.subs_check(poly_a, INT)
    wrap = zonk_wrapper(wrap)
    assert wrap == WpTyApp(INT)


def test_subs_check_spec_fun():
    a = _bound("a")
    poly_id = TyForall([a], TyFun(a, a))
    mono_id = TyFun(INT, INT)

    ctx = _ctx()
    wrap = ctx.subs_check(poly_id, mono_id)
    wrap = zonk_wrapper(wrap)
    assert wrap == WpTyApp(INT)


def test_subs_check_fun_contra():
    a = _bound("a")
    poly_arg = TyForall([a], TyFun(a, a))
    lhs = TyFun(TyFun(INT, INT), STRING)
    rhs = TyFun(poly_arg, STRING)

    ctx = _ctx()
    wrap = ctx.subs_check(lhs, rhs)
    wrap = zonk_wrapper(wrap)
    assert wrap == wp_fun(poly_arg, WpTyApp(INT), WP_HOLE)


def test_subs_check_anti_diff_res():
    lhs = TyFun(INT, STRING)
    rhs = TyFun(INT, INT)

    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.subs_check(lhs, rhs)


def test_subs_check_anti_contra():
    a = _bound("a")
    poly_arg = TyForall([a], TyFun(a, a))
    lhs = TyFun(poly_arg, INT)
    rhs = TyFun(TyFun(INT, INT), INT)

    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.subs_check(lhs, rhs)


def test_subs_check_anti_int_poly():
    a = _bound("a")
    rhs = TyForall([a], TyFun(a, a))
    lhs = TyFun(INT, INT)

    ctx = _ctx()
    with pytest.raises(Exception):
        ctx.subs_check(lhs, rhs)


# =============================================================================
# Deep Skolem alpha equivalence and prenex
# =============================================================================


def test_subs_check_deep_skol_alpha():
    a = _bound("a")
    b = _bound("b")
    lhs = TyForall([a], TyFun(a, a))
    rhs = TyForall([b], TyFun(b, b))

    ctx = _ctx()
    wrap = ctx.subs_check(lhs, rhs)
    wrap = zonk_wrapper(wrap)
    assert isinstance(wrap, (WpCompose, WpTyLam))


def test_subs_check_spec_paper():
    a = _bound("a")
    lhs = TyFun(INT, TyForall([a], TyFun(a, a)))
    rhs = TyFun(INT, TyFun(INT, INT))

    ctx = _ctx()
    wrap = ctx.subs_check(lhs, rhs)
    wrap = zonk_wrapper(wrap)
    assert wrap == wp_fun(INT, WP_HOLE, WpTyApp(INT))


def test_subs_check_spec_nested():
    a = _bound("a")
    b = _bound("b")
    poly_fun = TyForall([a], TyForall([b], TyFun(a, b)))
    mono_fun = TyFun(INT, STRING)

    ctx = _ctx()
    wrap = ctx.subs_check(poly_fun, mono_fun)
    wrap = zonk_wrapper(wrap)
    assert wrap == wp_compose(wp_fun(INT, WP_HOLE, WP_HOLE), wp_compose(WpTyApp(STRING), WpTyApp(INT)))


def test_subs_check_fun_identity():
    fun_ty = TyFun(INT, STRING)

    ctx = _ctx()
    wrap = ctx.subs_check(fun_ty, fun_ty)
    wrap = zonk_wrapper(wrap)
    assert wrap == WP_HOLE


def test_subs_check_fun_paper():
    a = _bound("a")
    poly_arg = TyForall([a], TyFun(a, a))
    lhs = TyFun(TyFun(INT, INT), INT)
    rhs = TyFun(poly_arg, INT)

    ctx = _ctx()
    wrap = ctx.subs_check(lhs, rhs)
    wrap = zonk_wrapper(wrap)
    assert wrap == wp_fun(poly_arg, WpTyApp(INT), WP_HOLE)


def test_subs_check_deep_skol_prenex_fwd():
    a = _bound("a")
    b = _bound("b")
    lhs = TyForall([a], TyForall([b], TyFun(a, TyFun(b, b))))
    rhs = TyForall([a], TyFun(a, TyForall([b], TyFun(b, b))))

    ctx = _ctx()
    wrap = ctx.subs_check(lhs, rhs)
    wrap = zonk_wrapper(wrap)
    # Wrapper is a composition of skolemization, subsumption, and instantiation
    assert isinstance(wrap, WpCompose)


def test_subs_check_deep_skol_prenex_rev():
    a = _bound("a")
    b = _bound("b")
    lhs = TyForall([a], TyFun(a, TyForall([b], TyFun(b, b))))
    rhs = TyForall([a], TyForall([b], TyFun(a, TyFun(b, b))))

    ctx = _ctx()
    wrap = ctx.subs_check(lhs, rhs)
    wrap = zonk_wrapper(wrap)
    # Wrapper is a composition of skolemization, subsumption, and instantiation
    assert isinstance(wrap, WpCompose)


# =============================================================================
# Instantiation Tests
# =============================================================================


def test_instantiate_forall():
    a = _bound("a")
    sigma = TyForall([a], a)

    ctx = _ctx()
    ty, wrap = ctx.instantiate(sigma)
    assert isinstance(wrap, WpTyApp)
    assert zonk_type(ty) == INT or isinstance(zonk_type(ty), MetaTv)


def test_instantiate_mono():
    ctx = _ctx()
    ty, wrap = ctx.instantiate(INT)
    assert ty == INT
    assert wrap == WP_HOLE


def test_inst_check_contra():
    from systemf.elab3.typecheck_expr import TypeChecker
    from systemf.elab3.types.tc import Check

    class FakeTcCtx(TypeChecker):
        def __init__(self):
            super().__init__(FakeCtx(), "PuttingTest", FakeNameGen())

        def lookup_gbl(self, name):
            raise KeyError(name)

    ctx = FakeTcCtx()
    a = _bound("a")
    ty = TyForall([a], TyFun(a, a))
    ty2 = TyFun(INT, INT)

    wrap = ctx.inst(ty, Check(ty2))
    wrap = zonk_wrapper(wrap)
    assert wrap == WpTyApp(INT)
