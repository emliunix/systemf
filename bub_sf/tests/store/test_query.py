"""Tests for query AST pretty-printer and query builders."""

from __future__ import annotations

import pytest
from republic.core.errors import ErrorKind, RepublicError
from republic.tape.query import TapeQuery

from bub_sf.store.query import (
    Adj,
    BuildQuery,
    Cond,
    Disj,
    _after_anchor,
    _between_anchors,
    _between_dates,
    _in_kinds,
    _text_query,
    collect_params,
    pp_ast,
)


# ---------------------------------------------------------------------------
# pp_ast – precedence / pretty printing
# ---------------------------------------------------------------------------

def test_pp_cond():
    """A bare condition prints as-is."""
    assert pp_ast(Cond("x = 1", [])) == "x = 1"


def test_pp_adj():
    """Two conditions joined by AND – no parens at top level."""
    ast = Adj(Cond("x = 1", []), Cond("y = 2", []))
    assert pp_ast(ast) == "x = 1 AND y = 2"


def test_pp_disj():
    """Two conditions joined by OR – no parens at top level."""
    ast = Disj(Cond("x = 1", []), Cond("y = 2", []))
    assert pp_ast(ast) == "x = 1 OR y = 2"


def test_or_inside_and_gets_parens():
    """OR has lower precedence than AND, so it must be parenthesised."""
    ast = Adj(
        Disj(Cond("a = 1", []), Cond("b = 2", [])),
        Cond("c = 3", []),
    )
    assert pp_ast(ast) == "(a = 1 OR b = 2) AND c = 3"


def test_and_inside_or_no_extra_parens():
    """AND has higher precedence than OR – no extra parens needed."""
    ast = Disj(
        Adj(Cond("a = 1", []), Cond("b = 2", [])),
        Cond("c = 3", []),
    )
    assert pp_ast(ast) == "a = 1 AND b = 2 OR c = 3"


def test_deep_left_assoc():
    """Left-associative tree of three ANDs – same precedence, no parens."""
    ast = Adj(
        Adj(Cond("a = 1", []), Cond("b = 2", [])),
        Cond("c = 3", []),
    )
    assert pp_ast(ast) == "a = 1 AND b = 2 AND c = 3"


def test_deep_right_assoc():
    """Right-associative tree of three ANDs – right operand gets parens."""
    ast = Adj(
        Cond("a = 1", []),
        Adj(Cond("b = 2", []), Cond("c = 3", [])),
    )
    assert pp_ast(ast) == "a = 1 AND (b = 2 AND c = 3)"


def test_mixed_complex():
    """Mix of AND and OR with multiple nesting levels."""
    ast = Disj(
        Adj(
            Cond("a = 1", []),
            Disj(Cond("b = 2", []), Cond("c = 3", [])),
        ),
        Adj(Cond("d = 4", []), Cond("e = 5", [])),
    )
    assert pp_ast(ast) == "a = 1 AND (b = 2 OR c = 3) OR d = 4 AND e = 5"


# ---------------------------------------------------------------------------
# collect_params
# ---------------------------------------------------------------------------

def test_collect_params_empty():
    """Empty params list from bare condition."""
    assert collect_params(Cond("x = 1", [])) == []


def test_collect_params_single():
    """Single param from condition."""
    assert collect_params(Cond("x = ?", [42])) == [42]


def test_collect_params_adj():
    """Params collected left-to-right from Adj."""
    ast = Adj(Cond("a = ?", [1]), Cond("b = ?", [2]))
    assert collect_params(ast) == [1, 2]


def test_collect_params_disj():
    """Params collected left-to-right from Disj."""
    ast = Disj(Cond("a = ?", [1]), Cond("b = ?", [2]))
    assert collect_params(ast) == [1, 2]


def test_collect_params_nested():
    """Params collected in DFS order."""
    ast = Adj(
        Cond("a = ?", [1]),
        Disj(Cond("b = ?", [2]), Cond("c = ?", [3])),
    )
    assert collect_params(ast) == [1, 2, 3]


# ---------------------------------------------------------------------------
# Individual builders
# ---------------------------------------------------------------------------

def test_in_kinds_empty():
    """Empty kinds returns empty params."""
    ast = _in_kinds(())
    assert pp_ast(ast) == "kind IN ()"
    assert collect_params(ast) == []


def test_in_kinds_single():
    """Single kind."""
    ast = _in_kinds(("message",))
    assert pp_ast(ast) == "kind IN (?)"
    assert collect_params(ast) == ["message"]


def test_in_kinds_multiple():
    """Multiple kinds."""
    ast = _in_kinds(("message", "event"))
    assert pp_ast(ast) == "kind IN (?,?)"
    assert collect_params(ast) == ["message", "event"]


def test_after_anchor():
    """After anchor produces entry_id > ?."""
    ast = _after_anchor(42)
    assert pp_ast(ast) == "entry_id > ?"
    assert collect_params(ast) == [42]


def test_between_anchors():
    """Between anchors produces range condition."""
    ast = _between_anchors(10, 20)
    assert pp_ast(ast) == "entry_id > ? AND entry_id < ?"
    assert collect_params(ast) == [10, 20]


def test_between_dates():
    """Between dates produces BETWEEN condition."""
    ast = _between_dates("2024-01-01", "2024-12-31")
    assert pp_ast(ast) == "date BETWEEN ? AND ?"
    assert collect_params(ast) == ["2024-01-01", "2024-12-31"]


def test_text_query():
    """Text query produces LIKE condition."""
    ast = _text_query("hello")
    assert pp_ast(ast) == "payload LIKE ?"
    assert collect_params(ast) == ["%hello%"]


# ---------------------------------------------------------------------------
# BuildQuery
# ---------------------------------------------------------------------------

class MockBuildQuery(BuildQuery):
    """Mock implementation for testing BuildQuery.build()."""

    def __init__(self, anchors_map: dict[str, int | None] = None, last: int | None = None):
        self._anchors = anchors_map or {}
        self._last = last

    async def anchors(self, tape_id: int, names: list[str]) -> list[int | None]:
        return [self._anchors.get(name) for name in names]

    async def last_anchor(self, tape_id: int) -> int | None:
        return self._last

    async def tape_id(self, tape_name: str) -> int | None:
        return 1  # Mock tape_id always returns 1


@pytest.mark.asyncio
async def test_build_empty_query():
    """Empty query still has tape_name condition."""
    builder = MockBuildQuery()
    query = TapeQuery(tape="test", store=None)
    sql, params = await builder.build(query)
    assert sql == "leaf_tape_id = ?"
    assert params == [1]


@pytest.mark.asyncio
async def test_build_kinds_only():
    """Query with kinds only."""
    builder = MockBuildQuery()
    query = TapeQuery(tape="test", store=None).kinds("message", "event")
    sql, params = await builder.build(query)
    assert "leaf_tape_id = ?" in sql
    assert "kind IN" in sql
    assert params == [1, "message", "event"]


@pytest.mark.asyncio
async def test_build_after_anchor():
    """Query with after_anchor."""
    builder = MockBuildQuery(anchors_map={"start": 10})
    query = TapeQuery(tape="test", store=None).after_anchor("start")
    sql, params = await builder.build(query)
    assert "entry_id > ?" in sql
    assert params == [1, 10]


@pytest.mark.asyncio
async def test_build_after_last():
    """Query with after_last."""
    builder = MockBuildQuery(last=99)
    query = TapeQuery(tape="test", store=None).last_anchor()
    sql, params = await builder.build(query)
    assert "entry_id > ?" in sql
    assert params == [1, 99]


@pytest.mark.asyncio
async def test_build_between_anchors():
    """Query with between_anchors."""
    builder = MockBuildQuery(anchors_map={"start": 10, "end": 20})
    query = TapeQuery(tape="test", store=None).between_anchors("start", "end")
    sql, params = await builder.build(query)
    assert "entry_id > ? AND entry_id < ?" in sql
    assert params == [1, 10, 20]


@pytest.mark.asyncio
async def test_build_between_dates():
    """Query with between_dates."""
    builder = MockBuildQuery()
    query = TapeQuery(tape="test", store=None).between_dates("2024-01-01", "2024-12-31")
    sql, params = await builder.build(query)
    assert "date BETWEEN ? AND ?" in sql
    assert params == [1, "2024-01-01", "2024-12-31"]


@pytest.mark.asyncio
async def test_build_text_query():
    """Query with text search."""
    builder = MockBuildQuery()
    query = TapeQuery(tape="test", store=None).query("hello")
    sql, params = await builder.build(query)
    assert "payload LIKE ?" in sql
    assert params == [1, "%hello%"]


@pytest.mark.asyncio
async def test_build_combined():
    """Query with multiple filters combined."""
    builder = MockBuildQuery(anchors_map={"start": 10})
    query = (
        TapeQuery(tape="test", store=None)
        .kinds("message")
        .after_anchor("start")
        .between_dates("2024-01-01", "2024-12-31")
        .query("hello")
    )
    sql, params = await builder.build(query)
    assert "leaf_tape_id = ?" in sql
    assert "kind IN" in sql
    assert "entry_id > ?" in sql
    assert "date BETWEEN" in sql
    assert "payload LIKE" in sql
    assert params == [1, "message", 10, "2024-01-01", "2024-12-31", "%hello%"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_after_anchor_not_found():
    """Missing anchor raises RepublicError."""
    builder = MockBuildQuery(anchors_map={})
    query = TapeQuery(tape="test", store=None).after_anchor("missing")
    with pytest.raises(RepublicError) as exc_info:
        await builder.build(query)
    assert exc_info.value.kind == ErrorKind.NOT_FOUND
    assert "missing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_build_after_last_no_anchors():
    """No anchors raises RepublicError."""
    builder = MockBuildQuery(last=None)
    query = TapeQuery(tape="test", store=None).last_anchor()
    with pytest.raises(RepublicError) as exc_info:
        await builder.build(query)
    assert exc_info.value.kind == ErrorKind.NOT_FOUND
    assert "No anchors" in str(exc_info.value)


@pytest.mark.asyncio
async def test_build_between_anchors_start_missing():
    """Missing start anchor raises RepublicError."""
    builder = MockBuildQuery(anchors_map={"start": None, "end": 20})
    query = TapeQuery(tape="test", store=None).between_anchors("start", "end")
    with pytest.raises(RepublicError) as exc_info:
        await builder.build(query)
    assert exc_info.value.kind == ErrorKind.NOT_FOUND
    assert "start" in str(exc_info.value)


@pytest.mark.asyncio
async def test_build_between_anchors_end_missing():
    """Missing end anchor raises RepublicError."""
    builder = MockBuildQuery(anchors_map={"start": 10, "end": None})
    query = TapeQuery(tape="test", store=None).between_anchors("start", "end")
    with pytest.raises(RepublicError) as exc_info:
        await builder.build(query)
    assert exc_info.value.kind == ErrorKind.NOT_FOUND
    assert "end" in str(exc_info.value)


@pytest.mark.asyncio
async def test_build_between_anchors_both_missing():
    """Both anchors missing raises RepublicError."""
    builder = MockBuildQuery(anchors_map={"start": None, "end": None})
    query = TapeQuery(tape="test", store=None).between_anchors("start", "end")
    with pytest.raises(RepublicError) as exc_info:
        await builder.build(query)
    assert exc_info.value.kind == ErrorKind.NOT_FOUND
