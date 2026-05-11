"""Tests for bub_sf.bub_ext tape primitives."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from republic.tape.entries import TapeEntry
from republic.tape.manager import AsyncTapeManager
from systemf.elab3 import builtins as bi
from systemf.elab3.types.val import VAsync, VData, VLit, VPrim, Val
from systemf.elab3.types.ty import LitString

from bub_sf.bub_ext import BubOps
from bub_sf.store.fork_store import SQLiteForkTapeStore


@pytest.fixture
def mock_store():
    """Create a mock SQLiteForkTapeStore."""
    store = MagicMock(spec=SQLiteForkTapeStore)
    store.append = AsyncMock()
    store.fork_tape = AsyncMock()
    store.create = AsyncMock()
    return store


@pytest.fixture
def bub_ops(mock_store):
    """Create BubOps with a mock store."""
    return BubOps(mock_store)


class TestTapeAppend:
    """Tests for _tape_append primitive."""

    @pytest.mark.asyncio
    async def test_user_role(self, bub_ops, mock_store):
        """tape_append with User role."""
        tape_name = "test-tape"
        content = "hello"
        
        args = [
            VPrim(tape_name),
            VData(0, []),  # User
            VLit(LitString(content)),
        ]
        
        result = await bub_ops._tape_append(args)
        
        assert result == bi.UNIT_VAL
        mock_store.append.assert_called_once()
        call_args = mock_store.append.call_args
        assert call_args[0][0] == tape_name
        entry = call_args[0][1]
        assert isinstance(entry, TapeEntry)
        assert entry.kind == "message"
        assert entry.payload["role"] == "user"
        assert entry.payload["content"] == content
        assert "reasoning_content" not in entry.payload

    @pytest.mark.asyncio
    async def test_assistant_role_with_reasoning_content(self, bub_ops, mock_store):
        """tape_append with Assistant role sets reasoning_content."""
        tape_name = "test-tape"
        content = "summary"
        
        args = [
            VPrim(tape_name),
            VData(1, []),  # Assistant
            VLit(LitString(content)),
        ]
        
        result = await bub_ops._tape_append(args)
        
        assert result == bi.UNIT_VAL
        mock_store.append.assert_called_once()
        entry = mock_store.append.call_args[0][1]
        assert entry.payload["role"] == "assistant"
        assert entry.payload["content"] == content
        assert entry.payload["reasoning_content"] == ""


class TestTapeHandoff:
    """Tests for _tape_handoff primitive."""

    @pytest.mark.asyncio
    async def test_handoff_calls_manager(self, bub_ops, mock_store):
        """tape_handoff delegates to AsyncTapeManager.handoff."""
        tape_name = "test-tape"
        handoff_name = "checkpoint"
        
        args = [
            VPrim(tape_name),
            VLit(LitString(handoff_name)),
        ]
        
        # Mock the manager's handoff method
        bub_ops.mgr.handoff = AsyncMock()
        
        result = await bub_ops._tape_handoff(args)
        
        assert result == bi.UNIT_VAL
        bub_ops.mgr.handoff.assert_called_once_with(tape_name, handoff_name)


class TestMakeTape:
    """Tests for _make_tape primitive."""

    @pytest.mark.asyncio
    async def test_make_tape_without_parent(self, bub_ops, mock_store):
        """make_tape with Nothing parent creates root tape."""
        args = [
            VData(0, []),  # Nothing
            VLit(LitString("mytape")),
        ]
        
        result = await bub_ops._make_tape(args)
        
        assert isinstance(result, VPrim)
        # Name should be "mytape-<suffix>"
        assert result.val.startswith("mytape-")

    @pytest.mark.asyncio
    async def test_make_tape_with_parent(self, bub_ops, mock_store):
        """make_tape with parent creates child tape."""
        parent_name = "parent-tape"
        args = [
            VData(1, [VPrim(parent_name)]),  # Just parent
            VLit(LitString("child")),
        ]
        
        result = await bub_ops._make_tape(args)
        
        assert isinstance(result, VPrim)
        mock_store.create.assert_called_once()
        # Name should be "parent-tape/child-<suffix>"
        assert result.val.startswith("parent-tape/child-")


class TestForkTape:
    """Tests for _fork_tape primitive."""

    @pytest.mark.asyncio
    async def test_fork_tape_with_name(self, bub_ops, mock_store):
        """fork_tape with explicit name uses it."""
        tape_name = "source"
        fork_name = "myfork"
        
        args = [
            VPrim(tape_name),
            VData(1, [VLit(LitString(fork_name))]),  # Just fork_name
        ]
        
        result = await bub_ops._fork_tape(args)
        
        assert isinstance(result, VPrim)
        assert result.val == fork_name
        mock_store.fork_tape.assert_called_once_with(tape_name, fork_name)

    @pytest.mark.asyncio
    async def test_fork_tape_with_nothing_generates_name(self, bub_ops, mock_store):
        """fork_tape with Nothing generates a random fork name."""
        tape_name = "source"
        
        args = [
            VPrim(tape_name),
            VData(0, []),  # Nothing
        ]
        
        result = await bub_ops._fork_tape(args)
        
        assert isinstance(result, VPrim)
        assert result.val.startswith("source/fork_")
        mock_store.fork_tape.assert_called_once()
