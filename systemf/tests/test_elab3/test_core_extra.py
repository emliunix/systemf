"""Tests for CoreBuilderExtra."""

from __future__ import annotations

import pytest

from systemf.elab3.core_extra import CoreBuilderExtra
from systemf.elab3.types.ty import TyInt, TyString, BoundTv, Name, TyConApp, Id
from systemf.elab3.types.tything import ATyCon, ACon, TyThing
from systemf.elab3.types.core import CoreVar, CoreApp, CoreTyApp
from systemf.elab3.builtins import BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR


class MockTyLookup:
    """Simple in-memory TyLookup for testing."""

    def __init__(self, things: dict[Name, TyThing]) -> None:
        self._things = things

    def lookup(self, name: Name) -> TyThing | None:
        return self._things.get(name)


def _mk_pair_tycon() -> ATyCon:
    a = BoundTv(name=Name("builtins", "a", 1001))
    b = BoundTv(name=Name("builtins", "b", 1002))
    mkpair = ACon(
        name=BUILTIN_PAIR_MKPAIR,
        tag=0,
        arity=2,
        field_types=[a, b],
        parent=BUILTIN_PAIR,
    )
    return ATyCon(
        name=BUILTIN_PAIR,
        tyvars=[a, b],
        constructors=[mkpair],
    )


def _mk_lookup() -> MockTyLookup:
    pair_tycon = _mk_pair_tycon()
    return MockTyLookup({
        BUILTIN_PAIR: pair_tycon,
        BUILTIN_PAIR_MKPAIR: pair_tycon.constructors[0],
    })


def test_mk_tuple_two_elements():
    """Build a 2-tuple (pair)."""
    ctx = _mk_lookup()
    builder = CoreBuilderExtra(ctx)

    t1 = CoreVar(Id(name=Name("Test", "x", 1), ty=TyInt()))
    t2 = CoreVar(Id(name=Name("Test", "y", 2), ty=TyString()))

    tm, ty = builder.mk_tuple([t1, t2], [TyInt(), TyString()])

    # Should be: MkPair @Int @String x y
    assert isinstance(tm, CoreApp)
    assert isinstance(tm.fun, CoreApp)
    assert isinstance(tm.fun.fun, CoreTyApp)
    assert isinstance(tm.fun.fun.fun, CoreTyApp)
    assert isinstance(tm.fun.fun.fun.fun, CoreVar)

    # Result type should be Pair Int String
    assert isinstance(ty, TyConApp)
    assert ty.name == BUILTIN_PAIR
    assert ty.args == [TyInt(), TyString()]


def test_mk_tuple_three_elements():
    """Build a 3-tuple (nested pairs)."""
    ctx = _mk_lookup()
    builder = CoreBuilderExtra(ctx)

    t1 = CoreVar(Id(name=Name("Test", "a", 1), ty=TyInt()))
    t2 = CoreVar(Id(name=Name("Test", "b", 2), ty=TyString()))
    t3 = CoreVar(Id(name=Name("Test", "c", 3), ty=TyInt()))

    tm, ty = builder.mk_tuple([t1, t2, t3], [TyInt(), TyString(), TyInt()])

    # Result type should be Pair Int (Pair String Int)
    assert isinstance(ty, TyConApp)
    assert ty.name == BUILTIN_PAIR
    assert ty.args[0] == TyInt()
    inner = ty.args[1]
    assert isinstance(inner, TyConApp)
    assert inner.args == [TyString(), TyInt()]


def test_mk_tuple_mismatched_lengths():
    """Elements and types must match in length."""
    ctx = _mk_lookup()
    builder = CoreBuilderExtra(ctx)

    t1 = CoreVar(Id(name=Name("Test", "x", 1), ty=TyInt()))
    with pytest.raises(Exception, match="does not match"):
        builder.mk_tuple([t1], [TyInt(), TyString()])


def test_mk_tuple_too_few_elements():
    """Tuple must have at least 2 elements."""
    ctx = _mk_lookup()
    builder = CoreBuilderExtra(ctx)

    t1 = CoreVar(Id(name=Name("Test", "x", 1), ty=TyInt()))
    with pytest.raises(Exception, match="at least 2"):
        builder.mk_tuple([t1], [TyInt()])


def test_lookup_data_con():
    """lookup_data_con returns tycon, con, and constructed type."""
    from systemf.elab3.core_extra import lookup_data_con
    ctx = _mk_lookup()

    tycon, con, ty = lookup_data_con(ctx, BUILTIN_PAIR_MKPAIR)
    assert tycon.name == BUILTIN_PAIR
    assert con.name == BUILTIN_PAIR_MKPAIR
    # Type should be forall a b. a -> b -> Pair a b
    assert str(ty).startswith("forall")
