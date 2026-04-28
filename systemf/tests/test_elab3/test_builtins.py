"""Tests for builtins module loading and ref operations."""

import pytest

from systemf.elab3.repl import REPL
from systemf.elab3.types.val import VData, VLit, VPrim
from systemf.elab3.types.ty import LitInt


class TestBuiltinsModule:
    """Test builtins module exports and ref operations."""

    def test_builtins_exports(self):
        """Builtins module should export all expected names."""
        ctx = REPL()
        builtins_mod = ctx.load("builtins")
        
        exports = [n.surface for n in builtins_mod.exports]
        
        # Core types
        assert "Unit" in exports
        assert "Bool" in exports
        assert "List" in exports
        assert "Pair" in exports
        assert "Maybe" in exports
        assert "Ref" in exports
        
        # Data constructors
        assert "True" in exports
        assert "False" in exports
        assert "Nil" in exports
        assert "Cons" in exports
        assert "Nothing" in exports
        assert "Just" in exports
        
        # Ref operations
        assert "mk_ref" in exports
        assert "set_ref" in exports
        assert "get_ref" in exports

    async def test_mk_ref_creates_ref(self):
        """mk_ref should create a VPrim containing a mutable cell."""
        ctx = REPL()
        session = ctx.new_session()
        
        result = await session.eval("mk_ref MkUnit")
        assert result and isinstance(result[0], VPrim)
        assert result[0].val == [VData(0, [])]

    async def test_get_ref_returns_nothing_initially(self):
        """get_ref on fresh ref should return Nothing."""
        ctx = REPL()
        session = ctx.new_session()
        
        result = await session.eval("get_ref (mk_ref MkUnit)")
        # Nothing is tag 0 with no values
        assert result and result[0] == VData(0, [])

    async def test_set_ref_and_get_ref(self):
        """set_ref should update value, get_ref should retrieve it."""
        ctx = REPL()
        session = ctx.new_session()
        
        result = await session.eval("let r = mk_ref 0 in let _ = set_ref r 42 in get_ref r")
        assert result and result[0] == VLit(LitInt(42))

    async def test_multiple_sets(self):
        """Multiple set_ref calls should overwrite value."""
        ctx = REPL()
        session = ctx.new_session()
        
        result = await session.eval("let r = mk_ref 0 in let _ = set_ref r 1 in let _ = set_ref r 2 in get_ref r")
        assert result and result[0] == VLit(LitInt(2))
