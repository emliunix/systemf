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
    agent.tapes.info = AsyncMock()
    return agent


class MockSession:
    """Mock REPLSessionProto with agent in state."""
    def __init__(self, agent):
        self.state = {"bub_state": {"_runtime_agent": agent}}
    
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
        mock_agent.tapes.handoff.assert_called_once()
        call_kwargs = mock_agent.tapes.handoff.call_args
        assert call_kwargs[0][0] == tape_name
        # impl appends a uuid suffix to keep handoff names unique
        assert call_kwargs[1]["name"].startswith(f"{handoff_name}_")


class TestMakeTape:
    """Tests for _tape_make primitive."""

    @pytest.mark.asyncio
    async def test_make_tape_without_parent(self, bub_ops, mock_agent, mock_session):
        """make_tape with Nothing parent creates root tape."""
        args = [
            VData(0, []),  # Nothing
            VLit(LitString("mytape")),
        ]
        
        result = bub_ops._tape_make(args, mock_session)
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
        
        result = bub_ops._tape_make(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert isinstance(val, VPrim)
        mock_agent.tapes.create.assert_called_once()
        # Name should be "parent-tape/child-<suffix>"
        assert val.val.startswith("parent-tape/child-")


class TestForkTape:
    """Tests for _tape_fork primitive."""

    @pytest.mark.asyncio
    async def test_fork_tape_with_name(self, bub_ops, mock_agent, mock_session):
        """fork_tape with explicit name uses it."""
        tape_name = "source"
        fork_name = "myfork"
        
        args = [
            VPrim(tape_name),
            VData(1, [VLit(LitString(fork_name))]),  # Just fork_name
        ]
        
        result = bub_ops._tape_fork(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert isinstance(val, VPrim)
        # impl appends a uuid suffix to keep fork names unique
        assert val.val.startswith(f"{fork_name}_")
        mock_agent.tapes.fork_tape.assert_called_once_with(tape_name, val.val)

    @pytest.mark.asyncio
    async def test_fork_tape_with_nothing_generates_name(self, bub_ops, mock_agent, mock_session):
        """fork_tape with Nothing generates a random fork name."""
        tape_name = "source"
        
        args = [
            VPrim(tape_name),
            VData(0, []),  # Nothing
        ]
        
        result = bub_ops._tape_fork(args, mock_session)
        assert isinstance(result, VAsync)
        
        val = await result.val
        assert isinstance(val, VPrim)
        assert val.val.startswith("source/fork_")
        mock_agent.tapes.fork_tape.assert_called_once()


def _tape_info(*, entries_since_last_anchor: int = 0, anchors: int = 0):
    """Build a TapeInfo-shaped mock for agent.tapes.info()."""
    info = MagicMock()
    info.entries_since_last_anchor = entries_since_last_anchor
    info.anchors = anchors
    return info


class TestNeedsCompact:
    """Tests for _needs_compact primitive."""

    @pytest.mark.asyncio
    async def test_returns_true_above_threshold(self, bub_ops, mock_agent, mock_session):
        """needs_compact returns TRUE when entries since last anchor exceed threshold."""
        from bub_sf.bub_ext import COMPACT_THRESHOLD_ENTRIES

        mock_agent.tapes.info = AsyncMock(
            return_value=_tape_info(entries_since_last_anchor=COMPACT_THRESHOLD_ENTRIES + 1)
        )
        args = [VPrim("some-tape")]

        result = bub_ops._needs_compact(args, mock_session)
        assert isinstance(result, VAsync)

        val = await result.val
        assert val == bi.TRUE_VAL
        mock_agent.tapes.info.assert_called_once_with("some-tape")

    @pytest.mark.asyncio
    async def test_returns_false_at_or_below_threshold(self, bub_ops, mock_agent, mock_session):
        """needs_compact returns FALSE when entries since last anchor are within threshold."""
        from bub_sf.bub_ext import COMPACT_THRESHOLD_ENTRIES

        mock_agent.tapes.info = AsyncMock(
            return_value=_tape_info(entries_since_last_anchor=COMPACT_THRESHOLD_ENTRIES)
        )
        args = [VPrim("some-tape")]

        val = await bub_ops._needs_compact(args, mock_session).val
        assert val == bi.FALSE_VAL


class TestInferiorTape:
    """Tests for _inferior_tape primitive."""

    @pytest.mark.asyncio
    async def test_creates_when_missing(self, bub_ops, mock_agent, mock_session):
        """inferior_tape creates the named child when it does not exist (no anchors)."""
        mock_agent.tapes.info = AsyncMock(return_value=_tape_info(anchors=0))
        args = [
            VLit(LitString("intent")),
            VPrim("session/main"),
        ]

        result = bub_ops._inferior_tape(args, mock_session)
        assert isinstance(result, VAsync)

        val = await result.val
        assert isinstance(val, VPrim)
        assert val.val == "session/main/intent"
        mock_agent.tapes.create.assert_called_once_with("session/main/intent")

    @pytest.mark.asyncio
    async def test_idempotent_when_exists(self, bub_ops, mock_agent, mock_session):
        """inferior_tape does not create when the tape already exists (has bootstrap anchor)."""
        mock_agent.tapes.info = AsyncMock(return_value=_tape_info(anchors=1))
        args = [
            VLit(LitString("intent")),
            VPrim("session/main"),
        ]

        val = await bub_ops._inferior_tape(args, mock_session).val
        assert isinstance(val, VPrim)
        assert val.val == "session/main/intent"
        mock_agent.tapes.create.assert_not_called()
