"""Parser types for System F surface language.

This module contains all types used by the parser including:
- Layout constraint types
- Token types
- Lexer-related types
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from systemf.utils.location import Location

# =============================================================================
# Layout Constraint Types
# =============================================================================


@dataclass(frozen=True, kw_only=True)
class AnyIndent:
    """Inside braces, no column checking.

    Used when parsing explicit brace-delimited blocks like:
    { item1; item2; item3 }
    """

    pass


@dataclass(frozen=True, kw_only=True)
class AtPos:
    """Must be at exact column.

    Used for layout mode where all items must align:
      item1
      item2  <- must be at same column as item1
    """

    col: int


@dataclass(frozen=True, kw_only=True)
class AfterPos:
    """At or after column.

    Used when items must be indented past a minimum:
      parent
        child1  <- must be at col >= parent's col
        child2
    """

    col: int


@dataclass(frozen=True, kw_only=True)
class EndOfBlock:
    """Block has ended.

    Returned by terminator when block should close.
    Any check against EndOfBlock fails.
    """

    pass


# Union type for all layout constraints
ValidIndent = AnyIndent | AtPos | AfterPos | EndOfBlock


# =============================================================================
# Token Types
# =============================================================================


class Token(Protocol):
    """Protocol for all tokens.

    All token types implement this protocol with type and value properties
    for pattern matching compatibility.
    """

    @property
    def location(self) -> Location:
        """Get the source location of this token."""
        ...


@dataclass(frozen=True, kw_only=True)
class TokenBase:
    """Base class for all tokens with location information."""

    location: Location

    @property
    def column(self) -> int:
        return self.location.column

    @property
    def line(self) -> int:
        return self.location.line

    def __str__(self) -> str:
        raise NotImplementedError("TokenBase is abstract, use concrete token types")


@dataclass(frozen=True, kw_only=True)
class IdentifierToken(TokenBase):
    """Identifier token (lowercase or underscore start)."""

    name: str

    @property
    def value(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, kw_only=True)
class NumberToken(TokenBase):
    """Numeric literal token."""

    number: str

    @property
    def value(self) -> str:
        return self.number

    def __str__(self) -> str:
        return self.number


@dataclass(frozen=True, kw_only=True)
class StringToken(TokenBase):
    """String literal token."""

    string: str

    @property
    def value(self) -> str:
        return self.string

    def __str__(self) -> str:
        return self.string


@dataclass(frozen=True, kw_only=True)
class KeywordToken(TokenBase):
    """Base class for keyword tokens (data, let, in, case, of, forall, type).

    Subclasses should override the type property.
    """

    keyword: str

    @property
    def value(self) -> str:
        return self.keyword

    def __str__(self) -> str:
        return self.keyword


# Specific keyword token classes


@dataclass(frozen=True, kw_only=True)
class LambdaToken(TokenBase):
    """Lambda token (small lambda)."""

    symbol: str

    @property
    def value(self) -> str:
        return self.symbol

    def __str__(self) -> str:
        return self.symbol


@dataclass(frozen=True, kw_only=True)
class DataToken(KeywordToken):
    """Data declaration keyword: data"""

    pass


@dataclass(frozen=True, kw_only=True)
class LetToken(KeywordToken):
    """Let binding keyword: let"""

    pass


@dataclass(frozen=True, kw_only=True)
class InToken(KeywordToken):
    """In keyword for let bindings"""

    pass


@dataclass(frozen=True, kw_only=True)
class CaseToken(KeywordToken):
    """Case expression keyword: case"""

    pass


@dataclass(frozen=True, kw_only=True)
class OfToken(KeywordToken):
    """Of keyword for case expressions"""

    pass


@dataclass(frozen=True, kw_only=True)
class ForallToken(KeywordToken):
    """Forall keyword (universal quantifier)."""

    pass


@dataclass(frozen=True, kw_only=True)
class TypeToken(KeywordToken):
    """Type declaration keyword: type"""

    pass


@dataclass(frozen=True, kw_only=True)
class IfToken(KeywordToken):
    """If keyword: if"""

    pass


@dataclass(frozen=True, kw_only=True)
class ThenToken(KeywordToken):
    """Then keyword: then"""

    pass


@dataclass(frozen=True, kw_only=True)
class ElseToken(KeywordToken):
    """Else keyword: else"""

    pass


@dataclass(frozen=True, kw_only=True)
class PrimTypeToken(KeywordToken):
    """Primitive type keyword: prim_type"""

    pass


@dataclass(frozen=True, kw_only=True)
class PrimOpToken(KeywordToken):
    """Primitive operator keyword: prim_op"""

    pass


@dataclass(frozen=True, kw_only=True)
class ImportToken(KeywordToken):
    """Import keyword: import"""

    pass


@dataclass(frozen=True, kw_only=True)
class QualifiedToken(KeywordToken):
    """Qualified keyword: qualified"""

    pass


@dataclass(frozen=True, kw_only=True)
class AsToken(KeywordToken):
    """As keyword: as"""

    pass


@dataclass(frozen=True, kw_only=True)
class HidingToken(KeywordToken):
    """Hiding keyword: hiding"""

    pass


class DocstringType:
    """Docstring type constants."""

    PRECEDING = "DOCSTRING_PRECEDING"
    FOLLOWING = "DOCSTRING_FOLLOWING"


class TokenType:
    """General token type constants."""

    PRAGMA = "PRAGMA"
    LAMBDA = "LAMBDA"


class OperatorToken(TokenBase):
    """Base class for operator tokens."""

    operator: str

    @property
    def value(self) -> str:
        return self.operator

    def __str__(self) -> str:
        return self.operator


# Concrete operator token classes (one-liner style)
@dataclass(frozen=True, kw_only=True)
class ArrowToken(OperatorToken):
    operator: str = "->"


@dataclass(frozen=True, kw_only=True)
class DarrowToken(OperatorToken):
    operator: str = "=>"


@dataclass(frozen=True, kw_only=True)
class EqToken(OperatorToken):
    operator: str = "=="


@dataclass(frozen=True, kw_only=True)
class NeToken(OperatorToken):
    operator: str = "/="


@dataclass(frozen=True, kw_only=True)
class LtToken(OperatorToken):
    operator: str = "<"


@dataclass(frozen=True, kw_only=True)
class GtToken(OperatorToken):
    operator: str = ">"


@dataclass(frozen=True, kw_only=True)
class LeToken(OperatorToken):
    operator: str = "<="


@dataclass(frozen=True, kw_only=True)
class GeToken(OperatorToken):
    operator: str = ">="


@dataclass(frozen=True, kw_only=True)
class PlusToken(OperatorToken):
    operator: str = "+"


@dataclass(frozen=True, kw_only=True)
class MinusToken(OperatorToken):
    operator: str = "-"


@dataclass(frozen=True, kw_only=True)
class StarToken(OperatorToken):
    operator: str = "*"


@dataclass(frozen=True, kw_only=True)
class SlashToken(OperatorToken):
    operator: str = "/"


@dataclass(frozen=True, kw_only=True)
class AndToken(OperatorToken):
    operator: str = "&&"


@dataclass(frozen=True, kw_only=True)
class OrToken(OperatorToken):
    operator: str = "||"


@dataclass(frozen=True, kw_only=True)
class AppendToken(OperatorToken):
    operator: str = "++"


@dataclass(frozen=True, kw_only=True)
class EqualsToken(OperatorToken):
    operator: str = "="


@dataclass(frozen=True, kw_only=True)
class ColonToken(OperatorToken):
    operator: str = ":"


@dataclass(frozen=True, kw_only=True)
class DoubleColonToken(OperatorToken):
    operator: str = "::"


@dataclass(frozen=True, kw_only=True)
class BarToken(OperatorToken):
    operator: str = "|"


@dataclass(frozen=True, kw_only=True)
class AtToken(OperatorToken):
    operator: str = "@"


@dataclass(frozen=True, kw_only=True)
class DotToken(OperatorToken):
    operator: str = "."


@dataclass(frozen=True, kw_only=True)
class SemicolonToken(OperatorToken):
    operator: str = ";"


# Delimiter token base class and concrete classes
@dataclass(frozen=True, kw_only=True)
class DelimiterToken(TokenBase):
    """Base class for delimiter tokens."""

    delimiter: str

    @property
    def value(self) -> str:
        return self.delimiter

    def __str__(self) -> str:
        return self.delimiter


@dataclass(frozen=True, kw_only=True)
class LeftParenToken(DelimiterToken):
    delimiter: str = "("


@dataclass(frozen=True, kw_only=True)
class RightParenToken(DelimiterToken):
    delimiter: str = ")"


@dataclass(frozen=True, kw_only=True)
class LeftBracketToken(DelimiterToken):
    delimiter: str = "["


@dataclass(frozen=True, kw_only=True)
class RightBracketToken(DelimiterToken):
    delimiter: str = "]"


@dataclass(frozen=True, kw_only=True)
class LeftBraceToken(DelimiterToken):
    delimiter: str = "{"


@dataclass(frozen=True, kw_only=True)
class RightBraceToken(DelimiterToken):
    delimiter: str = "}"


@dataclass(frozen=True, kw_only=True)
class CommaToken(DelimiterToken):
    delimiter: str = ","


@dataclass(frozen=True, kw_only=True)
class PragmaToken(TokenBase):
    """Pragma token capturing parsed content between {-# and #-}.

    The pragma content is parsed into a key-value pair:
    - First word (alphanumeric/underscore) is the key
    - Rest of the content is the value
    Example: {-# LLM model=gpt-4 #-} -> key="LLM", value="model=gpt-4"
    """

    key: str
    value: str
    raw_content: str

    @property
    def content(self) -> str:
        """Return raw content for backwards compatibility."""
        return self.raw_content

    def __str__(self) -> str:
        return self.raw_content


@dataclass(frozen=True, kw_only=True)
class DocstringToken(TokenBase):
    """Docstring token (-- | or -- ^)."""

    docstring_type: str  # "DOCSTRING_PRECEDING" or "DOCSTRING_INLINE"
    content: str

    @property
    def value(self) -> str:
        return self.content

    def __str__(self) -> str:
        return self.content


@dataclass(frozen=True, kw_only=True)
class CommentToken(TokenBase):
    """Regular comment token (-- ...)."""

    content: str

    @property
    def value(self) -> str:
        return self.content

    def __str__(self) -> str:
        return self.content


@dataclass(frozen=True, kw_only=True)
class EOFToken(TokenBase):
    """End of file token."""

    @property
    def value(self) -> str:
        return ""

    def __str__(self) -> str:
        return ""


class LexerError(Exception):
    """Error during lexical analysis."""

    def __init__(self, message: str, location: Location):
        super().__init__(f"{location}: {message}")
        self.location = location


# Type alias for token type strings
TokenTypeStr = str


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Layout constraints
    "AnyIndent",
    "AtPos",
    "AfterPos",
    "EndOfBlock",
    "ValidIndent",
    # Token protocol and base
    "Token",
    "TokenBase",
    # Literal tokens
    "IdentifierToken",
    "NumberToken",
    "StringToken",
    # Keyword tokens
    "KeywordToken",
    "LambdaToken",
    "DataToken",
    "LetToken",
    "InToken",
    "CaseToken",
    "OfToken",
    "ForallToken",
    "TypeToken",
    "IfToken",
    "ThenToken",
    "ElseToken",
    "PrimTypeToken",
    "PrimOpToken",
    "ImportToken",
    "QualifiedToken",
    "AsToken",
    "HidingToken",
    # Operator tokens
    "OperatorToken",
    "ArrowToken",
    "DarrowToken",
    "EqToken",
    "NeToken",
    "LtToken",
    "GtToken",
    "LeToken",
    "GeToken",
    "PlusToken",
    "MinusToken",
    "StarToken",
    "SlashToken",
    "AndToken",
    "OrToken",
    "AppendToken",
    "EqualsToken",
    "ColonToken",
    "DoubleColonToken",
    "BarToken",
    "AtToken",
    "DotToken",
    "SemicolonToken",
    # Delimiter tokens
    "DelimiterToken",
    "LeftParenToken",
    "RightParenToken",
    "LeftBracketToken",
    "RightBracketToken",
    "LeftBraceToken",
    "RightBraceToken",
    "CommaToken",
    # Misc tokens
    "PragmaToken",
    "DocstringToken",
    "CommentToken",
    "EOFToken",
    # Constants
    "DocstringType",
    "TokenType",
    # Errors and aliases
    "LexerError",
    "TokenTypeStr",
]
