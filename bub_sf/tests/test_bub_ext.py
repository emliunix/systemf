"""Tests for bub_sf.bub_ext tape primitives."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from republic.tape.entries import TapeEntry
from systemf.elab3 import builtins as bi
from systemf.elab3.types.val import VAsync, VData, VLit, VPrim, Val
from systemf.elab3.types.ty import LitString

from bub_sf.bub_ext import BubOps


@pytest.fixture
def mock_agent():
    """Create a mock Agent with mock tapes."""
    agent = MagicMock()
    agent.tapes = MagicMock()
    agent.tapes.append_entry = AsyncMock()
    agent.tapes.handoff = AsyncMock(return_value=[])
    agent.tapes.create = AsyncMock()
    agent.tapes.fork_tape = AsyncMock()
    return agent


class MockSession:
    """Mock REPLSessionProto with agent in state."""
    def __init__(self, agent):
        self.state = {"_runtime_agent": agent}
    
    def fork(self):
        return MockSession(self.state.get("_runtime_agent"))
    
    def add_args(self, args):
        pass
    
    def add_return(self, ref, ty):
        pass
    
    def add_import(self, decl):
        pass
    
    async def eval(self, input):
        return None
    
    async def unsafe_eval(self, input):
        return None
    
    def lookup(self, name):
        return None


@pytest.fixture
def mock_session(mock_agent):
    """Create a mock REPLSessionProto with agent in state."""
    return MockSession(mock_agent)


@pytest.fixture
def bub_ops():
    """Create BubOps with a mock framework."""
    framework = MagicMock()
    return BubOps(framework)


class TestTapeAppend:
    """Tests for _tape_append primitive."""

    @pytest.mark.asyncio
    async def test_user_role(self, bub_ops, mock_agent, mock_session):
        """tape_append with User role."""
        tape_name = "test-tape"
        content = "hello"
        
        args = [
            VPrim(tape_name),
            VData(0, []),  # User
            VLit(LitString(content)),
        ]
        
        result = bub_ops._tape_append(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert val == bi.UNIT_VAL
        mock_agent.tapes.append_entry.assert_called_once()
        call_args = mock_agent.tapes.append_entry.call_args
        assert call_args[0][0] == tape_name
        entry = call_args[0][1]
        assert isinstance(entry, TapeEntry)
        assert entry.kind == "message"
        assert entry.payload["role"] == "user"
        assert entry.payload["content"] == content
        assert "reasoning_content" not in entry.payload

    @pytest.mark.asyncio
    async def test_assistant_role_with_reasoning_content(self, bub_ops, mock_agent, mock_session):
        """tape_append with Assistant role sets reasoning_content."""
        tape_name = "test-tape"
        content = "summary"
        
        args = [
            VPrim(tape_name),
            VData(1, []),  # Assistant
            VLit(LitString(content)),
        ]
        
        result = bub_ops._tape_append(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert val == bi.UNIT_VAL
        mock_agent.tapes.append_entry.assert_called_once()
        entry = mock_agent.tapes.append_entry.call_args[0][1]
        assert entry.payload["role"] == "assistant"
        assert entry.payload["content"] == content
        assert entry.payload["reasoning_content"] == ""


class TestTapeHandoff:
    """Tests for _tape_handoff primitive."""

    @pytest.mark.asyncio
    async def test_handoff_calls_agent_tapes(self, bub_ops, mock_agent, mock_session):
        """tape_handoff delegates to agent.tapes.handoff."""
        tape_name = "test-tape"
        handoff_name = "checkpoint"
        
        args = [
            VPrim(tape_name),
            VLit(LitString(handoff_name)),
        ]
        
        result = bub_ops._tape_handoff(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert val == bi.UNIT_VAL
        mock_agent.tapes.handoff.assert_called_once_with(tape_name, name=handoff_name)


class TestMakeTape:
    """Tests for _make_tape primitive."""

    @pytest.mark.asyncio
    async def test_make_tape_without_parent(self, bub_ops, mock_agent, mock_session):
        """make_tape with Nothing parent creates root tape."""
        args = [
            VData(0, []),  # Nothing
            VLit(LitString("mytape")),
        ]
        
        result = bub_ops._make_tape(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert isinstance(val, VPrim)
        # Name should be "mytape-<suffix>"
        assert val.val.startswith("mytape-")

    @pytest.mark.asyncio
    async def test_make_tape_with_parent(self, bub_ops, mock_agent, mock_session):
        """make_tape with parent creates child tape."""
        parent_name = "parent-tape"
        args = [
            VData(1, [VPrim(parent_name)]),  # Just parent
            VLit(LitString("child")),
        ]
        
        result = bub_ops._make_tape(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert isinstance(val, VPrim)
        mock_agent.tapes.create.assert_called_once()
        # Name should be "parent-tape/child-<suffix>"
        assert val.val.startswith("parent-tape/child-")


class TestForkTape:
    """Tests for _fork_tape primitive."""

    @pytest.mark.asyncio
    async def test_fork_tape_with_name(self, bub_ops, mock_agent, mock_session):
        """fork_tape with explicit name uses it."""
        tape_name = "source"
        fork_name = "myfork"
        
        args = [
            VPrim(tape_name),
            VData(1, [VLit(LitString(fork_name))]),  # Just fork_name
        ]
        
        result = bub_ops._fork_tape(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert isinstance(val, VPrim)
        assert val.val == fork_name
        mock_agent.tapes.fork_tape.assert_called_once_with(tape_name, fork_name)

    @pytest.mark.asyncio
    async def test_fork_tape_with_nothing_generates_name(self, bub_ops, mock_agent, mock_session):
        """fork_tape with Nothing generates a random fork name."""
        tape_name = "source"
        
        args = [
            VPrim(tape_name),
            VData(0, []),  # Nothing
        ]
        
        result = bub_ops._fork_tape(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert isinstance(val, VPrim)
        assert val.val.startswith("source/fork_")
        mock_agent.tapes.fork_tape.assert_called_once()
