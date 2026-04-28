"""Tests for recursive and mutually recursive bindings in elab3.

These tests verify that the SCC-based binding group processing correctly
handles self-recursive and mutually recursive bindings.
"""

from __future__ import annotations

import pytest

from systemf.elab3.typecheck_expr import TypeChecker
from systemf.elab3.types.ast import Binding, Var, App, Lam, LitExpr, Let
from systemf.elab3.types.ty import Name, TyInt, TyFun, TyForall, TyVar, Id
from systemf.elab3.types.core import CoreLet, CoreVar, Rec, NonRec
from systemf.elab3.repl import REPL
from systemf.elab3.name_gen import NameGeneratorImpl
from systemf.utils.uniq import Uniq


def mk_name(surface: str, mod: str = "Test", unique: int = 1) -> Name:
    return Name(mod=mod, surface=surface, unique=unique)


def mk_tc() -> TypeChecker:
    """Create a TypeChecker for testing."""
    repl = REPL()
    name_gen = NameGeneratorImpl("Test", repl.uniq)
    return TypeChecker(repl, "Test", name_gen, {})


class TestRecursiveBindings:
    """Test self-recursive and mutually recursive bindings."""

    def test_non_recursive_binding(self):
        """Simple non-recursive binding should work as before."""
        tc = mk_tc()
        x = mk_name("x")
        
        # let x = 42 in x
        bindings = [Binding(x, LitExpr(LitInt(42)))]
        body = Var(x)
        
        result = tc.let(bindings, body, Check(TyInt()))
        core = result()
        
        # Should be: let x = 42 in x
        assert isinstance(core, CoreLet)
        assert isinstance(core.binding, NonRec)
        
    def test_self_recursive_binding(self):
        """Self-recursive binding (factorial-like)."""
        tc = mk_tc()
        fact = mk_name("fact", unique=1)
        n = mk_name("n", unique=2)
        
        # let fact n = if n == 0 then 1 else n * fact (n - 1)
        # For simplicity, just test that it typechecks
        # We'll use a simpler recursive form: let fact = \n -> fact n
        bindings = [
            Binding(fact, Lam([n], App(Var(fact), Var(n))))
        ]
        body = Var(fact)
        
        # This should typecheck and produce a Rec binding
        result = tc.let(bindings, body, Check(TyFun(TyInt(), TyInt())))
        core = result()
        
        # Should be: let fact = letrec { _fact_mono = \n -> _fact_mono n } in _fact_mono in fact
        assert isinstance(core, CoreLet)
        assert isinstance(core.binding, NonRec)
        # The RHS of the NonRec contains the letrec
        inner_let = core.binding.expr
        assert isinstance(inner_let, CoreLet)
        assert isinstance(inner_let.binding, Rec)
        assert len(inner_let.binding.bindings) == 1
        
    def test_mutual_recursion(self):
        """Mutually recursive bindings (even/odd)."""
        tc = mk_tc()
        even = mk_name("even", unique=1)
        odd = mk_name("odd", unique=2)
        n = mk_name("n", unique=3)
        
        # let even n = odd (n - 1)
        #     odd n = even (n - 1)
        # in even
        bindings = [
            Binding(even, Lam([n], App(Var(odd), Var(n)))),
            Binding(odd, Lam([n], App(Var(even), Var(n)))),
        ]
        body = Var(even)
        
        result = tc.let(bindings, body, Check(TyFun(TyInt(), TyInt())))
        core = result()
        
        # Should be: letrec { even = \n -> odd n; odd = \n -> even n } in even
        assert isinstance(core, CoreLet)
        assert isinstance(core.binding, Rec)
        assert len(core.binding.bindings) == 2
        
    def test_mixed_recursive_non_recursive(self):
        """Mix of recursive and non-recursive bindings."""
        tc = mk_tc()
        x = mk_name("x", unique=1)
        y = mk_name("y", unique=2)
        z = mk_name("z", unique=3)
        
        # let x = 1
        #     y = x + 1
        #     z = y + 1
        # in z
        bindings = [
            Binding(x, LitExpr(LitInt(1))),
            Binding(y, Var(x)),  # y uses x
            Binding(z, Var(y)),  # z uses y
        ]
        body = Var(z)
        
        result = tc.let(bindings, body, Check(TyInt()))
        core = result()
        
        # Should have nested NonRec bindings
        assert isinstance(core, CoreLet)
        
    def test_topological_ordering(self):
        """Bindings should be processed in topological order."""
        tc = mk_tc()
        a = mk_name("a", unique=1)
        b = mk_name("b", unique=2)
        c = mk_name("c", unique=3)
        
        # let c = b
        #     b = a
        #     a = 1
        # in c
        bindings = [
            Binding(c, Var(b)),
            Binding(b, Var(a)),
            Binding(a, LitExpr(LitInt(1))),
        ]
        body = Var(c)
        
        result = tc.let(bindings, body, Check(TyInt()))
        core = result()
        
        # Should typecheck successfully (a before b before c)
        assert isinstance(core, CoreLet)


class TestBindingErrors:
    """Test error cases for bindings."""

    def test_unbound_variable(self):
        """Using an unbound variable should fail."""
        tc = mk_tc()
        x = mk_name("x", unique=1)
        y = mk_name("y", unique=2)
        
        # let x = y in x  (y is unbound)
        bindings = [Binding(x, Var(y))]
        body = Var(x)
        
        with pytest.raises(Exception):
            result = tc.let(bindings, body, Check(TyInt()))
            result()  # Force evaluation


# Import needed for tests
from systemf.elab3.types.ty import LitInt
from systemf.elab3.tc_ctx import Check