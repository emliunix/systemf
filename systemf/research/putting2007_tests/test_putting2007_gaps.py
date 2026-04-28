r"""Regression tests exposing gaps between the Python implementation and the
Putting 2007 paper ("Practical Type Inference for Arbitrary-Rank Types").

Each test class targets one specific gap identified in the review.
Tests are expected to fail until the corresponding gap is fixed.

Gap summary
-----------
1. Missing ``inferSigma`` (GEN1) – let-bound polymorphism
2. Missing ``checkSigma`` (GEN2) – checking mode should skolemise, not instantiate
3. Missing ``instSigma`` dispatch – VAR rule doesn't instantiate in synthesis mode
4. Skolem escape check is stubbed out
5. Skolem variables are plain ``TypeVar``\s (not rigid)
6. ``TypeForall`` unification ignores bound variable names
"""

import pytest

from systemf.core import ast as core
from systemf.core.types import (
    Type,
    TypeVar,
    TypeArrow,
    TypeForall,
    TypeConstructor,
)
from systemf.surface.types import (
    SurfaceLit,
    ScopedVar,
    ScopedAbs,
    SurfaceApp,
    SurfaceTypeAbs,
    SurfaceTypeApp,
    SurfaceLet,
    SurfaceAnn,
    SurfaceConstructor,
    SurfaceCase,
    SurfaceBranch,
    SurfacePattern,
    SurfaceIf,
    SurfaceTypeVar,
    SurfaceTypeArrow,
    SurfaceTypeConstructor,
    SurfaceTypeForall,
    GlobalVar,
    ValBind,
)
from systemf.surface.inference import (
    BidiInference,
    TypeContext,
    TMeta,
)
from systemf.surface.inference.errors import (
    TypeError,
    TypeMismatchError,
    UnificationError,
)
from systemf.surface.inference.unification import Substitution, unify
from systemf.utils.location import Location

DUMMY_LOC = Location(line=1, column=1, file="test.py")


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def elab():
    return BidiInference()


@pytest.fixture
def empty_ctx():
    return TypeContext()


# ============================================================================
# Gap 1 – Missing inferSigma / GEN1 (let-bound polymorphism)
# ============================================================================
#
# Paper rule LET (Figure 8):
#
#     Γ ⊢^poly_⇑ u : σ     Γ, x:σ ⊢δ t : ρ
#     ─────────────────────────────────────────
#     Γ ⊢δ  let x = u in t : ρ
#
# The RHS is inferred with inferSigma which calls GEN1 to generalise.
# Without it the let-bound variable gets a monomorphic (meta) type and
# cannot be used at two different types in the body.
# ============================================================================


class TestGap1_LetPolymorphism:
    r"""GEN1: Let-bound values must be generalised.

    The classic test for let-polymorphism is:

        let id = \x -> x in (id 3, id True)

    ``id`` should get type ``∀a. a → a`` via GEN1 so that ``id 3`` and
    ``id True`` both succeed.  Without generalisation ``id`` has type
    ``_meta → _meta`` and the second usage fails with a unification error.
    """

    def test_let_poly_used_at_two_types(self, elab, empty_ctx):
        r"""let id = \x -> x in (id 3, id True)  -- must generalise id."""
        # id = \x -> x
        id_body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        id_fn = ScopedAbs(var_name="x", var_type=None, body=id_body, location=DUMMY_LOC)

        # id 3  (in inner let RHS, before unused is bound, id is at index 0)
        id_var_0 = ScopedVar(index=0, debug_name="id", location=DUMMY_LOC)
        app_int = SurfaceApp(
            func=id_var_0,
            arg=SurfaceLit(prim_type="Int", value=3, location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        # id True  (in inner let body, after unused is bound at index 0, id is at index 1)
        id_var_1 = ScopedVar(index=1, debug_name="id", location=DUMMY_LOC)
        app_bool = SurfaceApp(
            func=id_var_1,
            arg=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        # Use a tuple-like encoding: we just need both applications to
        # succeed.  The simplest body that requires both monomorphic results
        # is a pair constructor, but we can just use a nested let to force
        # both usages:
        #
        #   let id = \x -> x in let _ = id 3 in id True
        #
        # The inner let forces id to be used at Int; the outer body forces
        # id to be used at Bool (via the True constructor).

        ctx_with_bool = TypeContext(
            constructors={
                "True": TypeConstructor("Bool", []),
                "False": TypeConstructor("Bool", []),
            }
        )

        inner_let = SurfaceLet(
            bindings=[ValBind(name="unused", type_ann=None, value=app_int, location=DUMMY_LOC)],
            body=app_bool,
            location=DUMMY_LOC,
        )

        outer_let = SurfaceLet(
            bindings=[ValBind(name="id", type_ann=None, value=id_fn, location=DUMMY_LOC)],
            body=inner_let,
            location=DUMMY_LOC,
        )

        # This should succeed – id should be generalised to ∀a. a → a
        # Use typecheck() for end-to-end type inference (resolves all metas)
        core_term, ty = elab.typecheck(outer_let, ctx_with_bool)

        # Result type should be Bool (the type of `id True`)
        # After generalization, if no free vars, we get ForAll [] Bool
        if isinstance(ty, TypeForall):
            ty = ty.body  # Unwrap the forall
        assert isinstance(ty, TypeConstructor)
        assert ty.name == "Bool"

    def test_let_generalises_identity_type(self, elab, empty_ctx):
        r"""let id = \x -> x in id  -- id should have type ∀a. a→a, not _m→_m."""
        id_body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        id_fn = ScopedAbs(var_name="x", var_type=None, body=id_body, location=DUMMY_LOC)

        # Body is just `id`
        id_ref = ScopedVar(index=0, debug_name="id", location=DUMMY_LOC)

        let_term = SurfaceLet(
            bindings=[ValBind(name="id", type_ann=None, value=id_fn, location=DUMMY_LOC)],
            body=id_ref,
            location=DUMMY_LOC,
        )

        # Use typecheck for top-level generalization (like Haskell's typecheck)
        core_term, ty = elab.typecheck(let_term, empty_ctx)

        # The result should be a generalised forall type, not a bare meta arrow
        assert isinstance(ty, TypeForall), (
            f"Expected ∀a. a→a but got {ty} — GEN1 generalisation is missing"
        )


# ============================================================================
# Gap 2 – Missing checkSigma / GEN2 (checking mode skolemises, not instantiates)
# ============================================================================
#
# Paper rule GEN2 (Figure 8):
#
#     pr(σ) = ∀ā.ρ    ā ∉ ftv(Γ)    Γ ⊢⇓ t : ρ
#     ───────────────────────────────────────────
#     Γ ⊢⇓^poly t : σ
#
# Current check() against TypeForall _instantiates_ (replaces ∀-bound vars
# with flexible metas) instead of _skolemising_ (rigid constants).
# Instantiation makes the check trivially succeed because the metas unify
# with anything.
# ============================================================================


class TestGap2_CheckSigmaSkolemise:
    r"""GEN2: Checking mode must skolemise, not instantiate.

    Checking ``\x -> 42`` against ``∀a. a → a`` should **fail** because the
    body returns ``Int``, not ``a``.  With the current (buggy) instantiation
    the ∀-bound ``a`` becomes a meta ``_m`` which happily unifies with
    ``Int``, making the check pass incorrectly.
    """

    def test_check_lambda_against_forall_should_reject(self, elab, empty_ctx):
        r"""check (\x -> 42) : ∀a. a → a  -- MUST fail."""
        body = SurfaceLit(prim_type="Int", value=42, location=DUMMY_LOC)
        lam = ScopedAbs(var_name="x", var_type=None, body=body, location=DUMMY_LOC)

        # Expected type: ∀a. a → a
        forall_id = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        # This MUST raise – the body always returns Int, not `a`
        with pytest.raises((TypeMismatchError, UnificationError, TypeError)):
            elab.check(lam, forall_id, empty_ctx)

    def test_check_const_against_id_type_should_reject(self, elab, empty_ctx):
        r"""check (\x -> \y -> x) : ∀a. a → a  -- MUST fail.

        \x -> \y -> x  has type  a → b → a  which is NOT  a → a.
        """
        # \y -> x  (y at index 0, x at index 1)
        inner = ScopedAbs(
            var_name="y",
            var_type=None,
            body=ScopedVar(index=1, debug_name="x", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )
        lam = ScopedAbs(var_name="x", var_type=None, body=inner, location=DUMMY_LOC)

        forall_id = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        with pytest.raises((TypeMismatchError, UnificationError, TypeError)):
            elab.check(lam, forall_id, empty_ctx)

    def test_check_valid_id_against_forall_should_accept(self, elab, empty_ctx):
        r"""check (\x -> x) : ∀a. a → a  -- MUST succeed.

        This is the positive case: the identity function genuinely has the
        polymorphic type.  After fixing GEN2 this should still pass.
        """
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        lam = ScopedAbs(var_name="x", var_type=None, body=body, location=DUMMY_LOC)

        forall_id = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        # This should succeed – \x -> x genuinely has type ∀a. a → a
        core_term = elab.check(lam, forall_id, empty_ctx)
        assert isinstance(core_term, core.Abs)


# ============================================================================
# Gap 3 – Missing instSigma dispatch (VAR rule doesn't instantiate)
# ============================================================================
#
# Paper rule VAR (Figure 8):
#
#     ⊢^inst_δ σ ≤ ρ
#     ───────────────────────
#     Γ, (x:σ) ⊢δ x : ρ
#
# In synthesis mode (INST1), the σ must be instantiated to a ρ (no top-level
# forall).  The current infer() returns the sigma as-is.
# ============================================================================


class TestGap3_VarInstantiation:
    r"""VAR + INST1: Variables with ∀-types must be instantiated in synthesis mode.

    If ``x : ∀a. a → a`` is in context, ``infer(x)`` should return a rho type
    like ``_m → _m`` (instantiated), not ``∀a. a → a`` (sigma).  Returning a
    sigma causes problems downstream — e.g. application expects an arrow at
    the top level, not a forall.
    """

    def test_infer_var_instantiates_forall(self, elab):
        r"""infer(x) where x : ∀a. a→a  should return _m→_m, not ∀a. a→a."""
        poly_type = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))
        ctx = TypeContext(term_types=[poly_type])

        x = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        # Use infer to test internal inference behavior (VAR instantiation)
        _core_term, ty = elab.infer(x, ctx)

        # The returned type must be a rho (no top-level forall)
        assert not isinstance(ty, TypeForall), (
            f"Expected instantiated rho type but got sigma: {ty} — "
            f"VAR rule is missing instSigma / INST1"
        )
        # It should be an arrow with meta variables
        assert isinstance(ty, TypeArrow), f"Expected _m → _m but got {ty}"

    def test_infer_poly_var_applied_to_int(self, elab):
        r"""(\f -> f 3) applied to a context where f : ∀a. a→a.

        The APP rule infers the function type and expects an arrow.  If the
        VAR rule returns ∀a. a→a (not instantiated), the APP rule must handle
        it.  Currently it does via a special-case match on TypeForall in APP,
        but the paper's clean design is: VAR instantiates, APP just sees arrow.

        This test checks the *general* path: a poly variable used in a
        non-application context (e.g. passed as an argument) where the
        APP-level special-case doesn't help.
        """
        # Context: g : (Int → Int) → Int
        #          x : ∀a. a → a
        # Term:    g x
        # For this to work, x must be instantiated to Int → Int
        # so it matches g's parameter type.

        g_type = TypeArrow(
            TypeArrow(TypeConstructor("Int", []), TypeConstructor("Int", [])),
            TypeConstructor("Int", []),
        )
        x_type = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        # x is at index 0, g is at index 1
        ctx = TypeContext(term_types=[x_type, g_type])

        g_var = ScopedVar(index=1, debug_name="g", location=DUMMY_LOC)
        x_var = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        app = SurfaceApp(func=g_var, arg=x_var, location=DUMMY_LOC)

        # g x should typecheck: x instantiated to Int→Int, result is Int
        core_term, ty = elab.infer(app, ctx)
        assert isinstance(ty, TypeConstructor)
        assert ty.name == "Int"


# ============================================================================
# Gap 4 – Skolem escape check is stubbed out
# ============================================================================
#
# In _subs_check the escape check is:
#
#     if skol_tvs:
#         pass   # ← stubbed out
#
# The paper requires:
#
#     esc_tvs <- getFreeTyVars [sigma1, sigma2]
#     let bad_tvs = filter (`elem` esc_tvs) skol_tvs
#     check (null bad_tvs) ...
#
# Without the escape check, subsumption accepts types that aren't
# polymorphic enough.
# ============================================================================


class TestGap4_SkolemEscapeCheck:
    r"""Subsumption must reject types that aren't polymorphic enough.

    ``Int → Int  ≤  ∀a. a → a``  should **fail** because ``Int → Int``
    is not as polymorphic as ``∀a. a → a``.  Skolemising the RHS gives
    ``skol → skol``; checking ``Int → Int ≤ skol → skol`` unifies
    ``Int = skol`` which causes ``skol`` to escape.
    """

    def test_mono_not_subsumes_poly(self, elab, empty_ctx):
        r"""Int → Int  ≤  ∀a. a → a  -- MUST fail (not polymorphic enough)."""
        mono = TypeArrow(TypeConstructor("Int", []), TypeConstructor("Int", []))
        poly = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        with pytest.raises((TypeMismatchError, UnificationError, TypeError)):
            elab._subs_check(mono, poly, DUMMY_LOC)

    def test_subsumption_rejects_wrong_direction(self, elab, empty_ctx):
        r"""∀a. a → Int  ≤  ∀a. a → a  -- MUST fail.

        The LHS always returns Int; the RHS requires returning the same
        type as the input.  This is not ``at least as polymorphic``.
        """
        lhs = TypeForall("a", TypeArrow(TypeVar("a"), TypeConstructor("Int", [])))
        rhs = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        with pytest.raises((TypeMismatchError, UnificationError, TypeError)):
            elab._subs_check(lhs, rhs, DUMMY_LOC)

    def test_poly_subsumes_mono_should_succeed(self, elab, empty_ctx):
        r"""∀a. a → a  ≤  Int → Int  -- should succeed (more poly is OK)."""
        poly = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))
        mono = TypeArrow(TypeConstructor("Int", []), TypeConstructor("Int", []))

        # This direction should always work
        elab._subs_check(poly, mono, DUMMY_LOC)


# ============================================================================
# Gap 5 – Skolem variables are plain TypeVars (not rigid)
# ============================================================================
#
# The paper creates actual SkolemTv values that cannot be unified with
# anything except themselves.  The Python _skolemise creates
# TypeVar("_skol_a_0") which is a regular type variable that participates
# in unification — same-name vars unify.
# ============================================================================


class TestGap5_RigidSkolems:
    r"""Skolem constants must be rigid — they must not unify with other types.

    Two independently skolemised types should produce *distinct* skolem
    constants.  If they are plain ``TypeVar``\s with the same name they
    can accidentally unify.
    """

    def test_distinct_skolemisations_dont_unify(self, elab, empty_ctx):
        r"""Two independent skolemisations of ∀a. a→a must produce distinct skolems.

        If both produce TypeVar("_skol_a_0") they will unify, which is wrong.
        """
        ty = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        skol1, rho1 = elab._skolemise(ty)
        skol2, rho2 = elab._skolemise(ty)

        # The skolem names must be different so they can't unify
        assert skol1 != skol2, (
            f"Two independent skolemisations produced identical skolem names: "
            f"{skol1} — they will accidentally unify"
        )

    def test_skolem_does_not_unify_with_concrete_type(self, elab, empty_ctx):
        r"""A skolem constant must not unify with a concrete type like Int.

        Paper: SkolemTv is rigid; unify(SkolemTv, Int) must fail.
        Current: _skol_a_0 is a TypeVar; unify(TypeVar, Int) fails with
        "cannot unify" BUT only because TypeVar("_skol_a_0") ≠ Int.
        The real issue is that unify(TypeVar("x"), TypeVar("x")) succeeds
        even when one of them is supposed to be a skolem.
        """
        ty = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))
        _skols, rho = elab._skolemise(ty)

        # rho is  _skol_a_0 → _skol_a_0
        # Extract the skolem type from the arrow
        assert isinstance(rho, TypeArrow)
        skolem_type = rho.arg  # TypeVar("_skol_a_0")

        # A skolem must not unify with a meta variable (flexible).
        # In the paper, unify(SkolemTv, MetaTv) is an error because SkolemTv
        # is rigid.  In the current impl, since the skolem is just a TypeVar,
        # a meta CAN be unified with it (meta unifies with anything).
        meta = TMeta.fresh("test")
        subst = Substitution.empty()

        # This should FAIL — skolems are rigid
        with pytest.raises((UnificationError, TypeError)):
            new_subst = unify(skolem_type, meta, subst, DUMMY_LOC)
            # If unify succeeds, the skolem was treated as a unification target
            # which is wrong.  Even if it "succeeds", the result is unsound.
            # Force evaluation to detect the problem:
            resolved = new_subst.apply_to_type(meta)
            # If resolved is the skolem, that means the meta was unified with
            # a rigid variable — unsound.
            pytest.fail(
                f"Skolem {skolem_type} was unified with meta {meta} "
                f"(resolved to {resolved}).  Skolems must be rigid."
            )


# ============================================================================
# Gap 6 – TypeForall unification ignores bound variable names
# ============================================================================
#
# The current unify() for TypeForall(var1, body1) vs TypeForall(var2, body2)
# when var1 ≠ var2 just unifies the bodies without renaming.  This means
# ∀a. a→a  and  ∀b. b→b  fail to unify because TypeVar("a") ≠ TypeVar("b").
#
# The paper never unifies forall types directly — it always goes through
# instantiation or subsumption.  But if the implementation does have a path
# that unifies foralls (e.g. the fall-through case in check()), it must
# handle alpha-equivalence.
# ============================================================================


class TestGap6_ForallUnification:
    r"""TypeForall unification must handle alpha-equivalence.

    ``∀a. a → a``  and  ``∀b. b → b``  are alpha-equivalent and must unify
    (or, better, the system should never attempt to unify foralls directly
    and instead route through instantiation/subsumption).
    """

    def test_alpha_equivalent_foralls_unify(self):
        r"""∀a. a → a  should unify with  ∀b. b → b  (alpha-equivalent)."""
        ty1 = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))
        ty2 = TypeForall("b", TypeArrow(TypeVar("b"), TypeVar("b")))

        subst = Substitution.empty()
        # This should succeed — the types are alpha-equivalent
        result_subst = unify(ty1, ty2, subst, DUMMY_LOC)
        # And the substitution should be empty (no new constraints needed)
        assert len(result_subst.mapping) == 0, (
            f"Alpha-equivalent types should unify without new constraints, "
            f"but got substitution: {result_subst}"
        )

    def test_non_alpha_equivalent_foralls_dont_unify(self):
        r"""∀a. a → a  should NOT unify with  ∀a. a → Int  (genuinely different)."""
        ty1 = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))
        ty2 = TypeForall("a", TypeArrow(TypeVar("a"), TypeConstructor("Int", [])))

        subst = Substitution.empty()
        with pytest.raises(UnificationError):
            unify(ty1, ty2, subst, DUMMY_LOC)

    def test_check_against_alpha_renamed_forall(self, elab, empty_ctx):
        r"""check (\x -> x) : ∀b. b → b  should succeed.

        This combines Gap 2 (check against forall) with Gap 6 (alpha-equiv).
        After fixing GEN2, checking \x -> x against ∀b. b → b should work
        regardless of the bound variable name.
        """
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        lam = ScopedAbs(var_name="x", var_type=None, body=body, location=DUMMY_LOC)

        # Use "b" instead of "a" to exercise alpha-equivalence
        forall_id = TypeForall("b", TypeArrow(TypeVar("b"), TypeVar("b")))

        core_term = elab.check(lam, forall_id, empty_ctx)
        assert isinstance(core_term, core.Abs)


# ============================================================================
# Combined / integration tests
# ============================================================================


class TestCombinedGaps:
    r"""Tests that exercise multiple gaps simultaneously.

    These represent realistic programs from the paper that fail due to
    the combination of missing features.
    """

    def test_paper_example_let_poly_application(self, elab, empty_ctx):
        r"""Paper Section 4.3 example:

            let id = \x -> x in id id

        The inner ``id`` must be generalised (Gap 1: GEN1), and the outer
        ``id`` must be instantiated from ``∀a. a→a`` to ``(b→b) → (b→b)``
        (Gap 3: INST1) to accept ``id`` as argument.
        """
        id_body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        id_fn = ScopedAbs(var_name="x", var_type=None, body=id_body, location=DUMMY_LOC)

        # Body: id id  (both at index 0 in the let scope)
        id_ref_fn = ScopedVar(index=0, debug_name="id", location=DUMMY_LOC)
        id_ref_arg = ScopedVar(index=0, debug_name="id", location=DUMMY_LOC)
        body = SurfaceApp(func=id_ref_fn, arg=id_ref_arg, location=DUMMY_LOC)

        let_term = SurfaceLet(
            bindings=[ValBind(name="id", type_ann=None, value=id_fn, location=DUMMY_LOC)],
            body=body,
            location=DUMMY_LOC,
        )

        # Use typecheck for top-level generalization
        core_term, ty = elab.typecheck(let_term, empty_ctx)

        # Result should be the polymorphic identity type (generalised)
        # Haskell reference: ∀a. a → a
        assert isinstance(ty, TypeForall), f"Expected polymorphic type but got {ty}"

    def test_checking_wrong_function_against_poly_annotation(self, elab, empty_ctx):
        r"""((\x -> 42) :: ∀a. a → a) should FAIL.

        The annotation claims the function is the polymorphic identity,
        but the body always returns 42.  This requires:
        - Gap 2 (GEN2): check mode must skolemise
        - Gap 4: skolem escape check must catch the Int = skol failure
        """
        body = SurfaceLit(prim_type="Int", value=42, location=DUMMY_LOC)
        lam = ScopedAbs(var_name="x", var_type=None, body=body, location=DUMMY_LOC)

        ann_type = SurfaceTypeForall(
            var="a",
            body=SurfaceTypeArrow(
                arg=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                ret=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
            location=DUMMY_LOC,
        )

        ann_term = SurfaceAnn(term=lam, type=ann_type, location=DUMMY_LOC)

        with pytest.raises((TypeMismatchError, UnificationError, TypeError)):
            elab.infer(ann_term, empty_ctx)

    def test_paper_church_numerals(self, elab, empty_ctx):
        r"""Church-encoded zero and successor require let-polymorphism.

            let zero = \f -> \x -> x
            in let succ = \n -> \f -> \x -> f (n f x)
            in succ zero

        Both ``zero`` and ``succ`` must be generalised.
        """
        # zero = \f -> \x -> x
        x_var = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        zero_inner = ScopedAbs(var_name="x", var_type=None, body=x_var, location=DUMMY_LOC)
        zero_fn = ScopedAbs(var_name="f", var_type=None, body=zero_inner, location=DUMMY_LOC)

        # succ = \n -> \f -> \x -> f (n f x)
        # indices: x=0, f=1, n=2
        x_ref = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        f_ref_outer = ScopedVar(index=1, debug_name="f", location=DUMMY_LOC)
        f_ref_inner = ScopedVar(index=1, debug_name="f", location=DUMMY_LOC)
        n_ref = ScopedVar(index=2, debug_name="n", location=DUMMY_LOC)

        # n f
        n_f = SurfaceApp(func=n_ref, arg=f_ref_inner, location=DUMMY_LOC)
        # n f x
        n_f_x = SurfaceApp(func=n_f, arg=x_ref, location=DUMMY_LOC)
        # f (n f x)
        f_nfx = SurfaceApp(func=f_ref_outer, arg=n_f_x, location=DUMMY_LOC)

        succ_x = ScopedAbs(var_name="x", var_type=None, body=f_nfx, location=DUMMY_LOC)
        succ_f = ScopedAbs(var_name="f", var_type=None, body=succ_x, location=DUMMY_LOC)
        succ_fn = ScopedAbs(var_name="n", var_type=None, body=succ_f, location=DUMMY_LOC)

        # body: succ zero  (succ at index 0, zero at index 1 in nested let scope)
        succ_ref = ScopedVar(index=0, debug_name="succ", location=DUMMY_LOC)
        zero_ref = ScopedVar(index=1, debug_name="zero", location=DUMMY_LOC)
        body = SurfaceApp(func=succ_ref, arg=zero_ref, location=DUMMY_LOC)

        inner_let = SurfaceLet(
            bindings=[ValBind(name="succ", type_ann=None, value=succ_fn, location=DUMMY_LOC)],
            body=body,
            location=DUMMY_LOC,
        )

        outer_let = SurfaceLet(
            bindings=[ValBind(name="zero", type_ann=None, value=zero_fn, location=DUMMY_LOC)],
            body=inner_let,
            location=DUMMY_LOC,
        )

        # Use typecheck() for end-to-end type inference with generalization
        core_term, ty = elab.typecheck(outer_let, empty_ctx)

        # succ zero should have a polymorphic type (generalised Church numeral)
        # Type should be ∀a.∀b.(b -> a) -> b -> a
        assert isinstance(ty, TypeForall), f"Expected polymorphic type but got {ty}"
