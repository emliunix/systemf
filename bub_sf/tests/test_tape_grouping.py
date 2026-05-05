"""Tests for bub_sf.tape_grouping logic."""

from __future__ import annotations

import pytest
from republic.tape.entries import TapeEntry

from bub_sf.tape_grouping import GroupedEntry, group_entries


def make_entry(entry_id=0, kind="message", payload=None):
    """Create a TapeEntry with sensible defaults for testing."""
    return TapeEntry(
        id=entry_id,
        kind=kind,
        payload=payload or {"role": "user", "content": "hello"},
        date="2026-05-01T12:00:00+00:00",
    )


class TestGroupEntriesEmpty:
    """Edge cases with empty input."""

    def test_empty_list_returns_empty(self):
        assert group_entries([]) == []


class TestGroupEntriesSinglePrimary:
    """Single primary entry with no secondaries."""

    def test_single_message(self):
        entries = [make_entry(0, "message", {"role": "user", "content": "hi"})]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 0
        assert result[0].kind == "message"
        assert result[0].pre == []
        assert result[0].post == []

    def test_single_anchor(self):
        entries = [make_entry(0, "anchor", {"name": "a1"})]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 0
        assert result[0].kind == "anchor"


class TestGroupEntriesPreSecondaries:
    """Secondary entries before a primary become pre entries."""

    def test_system_before_message(self):
        entries = [
            make_entry(0, "system", {"content": "sys prompt"}),
            make_entry(1, "message", {"role": "user", "content": "hi"}),
        ]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].kind == "message"
        assert [e.kind for e in result[0].pre] == ["system"]

    def test_tool_call_before_message(self):
        entries = [
            make_entry(0, "tool_call", {"calls": [{"fn": "foo"}]}),
            make_entry(1, "message", {"role": "assistant", "content": "done"}),
        ]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 1
        assert [e.kind for e in result[0].pre] == ["tool_call"]

    def test_multiple_pre_secondaries(self):
        entries = [
            make_entry(0, "system", {"content": "sys"}),
            make_entry(1, "tool_call", {"calls": [{"fn": "foo"}]}),
            make_entry(2, "tool_result", {"results": ["ok"]}),
            make_entry(3, "message", {"role": "assistant", "content": "done"}),
        ]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 3
        assert [e.kind for e in result[0].pre] == ["system", "tool_call", "tool_result"]


class TestGroupEntriesPostSecondaries:
    """Error and event entries after a primary become post entries."""

    def test_error_after_message(self):
        entries = [
            make_entry(0, "message", {"role": "assistant", "content": "hi"}),
            make_entry(1, "error", {"msg": "oops"}),
        ]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 0
        assert [e.kind for e in result[0].post] == ["error"]

    def test_event_after_message(self):
        entries = [
            make_entry(0, "message", {"role": "assistant", "content": "hi"}),
            make_entry(1, "event", {"name": "done"}),
        ]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 0
        assert [e.kind for e in result[0].post] == ["event"]


class TestGroupEntriesMixed:
    """Complex sequences with pre and post secondaries."""

    def test_tool_chain(self):
        """message → tool_call → tool_result → message."""
        entries = [
            make_entry(0, "message", {"role": "user", "content": "do it"}),
            make_entry(1, "tool_call", {"calls": [{"fn": "foo"}]}),
            make_entry(2, "tool_result", {"results": ["ok"]}),
            make_entry(3, "message", {"role": "assistant", "content": "done"}),
        ]
        result = group_entries(entries)
        assert len(result) == 2
        assert result[0].id == 0
        assert result[0].pre == []
        assert result[0].post == []
        assert result[1].id == 3
        assert [e.kind for e in result[1].pre] == ["tool_call", "tool_result"]

    def test_interleaved_with_error(self):
        """message → tool_call → error → message.

        The error is a post-secondary, so it goes to the preceding primary.
        The tool_call is a pre-secondary for the next primary.
        """
        entries = [
            make_entry(0, "message", {"role": "user", "content": "do it"}),
            make_entry(1, "tool_call", {"calls": [{"fn": "foo"}]}),
            make_entry(2, "error", {"msg": "oops"}),
            make_entry(3, "message", {"role": "assistant", "content": "failed"}),
        ]
        result = group_entries(entries)
        assert len(result) == 2
        assert result[0].id == 0
        assert [e.kind for e in result[0].post] == ["error"]
        assert result[1].id == 3
        assert [e.kind for e in result[1].pre] == ["tool_call"]

    def test_anchor_resets_accumulation(self):
        """Secondary entries before anchor go to the anchor, not the message after."""
        entries = [
            make_entry(0, "system", {"content": "sys"}),
            make_entry(1, "anchor", {"name": "a1"}),
            make_entry(2, "message", {"role": "user", "content": "hi"}),
        ]
        result = group_entries(entries)
        assert len(result) == 2
        assert result[0].id == 1
        assert [e.kind for e in result[0].pre] == ["system"]
        assert result[1].id == 2
        assert result[1].pre == []


class TestGroupEntriesOrphans:
    """Secondary entries with no primary."""

    def test_all_secondary(self):
        entries = [
            make_entry(0, "tool_call", {"calls": [{"fn": "foo"}]}),
            make_entry(1, "tool_result", {"results": ["ok"]}),
        ]
        result = group_entries(entries)
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].kind == "tool_result"
        assert [e.kind for e in result[0].pre] == ["tool_call"]

    def test_trailing_secondaries(self):
        entries = [
            make_entry(0, "message", {"role": "user", "content": "hi"}),
            make_entry(1, "tool_call", {"calls": [{"fn": "foo"}]}),
        ]
        result = group_entries(entries)
        assert len(result) == 2
        assert result[0].id == 0
        assert result[1].id == 1
        assert result[1].kind == "tool_call"
        assert result[1].pre == []


class TestGroupedEntryProperties:
    """Test that GroupedEntry proxies primary properties."""

    def test_property_access(self):
        primary = make_entry(42, "message", {"role": "user", "content": "hi"})
        pre = [make_entry(0, "system", {"content": "sys"})]
        post = [make_entry(99, "error", {"msg": "oops"})]

        grouped = GroupedEntry(primary=primary, pre=pre, post=post)
        assert grouped.id == 42
        assert grouped.kind == "message"
        assert grouped.payload == {"role": "user", "content": "hi"}
        assert grouped.date == primary.date
