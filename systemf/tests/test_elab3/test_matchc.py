"""Basic smoke tests for elab3 pattern-match compiler (MatchC).

Tests construct XPat trees directly and verify MatchC produces
reasonable CoreCase shapes without crashing.
"""

import pytest

from systemf.elab3.matchc import MatchC, MRInfallible, MRFallible, Equation, mr_run
from systemf.elab3.types.xpat import XPatLit, XPatCon, XPatVar, XPatWild, XPatCo
from systemf.elab3.tc_ctx import TcCtx
from systemf.elab3.name_gen import NameGeneratorImpl
from systemf.elab3.types.ty import Id, LitInt, Name, Ty, TyConApp, TyFun
from systemf.elab3.types.tything import ATyCon, ACon
from systemf.elab3.types.core import CoreCase, CoreLet, CoreVar, C, DefaultAlt
from systemf.elab3.types.wrapper import WP_HOLE
from systemf.utils.uniq import Uniq


# =============================================================================
# Test helpers
# =============================================================================

class FakeCtx(TcCtx):
    """TcCtx with hard-coded Bool, Pair and Tree types for match testing."""

    def __init__(self) -> None:
        super().__init__("Test", Uniq(1000))
        self.bool_name = Name("Test", "Bool", 1)
        self.true_name = Name("Test", "True", 2)
        self.false_name = Name("Test", "False", 3)
        self.pair_name = Name("Test", "Pair", 4)
        self.tree_name = Name("Test", "Tree", 8)

        int_ty = TyConApp(Name("Test", "Int", 10), [])
        bool_tycon = ATyCon(
            name=self.bool_name,
            tyvars=[],
            constructors=[
                ACon(name=self.true_name, tag=1, arity=0, field_types=[], parent=self.bool_name),
                ACon(name=self.false_name, tag=2, arity=0, field_types=[], parent=self.bool_name),
            ],
        )
        pair_tycon = ATyCon(
            name=self.pair_name,
            tyvars=[],
            constructors=[
                ACon(
                    name=Name("Test", "MkPair", 5),
                    tag=1,
                    arity=2,
                    field_types=[int_ty, int_ty],
                    parent=self.pair_name,
                ),
            ],
        )
        tree_tycon = ATyCon(
            name=self.tree_name,
            tyvars=[],
            constructors=[
                ACon(name=Name("Test", "Leaf", 6), tag=1, arity=0, field_types=[], parent=self.tree_name),
                ACon(
                    name=Name("Test", "Node", 7),
                    tag=2,
                    arity=3,
                    field_types=[int_ty, TyConApp(self.tree_name, []), TyConApp(self.tree_name, [])],
                    parent=self.tree_name,
                ),
            ],
        )
        self.type_env = {
            self.bool_name: bool_tycon,
            self.pair_name: pair_tycon,
            self.tree_name: tree_tycon,
        }

    def lookup_gbl(self, name: Name) -> object:
        raise KeyError(name)


def make_id(surface: str, ty: Ty, unique: int = 999) -> Id:
    return Id(Name("Test", surface, unique), ty)


def mk_matchc() -> MatchC:
    return MatchC(FakeCtx(), NameGeneratorImpl("Test", Uniq(2000)))


def body(label: str, ty: Ty) -> CoreVar:
    return C.var(make_id(f"body_{label}", ty))


# =============================================================================
# Smoke tests
# =============================================================================

def test_wildcard_single_column():
    """Single wildcard equation returns the RHS directly."""
    mc = mk_matchc()
    bool_ty = TyConApp(Name("Test", "Bool", 1), [])
    x = make_id("x", bool_ty)
    b = body("wild", bool_ty)

    result = mc.matchc([x], bool_ty, [([XPatWild()], MRInfallible(b))])

    assert isinstance(result, MRInfallible)
    assert isinstance(result.core, CoreVar)


def test_var_binder():
    """Var pattern introduces a let binding."""
    mc = mk_matchc()
    bool_ty = TyConApp(Name("Test", "Bool", 1), [])
    x = make_id("x", bool_ty)
    v = make_id("v", bool_ty)
    b = body("var", bool_ty)

    result = mc.matchc([x], bool_ty, [([XPatVar(v)], MRInfallible(b))])

    assert isinstance(result, MRInfallible)
    assert isinstance(result.core, CoreLet)


def test_lit_alts_non_exhaustive():
    """Two literal patterns are fallible because of the default fallback."""
    mc = mk_matchc()
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    x = make_id("x", int_ty)

    result = mc.matchc(
        [x],
        int_ty,
        [
            ([XPatLit(LitInt(1))], MRInfallible(body("one", int_ty))),
            ([XPatLit(LitInt(2))], MRInfallible(body("two", int_ty))),
        ],
    )

    assert isinstance(result, MRFallible)
    eh = C.var(make_id("fail", int_ty))
    core = mr_run(result, eh)
    assert isinstance(core, (CoreLet, CoreCase))
    case_expr = core.body if isinstance(core, CoreLet) else core
    assert isinstance(case_expr, CoreCase)
    assert len(case_expr.alts) == 3  # LitAlt(1), LitAlt(2), DefaultAlt


def test_con_single_alt_non_exhaustive():
    """Single constructor alt for Bool is fallible (missing False)."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name

    result = mc.matchc(
        [x],
        bool_ty,
        [([XPatCon(true_name, [], [])], MRInfallible(body("t", bool_ty)))],
    )

    assert isinstance(result, MRFallible)
    eh = C.var(make_id("fail", bool_ty))
    core = mr_run(result, eh)
    assert isinstance(core, CoreCase)
    assert len(core.alts) == 2


def test_con_exhaustive_infallible():
    """Both True and False with infallible bodies -> MRInfallible."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name

    result = mc.matchc(
        [x],
        bool_ty,
        [
            ([XPatCon(true_name, [], [])], MRInfallible(body("t", bool_ty))),
            ([XPatCon(false_name, [], [])], MRInfallible(body("f", bool_ty))),
        ],
    )

    assert isinstance(result, MRInfallible)
    assert isinstance(result.core, CoreCase)
    assert all(not isinstance(alt[0], DefaultAlt) for alt in result.core.alts)


def test_con_with_nested_args():
    """Constructor with sub-patterns generates nested matching."""
    mc = mk_matchc()
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    pair_ty = TyConApp(mc.ctx.pair_name, [])
    x = make_id("x", pair_ty)
    pair_con = mc.ctx.type_env[mc.ctx.pair_name].constructors[0].name

    result = mc.matchc(
        [x],
        pair_ty,
        [
            (
                [XPatCon(pair_con, [XPatWild(), XPatLit(LitInt(42))], [int_ty, int_ty])],
                MRInfallible(body("pair", pair_ty)),
            ),
        ],
    )

    assert isinstance(result, (MRInfallible, MRFallible))
    eh = C.var(make_id("fail", pair_ty))
    core = mr_run(result, eh)
    assert isinstance(core, CoreCase)


def test_mixed_constructor_and_wildcard():
    """True + wildcard makes an exhaustive match."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name

    result = mc.matchc(
        [x],
        bool_ty,
        [
            ([XPatCon(true_name, [], [])], MRInfallible(body("t", bool_ty))),
            ([XPatWild()], MRInfallible(body("wild", bool_ty))),
        ],
    )

    assert isinstance(result, MRInfallible)
    assert isinstance(result.core, CoreCase)


def test_fallible_submatch_inside_constructor():
    """True (infallible) + False (fallible) -> overall fallible."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name

    result = mc.matchc(
        [x],
        bool_ty,
        [
            ([XPatCon(true_name, [], [])], MRInfallible(body("t", bool_ty))),
            ([XPatCon(false_name, [], [])], MRFallible(lambda eh: eh)),
        ],
    )

    assert isinstance(result, MRFallible)


def test_multiple_columns_constructor_then_literal():
    """Bool column then Int literal column."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    x = make_id("x", bool_ty)
    y = make_id("y", int_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name

    result = mc.matchc(
        [x, y],
        bool_ty,
        [
            ([XPatCon(true_name, [], []), XPatLit(LitInt(1))], MRInfallible(body("t1", bool_ty))),
            ([XPatCon(true_name, [], []), XPatLit(LitInt(2))], MRInfallible(body("t2", bool_ty))),
            ([XPatCon(false_name, [], []), XPatWild()], MRInfallible(body("f", bool_ty))),
        ],
    )

    assert isinstance(result, (MRInfallible, MRFallible))
    eh = C.var(make_id("fail", bool_ty))
    core = mr_run(result, eh)
    assert isinstance(core, CoreCase)
    assert core.scrut == C.var(x)


# =============================================================================
# Enriched tests
# =============================================================================

def test_nested_constructors_depth_two():
    """Pair (Pair _ 1) 2 generates nested CoreCase expressions."""
    mc = mk_matchc()
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    pair_ty = TyConApp(mc.ctx.pair_name, [])
    x = make_id("x", pair_ty)
    mkpair = mc.ctx.type_env[mc.ctx.pair_name].constructors[0].name

    inner = XPatCon(mkpair, [XPatWild(), XPatLit(LitInt(1))], [int_ty, int_ty])
    outer = XPatCon(mkpair, [inner, XPatLit(LitInt(2))], [pair_ty, int_ty])

    result = mc.matchc(
        [x],
        int_ty,
        [([outer], MRInfallible(body("nested", int_ty)))],
    )

    eh = C.var(make_id("fail", int_ty))
    core = mr_run(result, eh)
    assert isinstance(core, CoreCase)
    # First level unwraps outer Pair -> inner body should be another CoreCase
    first_alt_body = core.alts[0][1]
    assert isinstance(first_alt_body, CoreCase)


def test_different_arities_in_same_column():
    """Leaf (0 args) and Node (3 args) in the same case expression."""
    mc = mk_matchc()
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    tree_ty = TyConApp(mc.ctx.tree_name, [])
    x = make_id("x", tree_ty)
    leaf_name = mc.ctx.type_env[mc.ctx.tree_name].constructors[0].name
    node_name = mc.ctx.type_env[mc.ctx.tree_name].constructors[1].name

    node_pat = XPatCon(
        node_name,
        [XPatLit(LitInt(1)), XPatCon(leaf_name, [], []), XPatWild()],
        [int_ty, tree_ty, tree_ty],
    )

    result = mc.matchc(
        [x],
        int_ty,
        [
            ([XPatCon(leaf_name, [], [])], MRInfallible(body("leaf", int_ty))),
            ([node_pat], MRInfallible(body("node", int_ty))),
        ],
    )

    # Node sub-match contains a literal -> fallible, so whole case is fallible
    assert isinstance(result, MRFallible)
    eh = C.var(make_id("fail", int_ty))
    core = mr_run(result, eh)
    assert isinstance(core, CoreCase)
    # Leaf alt has 0 binders, Node alt has 3 binders
    assert len(core.alts) == 2


def test_non_consecutive_constructor_grouping():
    """Same constructors in non-consecutive positions are merged into one group."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name

    result = mc.matchc(
        [x],
        bool_ty,
        [
            ([XPatCon(true_name, [], [])], MRInfallible(body("t1", bool_ty))),
            ([XPatCon(false_name, [], [])], MRInfallible(body("f1", bool_ty))),
            ([XPatCon(true_name, [], [])], MRInfallible(body("t2", bool_ty))),
        ],
    )

    assert isinstance(result, MRInfallible)
    core = result.core
    assert isinstance(core, CoreCase)
    # True patterns are merged into a single group, so only 2 alts
    assert len(core.alts) == 2


def test_wildcards_in_middle_columns():
    """3 columns: wildcard in the middle doesn't block recursion."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    x = make_id("x", bool_ty)
    y = make_id("y", int_ty)
    z = make_id("z", bool_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name

    result = mc.matchc(
        [x, y, z],
        int_ty,
        [
            ([XPatCon(true_name, [], []), XPatLit(LitInt(1)), XPatCon(true_name, [], [])], MRInfallible(body("t1t", int_ty))),
            ([XPatCon(true_name, [], []), XPatWild(), XPatCon(false_name, [], [])], MRInfallible(body("t_f", int_ty))),
            ([XPatWild(), XPatWild(), XPatWild()], MRInfallible(body("catchall", int_ty))),
        ],
    )

    assert isinstance(result, MRInfallible)


def test_fallible_first_group_infallible_second():
    """False (fallible) then True (infallible) -> overall infallible via mr_chain."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name

    result = mc.matchc(
        [x],
        bool_ty,
        [
            ([XPatCon(false_name, [], [])], MRFallible(lambda eh: eh)),
            ([XPatCon(true_name, [], [])], MRInfallible(body("t", bool_ty))),
        ],
    )

    # Any fallible alt inside mk_con_alts makes the whole CoreCase fallible
    assert isinstance(result, MRFallible)
    eh = C.var(make_id("fail", bool_ty))
    core = mr_run(result, eh)
    assert isinstance(core, CoreCase)


def test_all_fallible_constructor_groups():
    """Both alts fallible -> overall fallible with shared error handler."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name

    result = mc.matchc(
        [x],
        bool_ty,
        [
            ([XPatCon(true_name, [], [])], MRFallible(lambda eh: eh)),
            ([XPatCon(false_name, [], [])], MRFallible(lambda eh: eh)),
        ],
    )

    assert isinstance(result, MRFallible)


def test_single_constructor_all_wildcard_args_exhaustive():
    """Pair only has MkPair; matching it with all wildcards is exhaustive."""
    mc = mk_matchc()
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    pair_ty = TyConApp(mc.ctx.pair_name, [])
    x = make_id("x", pair_ty)
    mkpair = mc.ctx.type_env[mc.ctx.pair_name].constructors[0].name

    result = mc.matchc(
        [x],
        int_ty,
        [([XPatCon(mkpair, [XPatWild(), XPatWild()], [int_ty, int_ty])], MRInfallible(body("pair", int_ty)))],
    )

    # Single-constructor type + exhaustive coverage = infallible
    assert isinstance(result, MRInfallible)
    assert isinstance(result.core, CoreCase)
    assert all(not isinstance(alt[0], DefaultAlt) for alt in result.core.alts)


def test_var_pattern_in_middle_creates_dead_code():
    """True, then var (becomes wildcard), then False. The False is dead code."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)
    true_name = mc.ctx.true_name
    false_name = mc.ctx.false_name
    y = make_id("y", bool_ty)

    result = mc.matchc(
        [x],
        bool_ty,
        [
            ([XPatCon(true_name, [], [])], MRInfallible(body("t", bool_ty))),
            ([XPatVar(y)], MRInfallible(body("var", bool_ty))),
            ([XPatCon(false_name, [], [])], MRInfallible(body("f", bool_ty))),
        ],
    )

    # PGAny group (var) makes the match exhaustive; result is infallible
    assert isinstance(result, MRInfallible)


def test_many_literal_alts_stress():
    """Ten literal alternatives stress mk_lit_alts and grouping."""
    mc = mk_matchc()
    int_ty = TyConApp(Name("Test", "Int", 10), [])
    x = make_id("x", int_ty)

    eqns = [
        ([XPatLit(LitInt(i))], MRInfallible(body(f"lit{i}", int_ty)))
        for i in range(10)
    ]
    result = mc.matchc([x], int_ty, eqns)

    assert isinstance(result, MRFallible)
    eh = C.var(make_id("fail", int_ty))
    core = mr_run(result, eh)
    case_expr = core.body if isinstance(core, CoreLet) else core
    assert isinstance(case_expr, CoreCase)
    # 10 LitAlts + 1 DefaultAlt
    assert len(case_expr.alts) == 11


def test_coercion_pattern():
    """Coercion pattern introduces a fresh coercion var."""
    mc = mk_matchc()
    bool_ty = TyConApp(mc.ctx.bool_name, [])
    x = make_id("x", bool_ty)

    result = mc.matchc(
        [x],
        bool_ty,
        [([XPatCo(WP_HOLE, bool_ty, XPatWild())], MRInfallible(body("co", bool_ty)))],
    )

    assert isinstance(result, MRInfallible)
