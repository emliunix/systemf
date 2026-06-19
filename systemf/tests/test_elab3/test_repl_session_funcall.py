"""Tests for the REPLSession funcall helper utilities."""
from pathlib import Path

import pytest

from systemf.elab3.repl import REPL
from systemf.elab3.repl_session import (
    mk_funcall,
    mk_funcall_by_name,
    mk_funcall_unsafe_fun,
)
from systemf.elab3.types.core import CoreApp, CoreVar
from systemf.elab3.types.ty import Id, LitInt, Name, TyFun, TyInt
from systemf.elab3.types.val import CoreValUnsafe, VLit


class FakeREPLSession:
    """Minimal stand-in for REPLSessionProto.resolve_name."""

    def resolve_name(self, name: str) -> Id:
        return Id(Name("M", "f", 1), TyFun(TyInt(), TyInt()))


def test_mk_funcall_with_no_args():
    fun = Id(Name("M", "f", 1), TyFun(TyInt(), TyInt()))
    term = mk_funcall(fun, [])
    assert term == CoreVar(fun)


def test_mk_funcall_with_args():
    fun = Id(Name("M", "f", 1), TyFun(TyInt(), TyFun(TyInt(), TyInt())))
    arg1 = VLit(LitInt(1))
    arg2 = VLit(LitInt(2))

    term = mk_funcall(fun, [arg1, arg2])

    expected = CoreApp(
        CoreApp(CoreVar(fun), CoreValUnsafe(arg1)),
        CoreValUnsafe(arg2),
    )
    assert term == expected


def test_mk_funcall_unsafe_fun_with_no_args():
    fun = VLit(LitInt(42))
    term = mk_funcall_unsafe_fun(fun, [])
    assert term == CoreValUnsafe(fun)


def test_mk_funcall_unsafe_fun_with_args():
    fun = VLit(LitInt(0))
    arg = VLit(LitInt(1))

    term = mk_funcall_unsafe_fun(fun, [arg])

    expected = CoreApp(CoreValUnsafe(fun), CoreValUnsafe(arg))
    assert term == expected


def test_mk_funcall_by_name_resolves_name_and_builds_term():
    arg = VLit(LitInt(5))
    term = mk_funcall_by_name("M.f", [arg], FakeREPLSession())

    expected = CoreApp(
        CoreVar(Id(Name("M", "f", 1), TyFun(TyInt(), TyInt()))),
        CoreValUnsafe(arg),
    )
    assert term == expected


async def test_mk_funcall_evaluates_named_function():
    repl = REPL()
    session = repl.new_session()
    plus_id = session.resolve_name("builtins.int_plus")

    term = mk_funcall(plus_id, [VLit(LitInt(1)), VLit(LitInt(2))])
    result = await session.unsafe_eval(term)

    assert result == VLit(LitInt(3))


async def test_mk_funcall_by_name_evaluates_module_function():
    data_dir = Path(__file__).parent.parent / "data"
    repl = REPL(search_paths=[str(data_dir)])
    repl.load("FuncallMod")
    session = repl.new_session()

    term = mk_funcall_by_name("FuncallMod.double", [VLit(LitInt(21))], session)
    result = await session.unsafe_eval(term)

    assert result == VLit(LitInt(42))


async def test_mk_funcall_unsafe_fun_evaluates_closure():
    repl = REPL()
    session = repl.new_session()
    closure_val, _ = await session.eval("\\x -> int_plus x x")

    term = mk_funcall_unsafe_fun(closure_val, [VLit(LitInt(3))])
    result = await session.unsafe_eval(term)

    assert result == VLit(LitInt(6))


async def test_mk_funcall_by_name_unknown_name_raises():
    repl = REPL()
    session = repl.new_session()

    with pytest.raises(Exception, match="not found"):
        mk_funcall_by_name("NoSuchModule.no_such_name", [], session)


async def test_sequence_operator_single_line():
    """The ; operator evaluates to the right-hand value."""
    repl = REPL()
    session = repl.new_session()
    result = await session.eval("1 ; 2")
    assert result is not None
    assert result[0] == VLit(LitInt(2))


async def test_sequence_operator_multiline():
    """The ; operator works across aligned lines."""
    repl = REPL()
    session = repl.new_session()
    result = await session.eval("1 ;\n2")
    assert result is not None
    assert result[0] == VLit(LitInt(2))
