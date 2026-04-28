"""Bidirectional type checking term tests from Putting2007 (JFP).

Ported from elab2 test_tyck_examples_terms.py.

Uses a hybrid approach:
1. Parse expression source
2. Rename with a simple environment
3. Typecheck using TypeChecker methods directly
"""

from typing import Callable

import pytest

from systemf.elab3.tc_ctx import TcCtx
from systemf.elab3.typecheck_expr import TypeChecker
from systemf.elab3.rename_expr import RenameExpr
from systemf.elab3.reader_env import ReaderEnv
from systemf.elab3.types.ty import (
    BoundTv,
    Id,
    Name,
    Ty,
    TyForall,
    TyFun,
    TyInt,
    TyString,
    zonk_type,
)
from systemf.elab3.types.tything import AnId
from systemf.elab3.types.tc import Check, Infer
from systemf.elab3.types.wrapper import WP_HOLE, WpTyApp
from systemf.surface.parser import parse_expression
from systemf.utils.uniq import Uniq


INT = TyInt()
STRING = TyString()


def _name(surface: str, unique: int = 1) -> Name:
    return Name("PuttingTermsTest", surface, unique)


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
            return Name("PuttingTermsTest", name(self._counter), self._counter, loc)
        return Name("PuttingTermsTest", name, self._counter, loc)

    def new_id(self, name: str | Callable[[int], str], ty: Ty):
        return Id(self.new_name(name, None), ty)


class FakeREPLContext:
    def __init__(self):
        self.uniq = Uniq(7000)
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
        super().__init__(ctx, "PuttingTermsTest", name_gen)
        if type_env:
            for name, anid in type_env.items():
                self.type_env[name] = anid

    def lookup_gbl(self, name: Name):
        if name in self.type_env:
            return self.type_env[name]
        raise KeyError(name)


class FakeRenameExpr(RenameExpr):
    def __init__(self, local_names: list[tuple[str, Name]] | None = None):
        super().__init__(ReaderEnv.empty(), "PuttingTermsTest", None)
        if local_names:
            self.local_env = [(s, n) for s, n in local_names]

    def new_name(self, name: str, loc=None):
        return _name(name)

    def new_names(self, names, loc=None):
        return [_name(n) for n in names]


def _parse_and_rename(source: str, local_vars: list[tuple[str, Ty]] | None = None) -> "Expr":
    """Parse an expression and rename it with optional local variable bindings."""
    ast = parse_expression(source)
    local_names = [(s, _name(s)) for s, _ in (local_vars or [])]
    renamer = FakeRenameExpr(local_names)
    return renamer.rename_expr(ast)


# =============================================================================
# Figure 8 — INT rule
# =============================================================================


def test_int_infer():
    expr = _parse_and_rename("42")
    ctx = FakeTcCtx()
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    assert zonk_type(infer.ref.get()) == INT


def test_int_check():
    expr = _parse_and_rename("42")
    ctx = FakeTcCtx()
    ctx.expr(expr, Check(INT))
    # No exception = success


def test_int_check_fail():
    expr = _parse_and_rename("42")
    ctx = FakeTcCtx()
    with pytest.raises(Exception):
        ctx.expr(expr, Check(STRING))


# =============================================================================
# Figure 8 — VAR rule
# =============================================================================


def test_var_mono():
    x_id = _id("x", INT)
    expr = _parse_and_rename("x", [("x", INT)])
    ctx = FakeTcCtx({_name("x"): AnId.create(x_id)})
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    assert zonk_type(infer.ref.get()) == INT


def test_var_poly():
    a = BoundTv(_name("a"))
    poly_id = TyForall([a], TyFun(a, a))
    id_id = _id("id", poly_id)
    expr = _parse_and_rename("id", [("id", poly_id)])
    ctx = FakeTcCtx({_name("id"): AnId.create(id_id)})
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    result = zonk_type(infer.ref.get())
    # Should instantiate to some function type
    assert isinstance(result, TyFun)


# =============================================================================
# Figure 8 — ABS rule
# =============================================================================


def test_abs1_infer():
    expr = _parse_and_rename("\\x -> x")
    ctx = FakeTcCtx()
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    result = zonk_type(infer.ref.get())
    assert isinstance(result, TyFun)


def test_abs2_check():
    expr = _parse_and_rename("\\x -> x")
    ctx = FakeTcCtx()
    ctx.expr(expr, Check(TyFun(INT, INT)))
    # No exception = success


def test_abs2_check_fail():
    expr = _parse_and_rename("\\x -> x")
    ctx = FakeTcCtx()
    with pytest.raises(Exception):
        ctx.expr(expr, Check(TyFun(INT, STRING)))


# =============================================================================
# Figure 8 — APP rule
# =============================================================================


def test_app_mono():
    id_id = _id("id", TyFun(INT, INT))
    expr = _parse_and_rename("id 42", [("id", TyFun(INT, INT))])
    ctx = FakeTcCtx({_name("id"): AnId.create(id_id)})
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    assert zonk_type(infer.ref.get()) == INT


def test_app_poly():
    a = BoundTv(_name("a"))
    poly_id = TyForall([a], TyFun(a, a))
    id_id = _id("id", poly_id)
    expr = _parse_and_rename("id 42", [("id", poly_id)])
    ctx = FakeTcCtx({_name("id"): AnId.create(id_id)})
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    assert zonk_type(infer.ref.get()) == INT


# =============================================================================
# Figure 8 — LET rule
# =============================================================================


def test_let_simple():
    expr = _parse_and_rename("let x = 42 in x")
    ctx = FakeTcCtx()
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    assert zonk_type(infer.ref.get()) == INT


def test_let_poly():
    expr = _parse_and_rename("let id = \\x -> x in id 42")
    ctx = FakeTcCtx()
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    assert zonk_type(infer.ref.get()) == INT


# =============================================================================
# Figure 8 — GEN rule
# =============================================================================


def test_gen1_infer():
    expr = _parse_and_rename("\\x -> x")
    ctx = FakeTcCtx()
    infer = ctx.make_infer()
    ctx.expr(expr, infer)
    result = zonk_type(infer.ref.get())
    # Should be a function type (generalization happens at binding level)
    assert isinstance(result, TyFun)


def test_gen2_check():
    a = BoundTv(_name("a"))
    poly_ty = TyForall([a], TyFun(a, a))
    expr = _parse_and_rename("\\x -> x")
    ctx = FakeTcCtx()
    ctx.expr(expr, Check(poly_ty))
    # No exception = success


# =============================================================================
# Integration
# =============================================================================


def test_integration_identity():
    """End-to-end: parse, rename, typecheck identity function."""
    expr = _parse_and_rename("\\x -> x")
    ctx = FakeTcCtx()
    infer = ctx.make_infer()
    result = ctx.expr(expr, infer)
    ty = zonk_type(infer.ref.get())
    assert isinstance(ty, TyFun)
