"""Tests for TypeChecker expression typechecking.

Covers elab3 typecheck_expr.py rules not already tested in
 test_putting2007_terms.py (which focuses on the paper examples).
"""
import pytest

from typing import Callable

from systemf.elab3.typecheck_expr import TypeChecker
from systemf.elab3.rename_expr import RenameExpr
from systemf.elab3.reader_env import ReaderEnv
from systemf.elab3.types.ty import (
    Id,
    Name,
    Ty,
    TyFun,
    TyInt,
    TyString,
    zonk_type,
)
from systemf.elab3.types.tything import AnId
from systemf.elab3.types.tc import Check, Infer
from systemf.surface.parser import parse_expression
from systemf.utils.uniq import Uniq


INT = TyInt()
STRING = TyString()


def _name(surface: str, unique: int = 1) -> Name:
    return Name("TcExprTest", surface, unique)


def _id(surface: str, ty: Ty, unique: int = 1) -> Id:
    return Id(_name(surface, unique), ty)


class FakeNameCache:
    def get(self, module: str, name: str):
        return None
    def put(self, name: Name):
        pass
    def put_all(self, names):
        pass


class FakeNameGen:
    _counter: int

    def __init__(self):
        self._counter = 0

    def new_name(self, name: str | Callable[[int], str], loc=None):
        self._counter += 1
        if callable(name):
            return Name("TcExprTest", name(self._counter), self._counter, loc)
        return Name("TcExprTest", name, self._counter, loc)

    def new_id(self, name: str | Callable[[int], str], ty: Ty):
        return Id(self.new_name(name, None), ty)


class FakeREPLContext:
    def __init__(self):
        self.uniq = Uniq(8000)
        self.name_cache = FakeNameCache()

    def load(self, name: str):
        raise KeyError(name)

    def next_replmod_id(self):
        return 0

    def get_primop(self, name, thing, session):
        return None


class FakeTcCtx(TypeChecker):
    def __init__(self, type_env: dict[Name, AnId] | None = None):
        ctx = FakeREPLContext()
        name_gen = FakeNameGen()
        super().__init__(ctx, "TcExprTest", name_gen)
        if type_env:
            for name, anid in type_env.items():
                self.type_env[name] = anid

    def lookup_gbl(self, name: Name):
        if name in self.type_env:
            return self.type_env[name]
        raise KeyError(name)


class FakeRenameExpr(RenameExpr):
    def __init__(self, local_names: list[tuple[str, Name]] | None = None):
        super().__init__(ReaderEnv.empty(), "TcExprTest", None)
        if local_names:
            self.local_env = [(s, n) for s, n in local_names]

    def new_name(self, name: str, loc=None):
        return _name(name)

    def new_names(self, names, loc=None):
        return [_name(n) for n in names]


def _parse_and_rename(source: str, local_vars: list[tuple[str, Ty]] | None = None) -> "Expr":
    """Parse an expression and rename it with optional local variable bindings."""
    from systemf.elab3.types.ast import Expr
    ast = parse_expression(source)
    local_names = [(s, _name(s)) for s, _ in (local_vars or [])]
    renamer = FakeRenameExpr(local_names)
    return renamer.rename_expr(ast)


# =============================================================================
# AABS — Annotated abstraction
# =============================================================================

def test_aabs_infer():
    r"""AABS1 (infer): \x:Int -> x  infers  Int -> Int."""
    expr = _parse_and_rename(r"\(x :: Int) -> x")
    ctx = FakeTcCtx()
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    result = zonk_type(infer.ref.get())
    assert result == TyFun(INT, INT)


def test_aabs_check():
    r"""AABS2 (check): \x:Int -> x  checks against  Int -> Int."""
    expr = _parse_and_rename(r"\(x :: Int) -> x")
    ctx = FakeTcCtx()
    ctx.expr(expr, Check(TyFun(INT, INT)))
    # No exception = success


def test_aabs_check_fail():
    r"""AABS2 (check fail): \x:Int -> x  does not check against  Int -> String."""
    expr = _parse_and_rename(r"\(x :: Int) -> x")
    ctx = FakeTcCtx()
    with pytest.raises(Exception):
        ctx.expr(expr, Check(TyFun(INT, STRING)))
