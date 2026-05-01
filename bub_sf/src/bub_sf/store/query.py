from abc import ABC, abstractmethod
from dataclasses import dataclass
import functools
from typing import Any, Callable 
from collections.abc import Iterable

from republic.core.errors import ErrorKind, RepublicError
from republic.tape.entries import TapeEntry
from republic.tape.query import TapeQuery, T


@dataclass
class Cond:
    cond: str
    params: list[Any]

@dataclass
class Adj:
    left: Ast
    right: Ast

@dataclass
class Disj:
    left: Ast
    right: Ast

Ast = Cond | Adj | Disj


def _in_kinds(kinds: tuple[str, ...]) -> Ast:
    """Build condition for kind IN (...)."""
    placeholders = ",".join("?" for _ in kinds)
    return Cond(f"kind IN ({placeholders})", list(kinds))


def _after_anchor(anchor_id: int) -> Ast:
    """Build condition for entries after an anchor.
    
    anchor_info: (tape_id, entry_id) or None if not found.
    """
    return Cond(
        "entry_id > ?",
        [anchor_id]
    )


def _between_anchors(
    start_id: int,
    end_id: int,
) -> Ast:
    """Build condition for entries between two anchors (exclusive)."""
    return Adj(
        Cond("entry_id > ?", [start_id]),
        Cond("entry_id < ?", [end_id])
    )


def _between_dates(start_date: str, end_date: str) -> Ast:
    """Build condition for entries between two dates (inclusive)."""
    return Cond(
        "date BETWEEN ? AND ?",
        [start_date, end_date]
    )


def _text_query(query_str: str) -> Ast:
    """Build condition for text search on payload."""
    return Cond(
        "payload LIKE ?",
        [f"%{query_str}%"]
    )


def collect_params(ast: Ast) -> list:
    """Traverse AST and collect all parameters in order."""
    params = []
    
    def _traverse(node: Ast) -> None:
        match node:
            case Cond():
                params.extend(node.params)
            case Adj():
                _traverse(node.left)
                _traverse(node.right)
            case Disj():
                _traverse(node.left)
                _traverse(node.right)
    _traverse(ast)
    return params


def pp_ast(ast: Ast) -> str:
    
    def _inner(ast: Ast) -> tuple[int, str]:
        if isinstance(ast, Cond):
            return 4, ast.cond
        elif isinstance(ast, Adj):
            return 2, f"{_pp(2, ast.left)} AND {_pp(3, ast.right)}"
        elif isinstance(ast, Disj):
            return 0, f"{_pp(0, ast.left)} OR {_pp(1, ast.right)}"
    
    def _pp(prec: int, ast: Ast) -> str:
        inner_prec, s = _inner(ast)
        if inner_prec < prec:
            return f"({s})"
        else:
            return s
    
    return _pp(0, ast)


class BuildQuery(ABC):

    @abstractmethod
    async def anchors(self, tape_id: int, names: list[str]) -> list[int | None]: 
        """:return: list of (tape_id, entry_id) | None for each anchor name"""
        ...

    @abstractmethod
    async def last_anchor(self, tape_id: int) -> int | None:
        """:return: the last anchor as (tape_id, entry_id) or None if no anchors exist"""
        ...

    @abstractmethod
    async def tape_id(self, tape_name: str) -> int | None:
        """:return: tape_id for given tape_name, or None if tape does not exist"""
        ...

    async def build(self, query: TapeQuery[T]) -> tuple[str, list[Any]]:
        """
        Build SQL conditions and post-processor from TapeQuery.
        
        :return: ((sql_where_clause, params) | None, post_processor)
        """
        conditions: list[Ast] = []
        
        tape_id = await self.tape_id(query.tape)
        if tape_id is None:
            raise RepublicError(ErrorKind.NOT_FOUND, f"Tape '{query.tape}' was not found.")
        # tape condition
        conditions.append(Cond("leaf_tape_id = ?", [tape_id]))
        
        # kinds filter
        if query._kinds:
            conditions.append(_in_kinds(query._kinds))
        
        # after_anchor filter
        if query._after_anchor is not None:
            match await self.anchors(tape_id, [query._after_anchor]):
                case [int() as anchor_id]:
                    conditions.append(_after_anchor(anchor_id))
                case _:
                    raise RepublicError(ErrorKind.NOT_FOUND, f"Anchor '{query._after_anchor}' was not found.")
        
        # after_last filter
        if query._after_last:
            match await self.last_anchor(tape_id):
                case int() as anchor_id:
                    conditions.append(_after_anchor(anchor_id))
                case None:
                    raise RepublicError(ErrorKind.NOT_FOUND, "No anchors found in tape.")
        
        # between_anchors filter
        if query._between_anchors is not None:
            start_name, end_name = query._between_anchors
            match await self.anchors(tape_id, list(query._between_anchors)):
                case [int() as start_id, int() as end_id]:
                    conditions.append(_between_anchors(start_id, end_id))
                case [None, None]:
                    raise RepublicError(ErrorKind.NOT_FOUND, f"Anchors '{start_name}' and '{end_name}' were not found.")
                case [None, _]:
                    raise RepublicError(ErrorKind.NOT_FOUND, f"Anchor '{start_name}' was not found.")
                case [_, None]:
                    raise RepublicError(ErrorKind.NOT_FOUND, f"Anchor '{end_name}' was not found.")
        
        # between_dates filter
        if query._between_dates is not None:
            start_date, end_date = query._between_dates
            conditions.append(_between_dates(start_date, end_date))
        
        # text query filter
        if query._query:
            conditions.append(_text_query(query._query))
        
        ast = functools.reduce(lambda acc, cond: Adj(acc, cond), conditions)
        sql_cond = pp_ast(ast)
        params = collect_params(ast)
        
        return (sql_cond, params)
