"""System F surface language parser package.

Layout-sensitive parser following Idris2's approach with explicit
constraint passing.

Modules:
- types: Token types and layout constraint types (ValidIndent, TokenBase, etc.)
- lexer: Lexer and tokenizer (lex, Lexer)
- helpers: Parser combinators (block, terminator, etc.)
- declarations: Declaration parsers (data, let, etc.) and type parser
- expressions: Expression parsers (case, lambda, etc.)

NOTE: the whole parser is AI generated.
"""

from __future__ import annotations

from parsy import eof

# Re-export token types and layout constraints
from systemf.surface.parser.types import (
    TokenBase,
    ValidIndent,
    AnyIndent,
    AtPos,
    AfterPos,
    EndOfBlock,
    Location,
    Token,
    IdentifierToken,
    NumberToken,
    StringToken,
    KeywordToken,
    LambdaToken,
    DataToken,
    LetToken,
    InToken,
    CaseToken,
    OfToken,
    ForallToken,
    TypeToken,
    IfToken,
    ThenToken,
    ElseToken,
    PrimTypeToken,
    PrimOpToken,
    ImportToken,
    QualifiedToken,
    AsToken,
    HidingToken,
    OperatorToken,
    DelimiterToken,
    PragmaToken,
    DocstringToken,
    EOFToken,
    LexerError,
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
    UnitToken,
    LeftBracketToken,
    RightBracketToken,
    LeftBraceToken,
    RightBraceToken,
    CommaToken,
)

# Re-export lexer
from systemf.surface.parser.lexer import Lexer, lex

# Re-export helpers
from systemf.surface.parser.helpers import (
    column,
    check_valid,
    block,
    block_entries,
    terminator,
    must_continue,
)

# Import expression and declaration modules
from systemf.surface.parser import expressions, declarations

# Re-export expression parsers
from systemf.surface.parser.expressions import (
    expr_parser,
    atom_parser,
    app_parser,
    lambda_parser,
    case_parser,
    let_parser,
    if_parser,
    pattern_parser,
    case_alt,
    let_binding,
    match_token,
    match_symbol,
    variable_parser,
    literal_parser,
    paren_parser,
    atom_base_parser,
)

# Re-export declaration parsers
from systemf.surface.parser.declarations import (
    decl_parser,
    top_decl_parser,
    top_import_parser,
    data_parser,
    term_parser,
    prim_type_parser,
    prim_op_parser,
    import_decl_parser,
    constr_parser,
    match_ident,
    consolidate,
    RawDecl,
)

# Re-export type parser
from systemf.surface.parser.type_parser import type_parser
from systemf.surface.types import SurfaceDeclaration, SurfaceImportDeclaration


# Convenience function for parsing expressions
def parse_expression(source: str, filename: str = "<stdin>"):
    """Parse an expression from source code.

    Args:
        source: The source code string to parse
        filename: Optional filename for error reporting

    Returns:
        The parsed surface term

    Raises:
        ParseError: If parsing fails
    """
    from parsy import eof

    tokens = list(lex(source, filename))
    try:
        return (expressions.expr_parser(AnyIndent()) << eof).parse(tokens)
    except Exception as e:
        raise _extract_parse_error(e, tokens)


def parse_declaration(source: str, filename: str = "<stdin>"):
    """Parse a declaration from source code.

    Args:
        source: The source code string to parse
        filename: Optional filename for error reporting

    Returns:
        The parsed surface declaration

    Raises:
        ParseError: If parsing fails
    """
    from parsy import eof

    tokens = list(lex(source, filename))
    try:
        return (declarations.decl_parser() << eof).parse(tokens)
    except Exception as e:
        raise _extract_parse_error(e, tokens)


def parse_type(source: str, filename: str = "<stdin>"):
    """Parse a type from source code.

    Args:
        source: The source code string to parse
        filename: Optional filename for error reporting

    Returns:
        The parsed surface type

    Raises:
        ParseError: If parsing fails
    """
    tokens = list(lex(source, filename))
    try:
        return (type_parser() << eof).parse(tokens)
    except Exception as e:
        raise _extract_parse_error(e, tokens)


def parse_program(source: str, filename: str = "<stdin>") -> tuple[
    list[SurfaceImportDeclaration],
    list[SurfaceDeclaration],
]:
    """Parse a complete program from source code.

    Parses imports first, then non-import declarations.
    Returns a tuple of (imports, declarations).

    Args:
        source: The source code string to parse
        filename: Optional filename for error reporting

    Returns:
        Tuple of (list of import declarations, list of other declarations)

    Raises:
        ParseError: If parsing fails
    """
    from systemf.surface.parser.types import ImportToken

    tokens = list(lex(source, filename))
    try:
        imports, rest = top_import_parser().parse_partial(tokens)
        raw_decls, remainder = top_decl_parser().parse_partial(rest)
        decls = consolidate(raw_decls)

        # Preserve import ordering error from change #18
        for token in remainder:
            if isinstance(token, ImportToken):
                loc = getattr(token, "location", None)
                raise ParseError("import declarations must appear before other declarations", loc)

        return imports, decls
    except Exception as e:
        raise _extract_parse_error(e, tokens)


class ParseError(Exception):
    """Error during parsing."""

    def __init__(self, message: str, location=None):
        from systemf.utils.location import Location

        loc_str = f"{location}" if location else "unknown location"
        super().__init__(f"{loc_str}: {message}")
        self.location = location


def _extract_parse_error(e: Exception, tokens: list) -> ParseError:
    """Extract location from exception and create ParseError.

    Properly bounds checks before accessing token list.
    """
    loc = None
    # Safely get index from exception
    idx = getattr(e, "index", None)
    if idx is not None and isinstance(idx, int) and 0 <= idx < len(tokens):
        loc = getattr(tokens[idx], "location", None)
    return ParseError(str(e), loc)



__all__ = [
    # Layout constraints and locations
    "ValidIndent",
    "AnyIndent",
    "AtPos",
    "AfterPos",
    "EndOfBlock",
    "Location",
    # Token types
    "Token",
    "TokenBase",
    "IdentifierToken",
    "NumberToken",
    "StringToken",
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
    "OperatorToken",
    "OperatorType",
    "DoubleColonToken",
    "DelimiterToken",
    "DelimiterType",
    "UnitToken",
    "PragmaToken",
    "DocstringToken",
    "EOFToken",
    "LexerError",
    # Lexer
    "Lexer",
    "lex",
    # Helpers
    "column",
    "check_valid",
    "block",
    "block_entries",
    "terminator",
    "must_continue",
    # Expression parsers
    "expr_parser",
    "atom_parser",
    "app_parser",
    "lambda_parser",
    "if_parser",
    "case_parser",
    "let_parser",
    "pattern_parser",
    "case_alt",
    "let_binding",
    "match_token",
    "match_keyword",
    "match_symbol",
    "variable_parser",
    "literal_parser",
    "paren_parser",
    "atom_base_parser",
    # Declaration parsers
    "decl_parser",
    "top_decl_parser",
    "top_import_parser",
    "data_parser",
    "term_parser",
    "prim_type_parser",
    "prim_op_parser",
    "import_decl_parser",
    "type_parser",
    "constr_parser",
    "match_ident",
    "consolidate",
    "RawDecl",
    # Convenience functions
    "parse_expression",
    "parse_declaration",
    "parse_type",
    "parse_program",
]
