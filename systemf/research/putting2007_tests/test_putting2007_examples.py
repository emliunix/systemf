r"""Test cases extracted from Putting2007 paper.

Tests validating System F against Peyton Jones et al.'s
"Practical Type Inference for Arbitrary-Rank Types" (JFP 2007).

These tests ensure System F correctly implements:
- Rank-N polymorphism (Section 3.1)
- Bidirectional type checking (Section 4.7)
- Subsumption with contra/co-variance (Section 3.3)
- Pattern matching (Section 7.2-7.3)
- Multi-branch constructs (Section 7.1)

Reference: docs/research/systemf-putting2007-validation.md
"""

import pytest

from systemf.core import ast as core
from systemf.core.types import (
    Type,
    TypeVar,
    TypeArrow,
    TypeForall,
    TypeConstructor,
    PrimitiveType,
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
    SurfaceTuple,
    SurfaceOp,
    SurfaceTypeVar,
    SurfaceTypeArrow,
    SurfaceTypeConstructor,
    SurfaceTypeForall,
    SurfaceVarPattern,
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
from systemf.utils.location import Location


# Create a dummy location for tests
DUMMY_LOC = Location(line=1, column=1, file="test.py")


# =============================================================================
# Paper Section 1: Introduction Examples
# =============================================================================


class TestIntroductionExample:
    r"""Example from Paper Section 1 (page 3).

    The motivating example showing higher-rank types:
    ```haskell
    foo :: ([Bool], [Char])
    foo = let
        f :: (forall a. [a] -> [a]) -> ([Bool], [Char])
        f x = (x [True, False], x ['a','b'])
        in
        f reverse
    ```
    """

    def test_rank2_function_argument(self):
        r"""Test that rank-2 function arguments work.

        The key insight is that x can be used polymorphically
        within f's body, despite being a lambda-bound parameter.
        """
        # This is a simplified version - full version requires list types
        # For now, test the core mechanism: passing polymorphic function

        # Build: f = λx:(∀a. a→a). (x 3, x True)
        # where x has type ∀a. a→a (rank-2 in argument position)

        elab = BidiInference()
        ctx = TypeContext()

        # Type: ∀a. a → a (polymorphic identity)
        id_type = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        # Lambda with rank-2 argument type
        # \x:(forall a. a->a) -> x
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        surface_id_type = SurfaceTypeForall(
            var="a",
            body=SurfaceTypeArrow(
                arg=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                ret=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
            location=DUMMY_LOC,
        )

        abs_term = ScopedAbs(var_name="x", var_type=surface_id_type, body=body, location=DUMMY_LOC)

        # This should typecheck with rank-2 type
        core_term, ty = elab.infer(abs_term, ctx)

        assert isinstance(ty, TypeArrow)
        # The argument type should be the polymorphic type
        arg_type = ty.arg
        assert isinstance(arg_type, TypeForall)


# =============================================================================
# Paper Section 3.1: Higher-Rank Types
# =============================================================================


class TestRankNTypes:
    r"""Tests for rank-N polymorphism.

    Rank classification (page 8):
    - Rank 0: Int -> Int (monomorphic)
    - Rank 1: forall a. a -> a (polymorphic only at top)
    - Rank 2: (forall a. a -> a) -> Int (polymorphic in argument)
    - Rank N: Arbitrary nesting
    """

    def test_rank0_monomorphic(self, elab, empty_ctx):
        r"""Rank 0: Int -> Int"""
        # \x:Int -> x
        int_type = SurfaceTypeConstructor(name="Int", args=[], location=DUMMY_LOC)
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        abs_term = ScopedAbs(var_name="x", var_type=int_type, body=body, location=DUMMY_LOC)

        core_term, ty = elab.infer(abs_term, empty_ctx)

        assert isinstance(ty, TypeArrow)
        assert isinstance(ty.arg, TypeConstructor)
        assert ty.arg.name == "Int"

    def test_rank1_polymorphic(self, elab, empty_ctx):
        r"""Rank 1: forall a. a -> a"""
        # /\a. \x:a -> x
        type_var = SurfaceTypeVar(name="a", location=DUMMY_LOC)
        inner_body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        inner_abs = ScopedAbs(var_name="x", var_type=type_var, body=inner_body, location=DUMMY_LOC)
        type_abs = SurfaceTypeAbs(var="a", body=inner_abs, location=DUMMY_LOC)

        core_term, ty = elab.infer(type_abs, empty_ctx)

        assert isinstance(ty, TypeForall)
        assert ty.var == "a"

    def test_rank2_function_argument(self, elab, empty_ctx):
        r"""Rank 2: (forall a. a -> a) -> Int"""
        # \f:(forall a. a->a) -> f @Int 3
        # Build the type: (forall a. a->a) -> Int
        id_type = SurfaceTypeForall(
            var="a",
            body=SurfaceTypeArrow(
                arg=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                ret=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
            location=DUMMY_LOC,
        )

        # f 3 (applying f to 3)
        arg = SurfaceLit(prim_type="Int", value=3, location=DUMMY_LOC)
        app = SurfaceApp(
            func=ScopedVar(index=0, debug_name="f", location=DUMMY_LOC), arg=arg, location=DUMMY_LOC
        )

        abs_term = ScopedAbs(var_name="f", var_type=id_type, body=app, location=DUMMY_LOC)

        core_term, ty = elab.infer(abs_term, empty_ctx)

        assert isinstance(ty, TypeArrow)
        # First arg should be polymorphic
        assert isinstance(ty.arg, TypeForall)


# =============================================================================
# Paper Section 3.3: Subsumption
# =============================================================================


class TestSubsumption:
    r"""Tests for subsumption relation.

    Key insight (page 9): An argument is acceptable if its type is
    "more polymorphic than" the function's parameter type.

    Examples from paper:
    k  :: forall a b. a -> b -> b
    f1 :: (Int -> Int -> Int) -> Int
    f2 :: (forall x. x -> x -> x) -> Int

    f1 k  -- OK (instantiate a,b to Int)
    f2 k  -- OK (k is more polymorphic)
    """

    def test_basic_instantiation(self, elab, empty_ctx):
        r"""k :: forall a b. a -> b -> b used where Int -> Int -> Int expected."""
        # Build: (\f:(Int->Int->Int). 42) (\x.\y.y)
        # where \x.\y.y has type forall a b. a -> b -> b

        # First, the polymorphic function: \x.\y.y
        y_var = ScopedVar(index=0, debug_name="y", location=DUMMY_LOC)  # y is at index 0
        x_var = ScopedVar(index=1, debug_name="x", location=DUMMY_LOC)  # x is at index 1
        inner_abs = ScopedAbs(var_name="y", var_type=None, body=y_var, location=DUMMY_LOC)
        poly_fn = ScopedAbs(var_name="x", var_type=None, body=inner_abs, location=DUMMY_LOC)

        # The function expecting monomorphic type: \f:(Int->Int->Int). 42
        int_type = SurfaceTypeConstructor(name="Int", args=[], location=DUMMY_LOC)
        int_arrow = SurfaceTypeArrow(arg=int_type, ret=int_type, param_doc=None, location=DUMMY_LOC)
        int_arrow2 = SurfaceTypeArrow(arg=int_type, ret=int_arrow, param_doc=None, location=DUMMY_LOC)

        body = SurfaceLit(prim_type="Int", value=42, location=DUMMY_LOC)
        abs_term = ScopedAbs(var_name="f", var_type=int_arrow2, body=body, location=DUMMY_LOC)

        # Application
        app = SurfaceApp(func=abs_term, arg=poly_fn, location=DUMMY_LOC)

        core_term, ty = elab.infer(app, empty_ctx)

        assert ty.name == "Int"

    def test_higher_rank_subsumption(self, elab, empty_ctx):
        r"""Test subsumption with higher-rank types."""
        # g :: ((forall b. [b] -> [b]) -> Int) -> Int
        # k1 :: (forall a. a -> a) -> Int  -- More polymorphic, should work
        # k2 :: ([Int] -> [Int]) -> Int    -- Less polymorphic, should fail

        # This tests contra/co-variance in subsumption
        # For now, test basic instantiation works
        pass  # Complex test - TODO


# =============================================================================
# Paper Section 4.7: Bidirectional Type Checking
# =============================================================================


class TestBidirectionalChecking:
    r"""Tests for bidirectional type checking rules (Figure 8).

    Key rules:
    - ABS1: Lambda inference (fresh meta for parameter)
    - ABS2: Lambda checking (against arrow type)
    - AABS1: Annotated lambda inference
    - AABS2: Annotated lambda checking
    - APP: Application (infer function, check arg)
    """

    def test_abs1_inference_mode(self, elab, empty_ctx):
        r"""ABS1 rule: Infer lambda by creating fresh meta for parameter."""
        # \x -> x (inference mode)
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        abs_term = ScopedAbs(var_name="x", var_type=None, body=body, location=DUMMY_LOC)

        core_term, ty = elab.infer(abs_term, empty_ctx)

        assert isinstance(ty, TypeArrow)
        # Both arg and ret should be same meta (unified by body)
        assert isinstance(ty.arg, TMeta)
        assert isinstance(ty.ret, TMeta)

    def test_abs2_checking_mode(self, elab, empty_ctx):
        r"""ABS2 rule: Check lambda against known arrow type."""
        # Check (\x -> x) : Int -> Int
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        abs_term = ScopedAbs(var_name="x", var_type=None, body=body, location=DUMMY_LOC)

        expected = TypeArrow(TypeConstructor("Int", []), TypeConstructor("Int", []))
        core_term = elab.check(abs_term, expected, empty_ctx)

        assert isinstance(core_term, core.Abs)

    def test_aabs1_annotated_inference(self, elab, empty_ctx):
        r"""AABS1 rule: Infer annotated lambda."""
        # \x:Int -> x
        int_type = SurfaceTypeConstructor(name="Int", args=[], location=DUMMY_LOC)
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        abs_term = ScopedAbs(var_name="x", var_type=int_type, body=body, location=DUMMY_LOC)

        core_term, ty = elab.infer(abs_term, empty_ctx)

        assert isinstance(ty, TypeArrow)
        assert ty.arg.name == "Int"
        assert ty.ret.name == "Int"

    def test_aabs2_annotated_checking(self, elab, empty_ctx):
        r"""AABS2 rule: Check annotated lambda with subsumption."""
        # Check (\x:Int -> x) : (forall a. a -> a) -> (Int -> Int)
        # This requires subsumption check
        pass  # Complex - TODO

    def test_app_rule(self, elab, int_var_ctx):
        r"""APP rule: Infer function, check argument."""
        # (\x:Int -> x) 42
        int_type = SurfaceTypeConstructor(name="Int", args=[], location=DUMMY_LOC)
        body = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        abs_term = ScopedAbs(var_name="x", var_type=int_type, body=body, location=DUMMY_LOC)

        arg = SurfaceLit(prim_type="Int", value=42, location=DUMMY_LOC)
        app = SurfaceApp(func=abs_term, arg=arg, location=DUMMY_LOC)

        core_term, ty = elab.infer(app, int_var_ctx)

        assert ty.name == "Int"


# =============================================================================
# Paper Section 7.1: Multi-Branch Constructs
# =============================================================================


class TestMultiBranchConstructs:
    r"""Tests for if-then-else and case expressions.

    Paper describes 3 design choices for branch typing:
    1. Monotyped branches (Choice 1)
    2. Unification under mixed prefix (Choice 2)
    3. Two-way subsumption (Choice 3 - recommended)

    Key issue: Branches might have polymorphic (rho) types, not just mono.
    """

    def test_case_bool_monotyped_branches(self, elab, bool_ctx):
        r"""Case with Bool and monomorphic branches (equivalent to if-then-else)."""
        # case True of True -> 1 | False -> 0
        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="True", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=SurfaceLit(prim_type="Int", value=1, location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="False", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=SurfaceLit(prim_type="Int", value=0, location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
        ]

        case_term = SurfaceCase(
            scrutinee=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            branches=branches,
            location=DUMMY_LOC,
        )

        # Use typecheck to get resolved concrete type
        core_term, ty = elab.typecheck(case_term, bool_ctx)

        assert ty.name == "Int"

    def test_case_bool_polymorphic_branches(self, elab, bool_ctx):
        r"""Case with Bool and polymorphic branches - tests subsumption vs unification.

        Paper example (Section 7.1) adapted to case:
        case True of True -> (\x -> x) | False -> (\y -> y)
        -- Both branches: forall a. a -> a

        Choice 3 requires two-way subsumption:
        subsCheck rho1 rho2
        subsCheck rho2 rho1
        """
        # Both branches are identity functions
        id_branch = ScopedAbs(
            var_name="x",
            var_type=None,
            body=ScopedVar(index=0, debug_name="x", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="True", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=id_branch,
                location=DUMMY_LOC,
            ),
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="False", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=id_branch,
                location=DUMMY_LOC,
            ),
        ]

        case_term = SurfaceCase(
            scrutinee=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            branches=branches,
            location=DUMMY_LOC,
        )

        # Use typecheck to get resolved concrete type
        core_term, ty = elab.typecheck(case_term, bool_ctx)

        # Both branches should have the same polymorphic function type
        # Result is forall a. a -> a, so check that it's a forall containing an arrow
        assert isinstance(ty, TypeForall)
        assert isinstance(ty.body, TypeArrow)

    def test_case_basic(self, elab, empty_ctx):
        r"""Basic case expression."""
        ctx = TypeContext(
            constructors={"True": TypeConstructor("Bool", []), "False": TypeConstructor("Bool", [])}
        )

        # case True of True -> 1 | False -> 0
        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="True", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=SurfaceLit(prim_type="Int", value=1, location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="False", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=SurfaceLit(prim_type="Int", value=0, location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
        ]

        case_term = SurfaceCase(
            scrutinee=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            branches=branches,
            location=DUMMY_LOC,
        )

        core_term, ty = elab.infer(case_term, ctx)

        assert ty.name == "Int"

    def test_case_prenex_equality(self, elab, bool_ctx):
        r"""Test if with branches equal up to prenex conversion.

        Paper Section 7.1: Two types can be equivalent under prenex conversion
        even if they look different.

        Example:
        - Branch 1: forall a. Int -> a          (forall at top)
        - Branch 2: Int -> forall a. a          (forall inside)

        These should be equivalent because:
        pr(forall a. Int -> a) = forall a. Int -> a
        pr(Int -> forall a. a) = forall a. Int -> a

        Both skolemize to: Int -> _skol_a
        """
        # Branch 1: /\a. \x:Int -> x  (identity at type Int -> a)
        # Actually, we need branches that return functions
        # Let's use: \x. x (polymorphic) for both branches

        # Branch 1: identity function with inferred type forall a. a -> a
        branch1 = ScopedAbs(
            var_name="x",
            var_type=None,
            body=ScopedVar(index=0, debug_name="x", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        # Branch 2: same structure, should have same type
        branch2 = ScopedAbs(
            var_name="y",
            var_type=None,
            body=ScopedVar(index=0, debug_name="y", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="True", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch1,
                location=DUMMY_LOC,
            ),
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="False", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch2,
                location=DUMMY_LOC,
            ),
        ]

        case_term = SurfaceCase(
            scrutinee=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            branches=branches,
            location=DUMMY_LOC,
        )

        # Use typecheck to get resolved concrete type
        core_term, ty = elab.typecheck(case_term, bool_ctx)

        # Both branches should have the same polymorphic function type
        # Result is forall a. a -> a, so check that it's a forall containing an arrow
        assert isinstance(ty, TypeForall)
        assert isinstance(ty.body, TypeArrow)

    def test_case_different_polymorphic_branches(self, elab, bool_ctx):
        r"""Test if where branches have different but compatible polymorphic types.

        Branch 1: forall a. a -> a  (fully polymorphic identity)
        Branch 2: Int -> Int        (monomorphic identity)

        NOTE: These are NOT equivalent under two-way subsumption:
        - (forall a. a -> a) <= (Int -> Int)  [TRUE - instantiate a to Int]
        - (Int -> Int) <= (forall a. a -> a)  [FALSE - Int -> Int is not polymorphic]

        So this test expects a type error, validating that our subsumption is correct.
        """
        # Branch 1: polymorphic identity: /\a. \x:a -> x
        type_var = SurfaceTypeVar(name="a", location=DUMMY_LOC)
        inner_body1 = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        inner_abs1 = ScopedAbs(
            var_name="x", var_type=type_var, body=inner_body1, location=DUMMY_LOC
        )
        branch1 = SurfaceTypeAbs(var="a", body=inner_abs1, location=DUMMY_LOC)

        # Branch 2: monomorphic identity: \x:Int -> x
        int_type = SurfaceTypeConstructor(name="Int", args=[], location=DUMMY_LOC)
        inner_body2 = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        branch2 = ScopedAbs(var_name="x", var_type=int_type, body=inner_body2, location=DUMMY_LOC)

        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="True", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch1,
                location=DUMMY_LOC,
            ),
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="False", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch2,
                location=DUMMY_LOC,
            ),
        ]

        case_term = SurfaceCase(
            scrutinee=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            branches=branches,
            location=DUMMY_LOC,
        )

        # This should FAIL - the types are not equivalent under two-way subsumption
        with pytest.raises((TypeMismatchError, UnificationError)):
            elab.infer(case_term, bool_ctx)

    def test_case_equivalent_polymorphic_branches(self, elab, bool_ctx):
        r"""Test case where branches have equivalent polymorphic types via instantiation.

        Both branches: forall a. a -> a
        These should be equivalent (both ways subsumption succeeds).

        This tests that the two-way subsumption correctly identifies
        equivalent polymorphic types.
        """
        # Branch 1: polymorphic identity
        type_var1 = SurfaceTypeVar(name="a", location=DUMMY_LOC)
        inner_body1 = ScopedVar(index=0, debug_name="x", location=DUMMY_LOC)
        inner_abs1 = ScopedAbs(
            var_name="x", var_type=type_var1, body=inner_body1, location=DUMMY_LOC
        )
        branch1 = SurfaceTypeAbs(var="a", body=inner_abs1, location=DUMMY_LOC)

        # Branch 2: also polymorphic identity (same structure, different var name)
        type_var2 = SurfaceTypeVar(name="b", location=DUMMY_LOC)
        inner_body2 = ScopedVar(index=0, debug_name="y", location=DUMMY_LOC)
        inner_abs2 = ScopedAbs(
            var_name="y", var_type=type_var2, body=inner_body2, location=DUMMY_LOC
        )
        branch2 = SurfaceTypeAbs(var="b", body=inner_abs2, location=DUMMY_LOC)

        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="True", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch1,
                location=DUMMY_LOC,
            ),
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="False", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch2,
                location=DUMMY_LOC,
            ),
        ]

        case_term = SurfaceCase(
            scrutinee=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            branches=branches,
            location=DUMMY_LOC,
        )

        # This should succeed - both branches have equivalent polymorphic types
        # Use typecheck to get resolved concrete type
        core_term, ty = elab.typecheck(case_term, bool_ctx)

        # Result should be a polymorphic function type
        assert isinstance(ty, TypeForall)

    def test_case_contravariant_subsumption(self, elab, bool_ctx):
        r"""Test subsumption in contravariant position (function arguments).

        Paper Section 3.3: Subsumption is contravariant in function arguments.

        Case:
        - Branch 1: (Int -> Int) -> Int   (accepts less polymorphic arg)
        - Branch 2: (forall a. a -> a) -> Int  (accepts more polymorphic arg)

        Branch 1 is MORE polymorphic than Branch 2 in the argument position
        (contravariance), so subsumption should handle this.
        """
        # Skip this complex test for now - requires full subsumption implementation
        pass

    def test_case_with_subsumption(self, elab, empty_ctx):
        r"""Test case where branches have polymorphic types.

        case x of
            True -> \y -> y      (forall a. a -> a)
            False -> \z:Int -> z  (Int -> Int)

        Should typecheck with result type Int -> Int.
        """
        ctx = TypeContext(
            constructors={"True": TypeConstructor("Bool", []), "False": TypeConstructor("Bool", [])}
        )

        # Branch 1: polymorphic identity
        branch1 = ScopedAbs(
            var_name="y",
            var_type=None,
            body=ScopedVar(index=0, debug_name="y", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        # Branch 2: monomorphic identity
        int_type = SurfaceTypeConstructor(name="Int", args=[], location=DUMMY_LOC)
        branch2 = ScopedAbs(
            var_name="z",
            var_type=int_type,
            body=ScopedVar(index=0, debug_name="z", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="True", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch1,
                location=DUMMY_LOC,
            ),
            SurfaceBranch(
                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="False", location=DUMMY_LOC)], location=DUMMY_LOC),
                body=branch2,
                location=DUMMY_LOC,
            ),
        ]

        case_term = SurfaceCase(
            scrutinee=SurfaceConstructor(name="True", args=[], location=DUMMY_LOC),
            branches=branches,
            location=DUMMY_LOC,
        )

        core_term, ty = elab.infer(case_term, ctx)

        # Should be a function type
        assert isinstance(ty, TypeArrow)


# =============================================================================
# Paper Section 7.3: Higher-Ranked Data Constructors
# =============================================================================


class TestHigherRankConstructors:
    r"""Tests for pattern matching with higher-rank constructors.

    Paper example (page 62):
    ```haskell
    data T = MkT (forall a. a -> a)

    case x of
        MkT v -> (v 3, v True)  -- v: forall a. a -> a
    ```
    """

    def test_constructor_instantiation(self, elab, empty_ctx):
        r"""Constructor with higher-rank argument type."""
        # Constructor: MkT :: (forall a. a -> a) -> T
        # Application: MkT (\x -> x)

        ctx = TypeContext(
            constructors={
                "MkT": TypeArrow(
                    TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a"))), TypeConstructor("T", [])
                )
            }
        )

        # Build: MkT (\x -> x)
        id_fn = ScopedAbs(
            var_name="x",
            var_type=None,
            body=ScopedVar(index=0, debug_name="x", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        constr = SurfaceConstructor(name="MkT", args=[id_fn], location=DUMMY_LOC)

        core_term, ty = elab.infer(constr, ctx)

        assert isinstance(ty, TypeConstructor)
        assert ty.name == "T"

    def test_pattern_with_polymorphic_bind(self, elab, empty_ctx):
        r"""Pattern match binds polymorphic variable.

        Paper Section 7.3 (page 62):
        data T = MkT (forall a. a -> a)

        case x of
            MkT v -> (v 3, v True)  -- v: forall a. a -> a

        The key insight: pattern variable v is bound to the polymorphic type
        from the constructor argument, not instantiated to a monotype.
        """
        # First, construct a value of type T using MkT with id function
        id_fn = ScopedAbs(
            var_name="x",
            var_type=None,
            body=ScopedVar(index=0, debug_name="x", location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        # Create context with constructor: MkT :: (forall a. a -> a) -> T
        ctx = TypeContext(
            constructors={
                "MkT": TypeArrow(
                    TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a"))), TypeConstructor("T", [])
                )
            }
        )

        # scrut = MkT (\x -> x)  -- has type T
        scrut = SurfaceConstructor(name="MkT", args=[id_fn], location=DUMMY_LOC)

        # body = v 3  (applying the bound polymorphic variable)
        body = SurfaceApp(
            func=ScopedVar(index=0, debug_name="v", location=DUMMY_LOC),
            arg=SurfaceLit(prim_type="Int", value=3, location=DUMMY_LOC),
            location=DUMMY_LOC,
        )

        branches = [
            SurfaceBranch(
                pattern=SurfacePattern(
                    patterns=[
                        SurfaceVarPattern(name="MkT", location=DUMMY_LOC),
                        SurfacePattern(patterns=[SurfaceVarPattern(name="v", location=DUMMY_LOC)], location=DUMMY_LOC),
                    ],
                    location=DUMMY_LOC,
                ),
                body=body,
                location=DUMMY_LOC,
            )
        ]

        case_term = SurfaceCase(scrutinee=scrut, branches=branches, location=DUMMY_LOC)

        # Use typecheck to get resolved concrete type
        core_term, ty = elab.typecheck(case_term, ctx)

        # Result should be Int
        assert ty.name == "Int"


# =============================================================================
# Paper Section 2: Motivating Examples
# =============================================================================


class TestMotivatingExamples:
    r"""Tests for motivating examples from Section 2.

    Includes:
    - runST (encapsulation)
    - build (fusion)
    - gmapT (generic programming)
    """

    def test_runST_type(self, elab, empty_ctx):
        r"""runST :: forall a. (forall s. ST s a) -> a"""
        # Type: forall a. (forall s. ST s a) -> a
        # This is the classic rank-2 example

        # For now, just test the type structure exists
        pass  # Requires ST type - TODO

    def test_build_type(self, elab, empty_ctx):
        r"""build :: forall a. (forall b. (a -> b -> b) -> b -> b) -> [a]"""
        # Type: forall a. (forall b. (a -> b -> b) -> b -> b) -> [a]
        # Another rank-2 example from fusion
        pass  # Requires list type - TODO


# =============================================================================
# Comprehensive Integration Tests
# =============================================================================


class TestPutting2007Integration:
    r"""Integration tests combining multiple features.

    These tests validate that the type checker correctly handles
    the interactions between features described in the paper.
    """

    def test_nested_higher_rank(self, elab, empty_ctx):
        r"""Nested higher-rank types."""
        # ((forall a. a -> a) -> Int) -> Int
        # Rank 3 type

        # Build a function that takes a rank-2 function
        # and applies it to id

        # The type we want: (forall a. a->a) -> Int
        id_type = TypeForall("a", TypeArrow(TypeVar("a"), TypeVar("a")))

        # \f:(forall a. a->a). f @Int 3
        # This is rank-2 in argument position
        f_var = ScopedVar(index=0, debug_name="f", location=DUMMY_LOC)
        int_type = SurfaceTypeConstructor(name="Int", args=[], location=DUMMY_LOC)

        # f 3 (instantiating implicitly)
        arg = SurfaceLit(prim_type="Int", value=3, location=DUMMY_LOC)
        app = SurfaceApp(func=f_var, arg=arg, location=DUMMY_LOC)

        # Annotate f with polymorphic type
        surface_id_type = SurfaceTypeForall(
            var="a",
            body=SurfaceTypeArrow(
                arg=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                ret=SurfaceTypeVar(name="a", location=DUMMY_LOC),
                location=DUMMY_LOC,
            ),
            location=DUMMY_LOC,
        )

        abs_term = ScopedAbs(var_name="f", var_type=surface_id_type, body=app, location=DUMMY_LOC)

        # Use typecheck to get resolved concrete type
        core_term, ty = elab.typecheck(abs_term, empty_ctx)

        # Should have type (forall a. a->a) -> Int
        assert isinstance(ty, TypeArrow)
        assert isinstance(ty.arg, TypeForall)
        assert ty.ret.name == "Int"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def elab():
    r"""Create a fresh BidiInference for each test."""
    return BidiInference()


@pytest.fixture
def empty_ctx():
    r"""Create an empty TypeContext."""
    return TypeContext()


@pytest.fixture
def int_var_ctx():
    r"""Create a context with a variable of type Int."""
    return TypeContext(term_types=[TypeConstructor("Int", [])])


@pytest.fixture
def bool_ctx():
    r"""Create a context with Bool constructors (True, False)."""
    return TypeContext(
        constructors={
            "True": TypeConstructor("Bool", []),
            "False": TypeConstructor("Bool", []),
        }
    )
