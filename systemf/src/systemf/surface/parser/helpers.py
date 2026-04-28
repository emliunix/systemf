"""Parser helper combinators for System F layout-sensitive parsing.

This module provides the core layout-aware parser combinators following
Idris2's approach with explicit constraint passing.

Key design:
- No global state - constraints passed explicitly
- Column-aware token parsing
- Block handling with layout or explicit braces
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple, TypeVar, cast

from parsy import Parser, Result, fail, generate, peek, success

from .types import (
    AfterPos,
    AnyIndent,
    AtPos,
    BarToken,
    DelimiterToken,
    EndOfBlock,
    OperatorToken,
    TokenBase,
    ValidIndent,
)

# Type variable for parsed items
T = TypeVar("T", bound=TokenBase)

type P[T] = Parser[List[TokenBase], T]


# =============================================================================
# Token Matching
# =============================================================================


def match_token(token_cls: type[T]) -> P[T]:
    """Match a token using Python match syntax.

    Args:
        token_cls: Token class to match (e.g., IdentifierToken, PlusToken)

    Returns:
        Parser that returns the matched token
    """

    @Parser
    def parser(tokens: List[TokenBase], index: int) -> Result[T]:
        if index >= len(tokens):
            return Result.failure(index, f"expected {token_cls.__name__}")
        token = tokens[index]
        if isinstance(token, token_cls):
            return Result.success(index + 1, token)
        return Result.failure(index, f"expected {token_cls.__name__}, got {str(token)}")

    return parser


# =============================================================================
# Core Infrastructure
# =============================================================================


def column() -> P[int]:
    """Get the column of the current token.

    Returns a parser that succeeds with the current token's start column.
    Used to capture the reference column for layout blocks.

    Example:
        After parsing `case x of`, call `column()` to get the column
        of the first branch token.
    """

    @Parser
    def parser(tokens: List[TokenBase], index: int) -> Result[int]:
        if index >= len(tokens):
            return Result.failure(index, "expected token")
        token = tokens[index]
        # Return column without consuming token (peek)
        return Result.success(index, token.location.column)

    return parser


def peek_column() -> P[int]:
    """Peek at the column of the next token without consuming it.

    Returns 0 if at end of input (EOF). This is the safe version of
    column() that never fails — it returns 0 at EOF. Used by
    layout-sensitive parsers to check the next token's column before
    deciding whether to continue parsing.
    """

    @Parser
    def parser(tokens: List[TokenBase], index: int) -> Result[int]:
        if index >= len(tokens):
            return Result.success(index, 0)
        token = tokens[index]
        return Result.success(index, token.location.column)

    return parser


def check_valid(constraint: ValidIndent, col: int) -> bool:
    """Check if a column satisfies a constraint.

    Args:
        constraint: The layout constraint to check against
        col: The column number to check

    Returns:
        True if col satisfies the constraint, False otherwise

    Examples:
        >>> check_valid(AnyIndent(), 5)
        True
        >>> check_valid(AtPos(4), 4)
        True
        >>> check_valid(AtPos(4), 5)
        False
    """
    match constraint:
        case AnyIndent():
            return True
        case AtPos() as ap:
            return col == ap.col
        case AfterPos() as apos:
            return col >= apos.col
        case EndOfBlock():
            return False
        case _:
            raise Exception("impossible")


def is_at_constraint(constraint: ValidIndent, col: int) -> bool:
    """Check if a column is exactly at the constraint position.

    Like check_valid but specifically for exact match.
    Useful for determining if we're at a new item vs continuation.

    Args:
        constraint: The layout constraint
        col: Column to check

    Returns:
        True if col matches constraint's exact position

    Example:
        >>> is_at_constraint(AtPos(4), 4)
        True
        >>> is_at_constraint(AtPos(4), 5)
        False
    """
    match constraint:
        case AnyIndent():
            return True
        case AtPos() as ap:
            return col == ap.col
        case AfterPos() as apos:
            return col == apos.col
        case EndOfBlock():
            return False
    return False


def get_indent_info(token: TokenBase) -> int:
    """Extract column (indentation info) from a token.

    Args:
        token: Any token with location info

    Returns:
        The token's start column

    Example:
        >>> get_indent_info(ident_token)
        4
    """
    return token.location.column


# =============================================================================
# Block Parsing Combinators
# =============================================================================


def block(item: Callable[[ValidIndent], P[T]]) -> P[List[T]]:
    """Parse a block that can be either explicit braces or layout-indented.

    Tries to parse:
    1. Explicit braces: `{ item; item; ... }` (uses AnyIndent)
    2. Layout mode: indented block starting at current position (uses AtPos)

    In layout mode:
    - Captures column of first token as reference
    - All subsequent items must be at that exact column
    - Block ends when token is at or before reference column

    Args:
        item: A parser that takes a ValidIndent constraint and returns T

    Returns:
        A parser that returns a list of parsed items

    Examples:
        >>> block(branch_parser).parse("{ A -> 1; B -> 2 }")
        [Branch(...), Branch(...)]

        >>> block(branch_parser).parse("A -> 1\nB -> 2")  # At same column
        [Branch(...), Branch(...)]
    """

    @Parser
    def parser(tokens: List[TokenBase], index: int) -> Result[List[T]]:
        # Check for explicit braces first
        if index < len(tokens):
            tok = tokens[index]
            if isinstance(tok, DelimiterToken) and tok.delimiter == "{":
                # Brace mode: use AnyIndent
                # Skip the opening brace
                entries_result = block_entries(AnyIndent(), item)(tokens, index + 1)
                if not entries_result.status:
                    return entries_result

                # Check for closing brace (but don't require it - just consume if present)
                next_idx = entries_result.index
                if next_idx < len(tokens):
                    close_tok = tokens[next_idx]
                    if isinstance(close_tok, DelimiterToken) and close_tok.delimiter == "}":
                        next_idx += 1

                return Result.success(next_idx, entries_result.value)

        # Layout mode: capture current column
        if index >= len(tokens):
            # Empty stream, return empty list
            return Result.success(index, [])

        # Get column of first token
        start_col = tokens[index].location.column

        # Use block_entries with AtPos constraint
        entries_result = block_entries(AtPos(col=start_col), item)(tokens, index)

        if entries_result.status:
            return entries_result
        else:
            # If entries failed to parse, return empty list
            return Result.success(index, [])

    return parser


def block_entries(constraint: ValidIndent, item: Callable[[ValidIndent], P[T]]) -> P[List[T]]:
    """Parse zero or more items with the given column constraint.

    Continues parsing items until:
    - Explicit terminator found (`}` or `;` in braces mode)
    - Token at/before start column found (layout mode)
    - End of input

    Args:
        constraint: The ValidIndent constraint for items
        item: Parser that takes constraint and returns T

    Returns:
        Parser returning list of zero or more items

    Example:
        >>> block_entries(AtPos(4), binding_parser).parse("x = 1\ny = 2")
        [Binding(...), Binding(...)]  # Both at column 4
    """

    @Parser
    def parser(tokens: List[TokenBase], index: int) -> Result[List[T]]:
        results: List[T] = []
        current_index = index
        current_constraint = constraint

        while current_index < len(tokens):
            # Check if constraint is EndOfBlock - stop parsing
            match current_constraint:
                case EndOfBlock():
                    break

            # Try to parse one entry
            entry_result = block_entry(current_constraint, item)(tokens, current_index)

            if not entry_result.status:
                # Entry failed to parse - stop here
                break

            # Entry parsed successfully
            parsed_value, updated_constraint = entry_result.value
            results.append(parsed_value)
            current_index = entry_result.index
            current_constraint = updated_constraint

        return Result.success(current_index, results)

    return parser


def block_entry(
    constraint: ValidIndent, item: Callable[[ValidIndent], P[T]]
) -> P[Tuple[T, ValidIndent]]:
    """Parse a single item and check its column against constraint.

    Args:
        constraint: Column constraint the item must satisfy
        item: Parser for the item (receives constraint)

    Returns:
        Tuple of (parsed_item, updated_constraint)

    Raises:
        ParseError: If item's column doesn't satisfy constraint

    Example:
        >>> block_entry(AtPos(4), ident_parser).parse("x")
        (Ident('x'), AtPos(4))
    """

    @Parser
    def parser(tokens: List[TokenBase], index: int) -> Result[Tuple[T, ValidIndent]]:
        if index >= len(tokens):
            return Result.failure(index, "expected block entry")

        token = tokens[index]
        col = token.location.column

        # Check if column satisfies constraint
        if not check_valid(constraint, col):
            return Result.failure(index, f"invalid indentation at column {col}")

        # Parse the item using the provided parser
        item_result = item(constraint)(tokens, index)

        if not item_result.status:
            return cast(Any, item_result)

        # Get the next index after parsing the item
        next_index = item_result.index

        # Call terminator to get updated constraint
        term_result = terminator(constraint, col)(tokens, next_index)

        if not term_result.status:
            return cast(Result[Tuple[T, ValidIndent]], term_result)

        updated_constraint = term_result.value

        return Result.success(term_result.index, (item_result.value, updated_constraint))

    return parser


# =============================================================================
# Terminators and Validation
# =============================================================================


def terminator(constraint: ValidIndent, start_col: int) -> P[ValidIndent]:
    """Check for block terminators and return updated constraint.

    In braces mode:
    - `;` found: continue with AfterPos constraint
    - `}` found: return EndOfBlock

    In layout mode:
    - Token at column <= start_col: end block (return EndOfBlock)
    - Token at column > start_col: continuation (return same constraint)

    Args:
        constraint: Current layout constraint
        start_col: Starting column of the block

    Returns:
        Updated constraint for next entry

    Example:
        >>> terminator(AtPos(4), 4).parse("")  # At same column
        AtPos(4)

        >>> terminator(AtPos(4), 4).parse("end")  # At column 0
        EndOfBlock()
    """

    @Parser
    def parser(tokens: List[TokenBase], index: int) -> Result[ValidIndent]:
        # At EOF, block ends - consume nothing (at end)
        if index >= len(tokens):
            return Result.success(index, EndOfBlock())

        token = tokens[index]

        # Check for semicolon - consume it and continue with AfterPos
        if isinstance(token, OperatorToken) and token.operator == ";":
            match constraint:
                case AnyIndent():
                    return Result.success(index + 1, AnyIndent())
                case AtPos() as ap:
                    return Result.success(index + 1, AfterPos(col=ap.col))
                case AfterPos() as apos:
                    return Result.success(index + 1, AfterPos(col=apos.col))
                case EndOfBlock():
                    return Result.success(index + 1, EndOfBlock())

        # Check for bar (|) - case branch separator in braces mode
        match token:
            case BarToken():
                # Consume the bar and continue with same constraint
                match constraint:
                    case AnyIndent():
                        return Result.success(index + 1, AnyIndent())
                    case AtPos() as ap:
                        return Result.success(index + 1, AtPos(col=ap.col))
                    case AfterPos() as apos:
                        return Result.success(index + 1, AfterPos(col=apos.col))
                    case EndOfBlock():
                        return Result.success(index + 1, EndOfBlock())

        # Check for close brace - don't consume, just return EndOfBlock
        # (the caller will consume the brace if needed)
        if isinstance(token, DelimiterToken) and token.delimiter == "}":
            return Result.success(index, EndOfBlock())

        # Check column position
        col = token.location.column

        # Layout mode column handling (matching Idris2 behavior):
        # AtPos(c): col == c -> continue with AtPos(c) (new item at same column)
        #          col < c  -> EndOfBlock (dedented past reference)
        # AfterPos(c): col <= c -> switch to AtPos(c) (back to exact column)
        #             col > c  -> continue with AfterPos(c)
        match constraint:
            case AtPos() as ap:
                if col < ap.col:
                    # Strictly dedented - block ends
                    return Result.success(index, EndOfBlock())
                elif col == ap.col:
                    # Same column - new item in block, continue with same constraint
                    return Result.success(index, AtPos(col=ap.col))
                else:
                    # Further indented - continuation, same constraint
                    return Result.success(index, AtPos(col=ap.col))
            case AfterPos() as apos:
                if col <= apos.col:
                    # At or before reference - switch back to exact column
                    return Result.success(index, AtPos(col=apos.col))
                else:
                    # After reference - continue with AfterPos
                    return Result.success(index, AfterPos(col=apos.col))
            case AnyIndent():
                # In braces mode, any column is fine
                return Result.success(index, AnyIndent())
            case EndOfBlock():
                return Result.success(index, EndOfBlock())

        # Default: continue with same constraint
        return Result.success(index, constraint)

    return parser


def must_continue(constraint: ValidIndent, expected: Optional[str] = None) -> P[None]:
    """Verify we're still within the block and haven't hit a terminator.

    Used after keywords or between items to ensure layout hasn't ended
    unexpectedly.

    Args:
        constraint: Current constraint
        expected: Optional description of what we expected to find

    Raises:
        ParseError: If constraint is EndOfBlock

    Example:
        >>> must_continue(AtPos(4), "binding").parse("x")
        None  # Success, we're still in block
    """

    @Parser
    def parser(tokens: list, index: int) -> Result:
        match constraint:
            case EndOfBlock():
                if expected:
                    msg = f"Unexpected end of expression (expected '{expected}')"
                else:
                    msg = "Unexpected end of expression"
                return Result.failure(index, msg)
            case _:
                # AtPos, AfterPos, AnyIndent all succeed
                return Result.success(index, None)

    return parser


__all__ = [
    # Token matching
    "match_token",
    # Core infrastructure
    "column",
    "peek_column",
    "check_valid",
    "is_at_constraint",
    "get_indent_info",
    # Block combinators
    "block",
    "block_entries",
    "block_entry",
    # Terminators
    "terminator",
    "must_continue",
]
