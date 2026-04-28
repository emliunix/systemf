"""Lexer for surface language.

Simple tokenizer for System F surface syntax.
No virtual indentation tokens - stateful parser will handle layout.
"""

from __future__ import annotations

import re

from systemf.surface.parser.types import (
    AsToken,
    CaseToken,
    CommentToken,
    DataToken,
    DocstringToken,
    DocstringType,
    ElseToken,
    ForallToken,
    HidingToken,
    IdentifierToken,
    IfToken,
    ImportToken,
    InToken,
    LambdaToken,
    LetToken,
    LexerError,
    NumberToken,
    OfToken,
    PragmaToken,
    PrimOpToken,
    PrimTypeToken,
    QualifiedToken,
    StringToken,
    ThenToken,
    TokenBase,
    TypeToken,
    # Concrete operator tokens
    ArrowToken,
    DarrowToken,
    EqToken,
    NeToken,
    LtToken,
    GtToken,
    LeToken,
    GeToken,
    PlusToken,
    MinusToken,
    StarToken,
    SlashToken,
    AndToken,
    OrToken,
    AppendToken,
    EqualsToken,
    ColonToken,
    DoubleColonToken,
    BarToken,
    AtToken,
    DotToken,
    # Concrete delimiter tokens
    LeftParenToken,
    RightParenToken,
    LeftBracketToken,
    RightBracketToken,
    LeftBraceToken,
    RightBraceToken,
    CommaToken,
)
from systemf.utils.location import Location


class Lexer:
    """Tokenizer for System F surface language.

    Tokenizes input into a stream of tokens for the parser.
    No indentation tracking - raw tokens only with location info.
    """

    # Token specifications as regex patterns
    # Unicode characters used directly (not escapes) for readability
    TOKEN_PATTERNS = [
        # Pragma: matches entire block {-# ... #-} including multiline
        ("PRAGMA", r"\{-#(?:(?!#-\}).)*#-\}"),
        # Whitespace
        ("WHITESPACE", r"[ \t]+"),
        ("NEWLINE", r"\n|\r\n?"),
        # Docstrings (-- | or -- ^) - single line only, no merging
        (DocstringType.PRECEDING, r"--\s*\|([^\n]*)"),
        (DocstringType.FOLLOWING, r"--\s*\^([^\n]*)"),
        # Regular comments
        ("COMMENT", r"--[^\n]*"),
        # Keywords
        ("DATA", r"\bdata\b"),
        ("LET", r"\blet\b"),
        ("IN", r"\bin\b"),
        ("CASE", r"\bcase\b"),
        ("OF", r"\bof\b"),
        ("FORALL", r"\bforall\b|∀"),
        ("TYPE", r"\btype\b"),
        ("IF", r"\bif\b"),
        ("THEN", r"\bthen\b"),
        ("ELSE", r"\belse\b"),
        ("PRIM_TYPE", r"\bprim_type\b"),
        ("PRIM_OP", r"\bprim_op\b"),
        ("IMPORT", r"\bimport\b"),
        ("QUALIFIED", r"\bqualified\b"),
        ("AS", r"\bas\b"),
        ("HIDING", r"\bhiding\b"),
        # Multi-character operators
        ("ARROW", r"->|→"),
        ("DARROW", r"=>"),
        ("NE", r"/="),
        ("LE", r"<="),
        ("GE", r">="),
        ("AND", r"&&"),
        ("OR", r"\|\|"),
        ("APPEND", r"\+\+"),
        ("LAMBDA", r"\\|λ"),
        # Single-character operators (after multi-char)
        ("EQ", r"=="),
        ("PLUS", r"\+"),
        ("MINUS", r"-"),
        ("STAR", r"\*"),
        ("SLASH", r"/"),
        ("LT", r"<"),
        ("GT", r">"),
        ("EQUALS", r"="),
        ("DOUBLECOLON", r"::"),
        ("COLON", r":"),
        ("BAR", r"\|"),
        ("AT", r"@"),
        ("DOT", r"\."),
        # Delimiters
        ("LPAREN", r"\("),
        ("RPAREN", r"\)"),
        ("LBRACKET", r"\["),
        ("RBRACKET", r"\]"),
        ("LBRACE", r"\{"),
        ("RBRACE", r"\}"),
        ("COMMA", r","),
        # Literals
        ("STRING", r'"([^"\\]|\\.)*"'),
        ("NUMBER", r"\d+"),
        # Identifiers (all names treated uniformly)
        ("IDENT", r"[a-zA-Z_][a-zA-Z0-9_']*"),
    ]

    def __init__(self, source: str, filename: str | None = None) -> None:
        """Initialize lexer with source code.

        Args:
            source: Source code to tokenize
            filename: Optional filename for error reporting
        """
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: list[TokenBase] = []

        # Compile regex for efficiency
        self._pattern = re.compile(
            "|".join(f"(?P<{name}>{pattern})" for name, pattern in self.TOKEN_PATTERNS),
            re.DOTALL,  # Allow . to match newlines for pragma multiline matching
        )

    def tokenize(self) -> list[TokenBase]:
        """Convert source code to token stream.

        Returns:
            List of tokens with location information

        Raises:
            LexerError: If unexpected character encountered
        """
        self.tokens = []

        while self.pos < len(self.source):
            # Skip whitespace (but not newlines, comments, docstrings, or pragmas)
            if self._skip_whitespace():
                continue

            # Try to match a token
            match = self._pattern.match(self.source, self.pos)

            if match:
                token = self._create_token(match)
                if token:
                    self.tokens.append(token)
                self._advance(match.group())
            else:
                # Unknown character
                loc = Location(self.line, self.column, self.filename)
                raise LexerError(f"Unexpected character: {self.source[self.pos]!r}", loc)

        return self.tokens

    def _skip_whitespace(self) -> bool:
        """Skip whitespace (spaces and tabs only, not newlines).

        Returns:
            True if skipped anything, False otherwise
        """
        skipped = False
        while self.pos < len(self.source) and self.source[self.pos] in " \t":
            self._advance(self.source[self.pos])
            skipped = True
        return skipped

    def _advance(self, text: str) -> None:
        """Advance position by text length, updating line/column."""
        for char in text:
            if char == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
        self.pos += len(text)

    def _process_escape_sequences(self, s: str) -> str:
        """Process escape sequences in a string literal.

        Converts standard escape sequences to their actual characters:
        - \\n -> newline (ASCII 10)
        - \\t -> tab (ASCII 9)
        - \\r -> carriage return (ASCII 13)
        - \\\\ -> backslash
        - \\\" -> double quote
        - \\b -> backspace (ASCII 8)
        - \\f -> form feed (ASCII 12)
        - \\0 -> null (ASCII 0)

        Args:
            s: The raw string content (without quotes)

        Returns:
            String with escape sequences processed
        """
        result = []
        i = 0
        while i < len(s):
            if s[i] == "\\" and i + 1 < len(s):
                next_char = s[i + 1]
                if next_char == "n":
                    result.append("\n")
                    i += 2
                elif next_char == "t":
                    result.append("\t")
                    i += 2
                elif next_char == "r":
                    result.append("\r")
                    i += 2
                elif next_char == "\\":
                    result.append("\\")
                    i += 2
                elif next_char == '"':
                    result.append('"')
                    i += 2
                elif next_char == "b":
                    result.append("\b")
                    i += 2
                elif next_char == "f":
                    result.append("\f")
                    i += 2
                elif next_char == "0":
                    result.append("\0")
                    i += 2
                else:
                    # Unknown escape sequence, keep as-is
                    result.append(s[i])
                    i += 1
            else:
                result.append(s[i])
                i += 1
        return "".join(result)

    def _create_token(self, match: re.Match) -> TokenBase | None:
        """Create appropriate token from regex match."""
        token_type = match.lastgroup
        value = match.group()
        loc = Location(self.line, self.column, self.filename)

        if token_type == "WHITESPACE":
            # Skip whitespace
            return None
        elif token_type == "COMMENT":
            # Emit comment token (content after --)
            content = value[2:].strip() if len(value) > 2 else ""
            return CommentToken(content=content, location=loc)
        elif token_type == "NEWLINE":
            # Track newlines for location, but don't emit token
            return None
        elif token_type == "PRAGMA":
            # Extract raw content between {-# and #-}
            raw_content = value[3:-3].strip()  # Remove {-# and #-}
            # Parse into key-value pair: first word is key, rest is value
            parts = raw_content.split(None, 1)
            key = parts[0] if parts else ""
            val = parts[1] if len(parts) > 1 else ""
            return PragmaToken(key=key, value=val, raw_content=raw_content, location=loc)
        elif token_type == DocstringType.PRECEDING:
            # Keep the full content including '|' marker - post-pass will handle it
            # value is like "-- | some content", keep "| some content"
            content = value[2:].strip() if len(value) > 2 else ""
            return DocstringToken(docstring_type=token_type, content=content, location=loc)
        elif token_type == DocstringType.FOLLOWING:
            # Keep the full content including '^' marker - post-pass will handle it
            content = value[2:].strip() if len(value) > 2 else ""
            return DocstringToken(docstring_type=token_type, content=content, location=loc)
        elif token_type == "IDENT":
            return IdentifierToken(name=value, location=loc)
        elif token_type == "NUMBER":
            return NumberToken(number=value, location=loc)
        elif token_type == "STRING":
            # Remove quotes from string value and process escape sequences
            string_value = value[1:-1]
            string_value = self._process_escape_sequences(string_value)
            return StringToken(string=string_value, location=loc)
        elif token_type == "DATA":
            return DataToken(keyword=value, location=loc)
        elif token_type == "LET":
            return LetToken(keyword=value, location=loc)
        elif token_type == "IN":
            return InToken(keyword=value, location=loc)
        elif token_type == "CASE":
            return CaseToken(keyword=value, location=loc)
        elif token_type == "OF":
            return OfToken(keyword=value, location=loc)
        elif token_type == "FORALL":
            return ForallToken(keyword=value, location=loc)
        elif token_type == "TYPE":
            return TypeToken(keyword=value, location=loc)
        elif token_type == "IF":
            return IfToken(keyword=value, location=loc)
        elif token_type == "THEN":
            return ThenToken(keyword=value, location=loc)
        elif token_type == "ELSE":
            return ElseToken(keyword=value, location=loc)
        elif token_type == "PRIM_TYPE":
            return PrimTypeToken(keyword=value, location=loc)
        elif token_type == "PRIM_OP":
            return PrimOpToken(keyword=value, location=loc)
        elif token_type == "IMPORT":
            return ImportToken(keyword=value, location=loc)
        elif token_type == "QUALIFIED":
            return QualifiedToken(keyword=value, location=loc)
        elif token_type == "AS":
            return AsToken(keyword=value, location=loc)
        elif token_type == "HIDING":
            return HidingToken(keyword=value, location=loc)
        elif token_type == "LAMBDA":
            return LambdaToken(symbol=value, location=loc)
        elif token_type == "ARROW":
            return ArrowToken(operator=value, location=loc)
        elif token_type == "DARROW":
            return DarrowToken(operator=value, location=loc)
        elif token_type == "EQ":
            return EqToken(operator=value, location=loc)
        elif token_type == "NE":
            return NeToken(operator=value, location=loc)
        elif token_type == "LT":
            return LtToken(operator=value, location=loc)
        elif token_type == "GT":
            return GtToken(operator=value, location=loc)
        elif token_type == "LE":
            return LeToken(operator=value, location=loc)
        elif token_type == "GE":
            return GeToken(operator=value, location=loc)
        elif token_type == "PLUS":
            return PlusToken(operator=value, location=loc)
        elif token_type == "MINUS":
            return MinusToken(operator=value, location=loc)
        elif token_type == "STAR":
            return StarToken(operator=value, location=loc)
        elif token_type == "SLASH":
            return SlashToken(operator=value, location=loc)
        elif token_type == "AND":
            return AndToken(operator=value, location=loc)
        elif token_type == "OR":
            return OrToken(operator=value, location=loc)
        elif token_type == "APPEND":
            return AppendToken(operator=value, location=loc)
        elif token_type == "EQUALS":
            return EqualsToken(operator=value, location=loc)
        elif token_type == "DOUBLECOLON":
            return DoubleColonToken(operator=value, location=loc)
        elif token_type == "COLON":
            return ColonToken(operator=value, location=loc)
        elif token_type == "BAR":
            return BarToken(operator=value, location=loc)
        elif token_type == "AT":
            return AtToken(operator=value, location=loc)
        elif token_type == "DOT":
            return DotToken(operator=value, location=loc)
        elif token_type == "LPAREN":
            return LeftParenToken(delimiter=value, location=loc)
        elif token_type == "RPAREN":
            return RightParenToken(delimiter=value, location=loc)
        elif token_type == "LBRACKET":
            return LeftBracketToken(delimiter=value, location=loc)
        elif token_type == "RBRACKET":
            return RightBracketToken(delimiter=value, location=loc)
        elif token_type == "LBRACE":
            return LeftBraceToken(delimiter=value, location=loc)
        elif token_type == "RBRACE":
            return RightBraceToken(delimiter=value, location=loc)
        elif token_type == "COMMA":
            return CommaToken(delimiter=value, location=loc)
        else:
            # Unknown token type - skip
            return None


def lex(source: str, filename: str | None = None) -> list[TokenBase]:
    """Tokenize source code.

    Convenience function that creates a Lexer and tokenizes the source.
    Also processes comments in a post-lexer pass to join consecutive lines
    and classify docstrings.

    Args:
        source: Source code to tokenize
        filename: Optional filename for error reporting

    Returns:
        List of tokens with comments processed
    """
    tokens = Lexer(source, filename).tokenize()
    tokens = process_comments(tokens)
    tokens = strip_comments_and_whitespace(tokens)
    return tokens


def process_comments(tokens: list[TokenBase]) -> list[TokenBase]:
    """Process comments: join consecutive lines and classify docstrings.

    This is a post-lexer pass with nested while loop style:
    1. Outer loop finds potential docstring start
    2. Inner loop (when marker | or ^ found) consumes all consecutive comment lines
    3. First line: strip leading space (Idris2-style) then marker
    4. Subsequent lines: strip leading space only (marker already stripped by lexer)
    5. Classifies as DOCSTRING_PRECEDING (|) or DOCSTRING_INLINE (^)
    6. Stops at new docstring (| or ^) or blank line or non-comment

    Args:
        tokens: Raw tokens from lexer

    Returns:
        Tokens with docstrings processed, regular comments filtered
    """
    if not tokens:
        return tokens

    def strip_first_space(s: str) -> str:
        """Strip first leading space if present (Idris2-style)."""
        return s[1:] if s.startswith(" ") else s

    def has_marker(content: str) -> tuple[bool, str]:
        """Check if content has docstring marker after optional space.
        Returns (has_marker, marker_char) where marker_char is '|', '^', or ''.
        """
        stripped = strip_first_space(content)
        if stripped.startswith("|"):
            return True, "|"
        elif stripped.startswith("^"):
            return True, "^"
        return False, ""

    result: list[TokenBase] = []
    i = 0

    while i < len(tokens):
        token = tokens[i]

        # Check if this is a potential docstring
        if isinstance(token, (DocstringToken, CommentToken)):
            has_marker_flag, marker = has_marker(token.content)

            if has_marker_flag:
                # Docstring found - enter inner loop to consume consecutive lines
                location = token.location
                # First line: strip leading space then marker
                first_content = strip_first_space(token.content)
                if first_content.startswith(marker):
                    first_content = strip_first_space(first_content[1:])
                lines = [first_content]
                last_line = token.location.line
                j = i + 1

                # Inner while: consume all consecutive comment lines
                # Stop at blank line, non-comment, or new marker after non-marker comments
                saw_non_marker = False
                while j < len(tokens):
                    next_token = tokens[j]

                    # Check for line gap (blank line means end of docstring)
                    if hasattr(next_token, "location"):
                        if next_token.location.line - last_line > 1:
                            break
                        last_line = next_token.location.line

                    # Only accept comment tokens
                    if not isinstance(next_token, (DocstringToken, CommentToken)):
                        break

                    # Process this line: strip leading space, then check for marker
                    content = strip_first_space(next_token.content)
                    has_marker_now = content.startswith("|") or content.startswith("^")

                    # If we see a marker after non-marker comments, stop (new docstring)
                    if has_marker_now and saw_non_marker:
                        break

                    # Strip marker if present and continue
                    if has_marker_now:
                        content = strip_first_space(content[1:])
                    else:
                        saw_non_marker = True

                    lines.append(content)
                    j += 1

                # Create the docstring token
                content = "\n".join(lines)
                doc_type = DocstringType.PRECEDING if marker == "|" else DocstringType.FOLLOWING
                result.append(
                    DocstringToken(docstring_type=doc_type, content=content, location=location)
                )
                i = j
            else:
                # Regular comment - skip it
                i += 1
        else:
            # Non-comment token - keep it
            result.append(token)
            i += 1

    return result


def strip_comments_and_whitespace(tokens: list[TokenBase]) -> list[TokenBase]:
    """Filter out remaining comments and whitespace tokens.

    After processing docstrings, remove any leftover comment tokens
    and other non-semantic tokens before parsing.

    Args:
        tokens: Tokens after docstring processing

    Returns:
        Clean tokens ready for parsing
    """
    return [
        t
        for t in tokens
        if not isinstance(t, CommentToken)
        and (
            not isinstance(t, DocstringToken)
            or t.docstring_type in (DocstringType.PRECEDING, DocstringType.FOLLOWING)
        )
    ]
