"""Tests for bub_sf.hook_cli rendering logic."""

from __future__ import annotations

from typing import Any

from republic.tape.entries import TapeEntry

from bub_sf.hook_cli import _render_body


def make_entry(kind: str, payload: dict[str, Any], meta: dict[str, Any] | None = None) -> TapeEntry:
    return TapeEntry(id=0, kind=kind, payload=payload, meta=meta or {}, date="2026-05-05T12:00:00+00:00")


class TestRenderBody:
    def test_message_with_string_content(self) -> None:
        entry = make_entry("message", {"role": "user", "content": "Hello"})
        body = _render_body(entry)
        # Role is now shown in meta table, body is just content
        assert body == "Hello"

    def test_message_with_list_content(self) -> None:
        entry = make_entry("message", {"role": "user", "content": [{"type": "text", "text": "Hello"}]})
        body = _render_body(entry)
        # Role is now shown in meta table, body is just content JSON
        assert '"type": "text"' in body

    def test_message_without_role(self) -> None:
        entry = make_entry("message", {"content": "Hello"})
        body = _render_body(entry)
        assert body == "Hello"

    def test_system(self) -> None:
        entry = make_entry("system", {"content": "Be helpful"})
        body = _render_body(entry)
        assert body == "Be helpful"

    def test_anchor_without_state(self) -> None:
        entry = make_entry("anchor", {"name": "checkpoint"})
        body = _render_body(entry)
        # Name is now shown in meta table, body is empty without state
        assert body == ""

    def test_anchor_with_state(self) -> None:
        entry = make_entry("anchor", {"name": "checkpoint", "state": {"x": 1}})
        body = _render_body(entry)
        # Name is now shown in meta table, body is just state JSON
        assert '"x": 1' in body

    def test_tool_call(self) -> None:
        entry = make_entry("tool_call", {"calls": [{"name": "foo", "arguments": {}}]})
        body = _render_body(entry)
        assert '"name": "foo"' in body

    def test_tool_result(self) -> None:
        entry = make_entry("tool_result", {"results": ["ok"]})
        body = _render_body(entry)
        # String results get compact rendering
        assert "output hidden" in body

    def test_tool_result_json(self) -> None:
        entry = make_entry("tool_result", {"results": [{"x": 1}]})
        body = _render_body(entry)
        # JSON results still show full JSON
        assert '"x": 1' in body

    def test_error(self) -> None:
        entry = make_entry("error", {"kind": "UNKNOWN", "message": "oops"})
        body = _render_body(entry)
        assert '"kind": "UNKNOWN"' in body
        assert '"message": "oops"' in body

    def test_event_without_data(self) -> None:
        entry = make_entry("event", {"name": "start"})
        body = _render_body(entry)
        # Name is now shown in meta table, body is empty without data
        assert body == ""

    def test_event_with_data(self) -> None:
        entry = make_entry("event", {"name": "start", "data": {"step": 1}})
        body = _render_body(entry)
        # Name is now shown in meta table, body is just data JSON
        assert '"step": 1' in body

    def test_unknown_kind(self) -> None:
        entry = make_entry("custom", {"foo": "bar"})
        body = _render_body(entry)
        assert '"foo": "bar"' in body


class TestPrettyJson:
    def test_pretty_json_output(self) -> None:
        from bub_sf.hook_cli import _pretty_json
        result = _pretty_json({"a": 1})
        assert result == '{\n  "a": 1\n}'
