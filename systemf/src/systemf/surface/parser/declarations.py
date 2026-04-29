"""Declaration parsers for System F surface language.

Implements declaration parsers using the helper combinators.
Declarations are NOT layout-sensitive - they can appear at any column.

Parsers implemented:
- Data declarations: data CONSTRUCTOR [params] = constr ("|" constr)*
- Term declarations: ident : type = expr
- Primitive type declarations: prim_type CONSTRUCTOR
- Primitive operation declarations: prim_op ident : type
- Main declaration entry point
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from parsy import Parser as P, Result, alt, generate

from systemf.surface.parser.types import (
    KeywordToken,
    OperatorToken,
    DelimiterToken,
    IdentifierToken,
    DocstringToken,
    PragmaToken,
    DocstringType,
    UnitToken,
)
from systemf.surface.types import (
    SurfaceDeclaration,
    SurfaceDataDeclaration,
    SurfaceTermDeclaration,
    SurfacePrimTypeDecl,
    SurfacePrimOpDecl,
    SurfaceImportDeclaration,
    SurfaceConstructorInfo,
    SurfaceType,
)
from systemf.surface.parser.type_parser import (
    tycon_arg_parser,
    type_atom_parser,
    type_parser,
)

# Import expression parser for term declaration bodies
from systemf.surface.parser.expressions import expr_parser as _expr_parser_factory
from systemf.surface.parser.helpers import AfterPos, match_token


def skip_inline_docstrings() -> P[None]:
    """Skip any inline docstring tokens (-- ^).

    Returns:
        Parser that consumes and ignores inline docstrings
    """

    @P
    def parser(tokens: list, index: int) -> Result:
        i = index
        while i < len(tokens):
            token = tokens[i]
            if isinstance(token, DocstringToken) and token.docstring_type == DocstringType.FOLLOWING:
                i += 1
            else:
                break
        return Result.success(i, None)

    return parser


# =============================================================================
# Token Matching Helpers
# =============================================================================


def match_keyword(value: str) -> P[KeywordToken]:
    """Match a keyword token with the given value.

    Args:
        value: The keyword to match (e.g., "data", "let")

    Returns:
        Parser that returns the matched keyword token
    """

    @P
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.failure(index, f"expected keyword '{value}'")
        token = tokens[index]
        if isinstance(token, KeywordToken) and token.keyword == value:
            return Result.success(index + 1, token)
        return Result.failure(index, f"expected keyword '{value}', got {str(token)}")

    return parser


def match_symbol(value: str) -> P[OperatorToken | DelimiterToken]:
    """Match an operator or delimiter token with the given value.

    Args:
        value: The symbol to match (e.g., "=", "|", ":")

    Returns:
        Parser that returns the matched operator/delimiter token
    """

    @P
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.failure(index, f"expected symbol '{value}'")
        token = tokens[index]
        if isinstance(token, OperatorToken) and token.operator == value:
            return Result.success(index + 1, token)
        if isinstance(token, DelimiterToken) and token.delimiter == value:
            return Result.success(index + 1, token)
        return Result.failure(index, f"expected symbol '{value}'")

    return parser


def match_ident() -> P[IdentifierToken]:
    """Match an identifier token.

    Returns:
        Parser that returns the matched identifier token
    """

    @P
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.failure(index, "expected identifier")
        token = tokens[index]
        if isinstance(token, IdentifierToken):
            return Result.success(index + 1, token)
        return Result.failure(index, f"expected identifier, got {str(token)}")

    return parser


def match_docstring() -> P[DocstringToken]:
    """Match a preceding docstring token.

    Returns:
        Parser that returns the matched DocstringToken
    """

    @P
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.failure(index, "expected docstring")
        token = tokens[index]
        if isinstance(token, DocstringToken) and token.docstring_type == DocstringType.PRECEDING:
            return Result.success(index + 1, token)
        return Result.failure(index, "expected docstring")

    return parser


def match_pragma() -> P[PragmaToken]:
    """Match a pragma token.

    Returns:
        Parser that returns the matched PragmaToken
    """

    @P
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.failure(index, "expected pragma")
        token = tokens[index]
        if isinstance(token, PragmaToken) and token.key:
            return Result.success(index + 1, token)
        return Result.failure(index, "expected pragma")

    return parser


# =============================================================================
# Type Parser (imported from type_parser module)
# =============================================================================

# Type parsers are imported from type_parser module:
# - type_atom_parser: parses atomic types
# - type_parser: main type parser for types and arrows


# =============================================================================
# Constructor Parser (for data declarations)
# =============================================================================


def constr_parser() -> P[SurfaceConstructorInfo]:
    """Parse a data constructor: CONSTRUCTOR [type_atom*].

    Returns:
        SurfaceConstructorInfo with constructor name and type arguments
    """

    @P
    def parser(tokens: list, index: int) -> Result:
        i = index

        # Skip any inline docstrings before constructor name
        skip_result = skip_inline_docstrings()(tokens, i)
        if skip_result.status:
            i = skip_result.index

        # Match constructor name (now uses IDENT token)
        con_result = match_ident()(tokens, i)
        if not con_result.status:
            return con_result
        con_token = con_result.value
        name = con_token.value
        loc = con_token.location
        i = con_result.index

        # Parse type arguments greedily until no more type atoms
        # The topDecl parser sets boundaries, so we parse until the type atom parser fails
        # But stop if we see a BAR (constructor separator) - that's not a type argument
        # Also stop if we see what looks like a term declaration (identifier followed by :)
        args: list[SurfaceType] = []
        while i < len(tokens):
            # Stop at constructor separator (|)
            if isinstance(tokens[i], OperatorToken) and tokens[i].operator == "|":
                break

            # Stop if this looks like a term declaration (identifier :: type)
            # This prevents consuming identifiers that are actually function names
            if isinstance(tokens[i], IdentifierToken):
                # Check if next token is a double colon - if so, this is likely a term declaration
                if i + 1 < len(tokens):
                    next_token = tokens[i + 1]
                    if isinstance(next_token, OperatorToken) and next_token.operator == "::":
                        break

            # Try to parse a type atom
            arg_result = type_atom_parser()(tokens, i)
            if not arg_result.status:
                break
            # Make sure we actually advanced
            if arg_result.index <= i:
                break
            args.append(arg_result.value)
            i = arg_result.index

        return Result.success(
            i, SurfaceConstructorInfo(name=name, args=args, docstring=None, location=loc)
        )

    return parser


# =============================================================================
# Declaration Parsers
# =============================================================================


def data_parser() -> P[SurfaceDataDeclaration]:
    """Parse a data declaration: data CONSTRUCTOR [ident*] = constr ("|" constr)*.

    Grammar: data CONSTRUCTOR [ident*] = constr ("|" constr)*
    NOT layout-sensitive - constructors can be on any line

    Returns:
        SurfaceDataDeclaration with type name, parameters, and constructors
    """

    @generate
    def parser():
        # Match "data" keyword
        data_token = yield match_keyword("data")
        loc = data_token.location

        # Parse type constructor name
        name_token = yield match_ident()
        name = name_token.value

        # Parse optional type parameters (with optional inline docstrings)
        params = yield tycon_arg_parser().many()

        # Match "=" symbol
        yield match_symbol("=")

        # Skip any inline docstrings before first constructor
        yield skip_inline_docstrings()

        # Parse first constructor
        first_constr = yield constr_parser()

        # Parse additional constructors separated by "|"
        rest_constrs: list[SurfaceConstructorInfo] = []
        while True:
            # Skip any inline docstrings
            yield skip_inline_docstrings()

            # Try to match "|"
            pipe = yield (match_symbol("|")).optional()
            if pipe is None:
                break

            # Skip any inline docstrings after "|"
            yield skip_inline_docstrings()

            # Parse next constructor
            constr = yield constr_parser()
            rest_constrs.append(constr)

        constructors = [first_constr] + rest_constrs

        return SurfaceDataDeclaration(
            name=name,
            params=params,
            constructors=constructors,
            location=loc,
            docstring=None,
            pragma=None,
        )

    return parser


def term_parser() -> P[SurfaceTermDeclaration]:
    """Parse a term declaration: ident : type = expr.

    Combines type signature AND definition.
    Example: add x y : Int = x + y

    Returns:
        SurfaceTermDeclaration with name, type annotation, and body
    """

    @generate
    def parser():
        # Parse identifier name
        name_token = yield match_ident()
        name = name_token.value
        loc = name_token.location

        # Match "::" for type annotation
        yield match_symbol("::")

        # Parse type — constrained so that the next top-level declaration
        # (which starts at the same column as name_token) is never consumed
        # as a type application argument.
        decl_col = name_token.location.column
        ty = yield type_parser(AfterPos(col=decl_col + 1))

        # Match "=" for definition
        yield match_symbol("=")

        # The declaration name's column is the block column for the entire
        # declaration — both the type (above) and the body use the same
        # AfterPos(decl_col + 1) constraint.  Any token at column <= decl_col
        # belongs to the next declaration, not to this body.
        body = yield _expr_parser_factory(AfterPos(col=decl_col + 1))

        return SurfaceTermDeclaration(
            name=name,
            type_annotation=ty,
            body=body,
            location=loc,
            docstring=None,
            pragma=None,
        )

    return parser


def prim_type_parser() -> P[SurfacePrimTypeDecl]:
    """Parse a primitive type declaration: prim_type CONSTRUCTOR [ident*].

    Returns:
        SurfacePrimTypeDecl with the primitive type name and optional params
    """

    @generate
    def parser():
        # Match "prim_type" keyword
        prim_token = yield match_keyword("prim_type")
        loc = prim_token.location

        # Parse constructor name
        name_token = yield match_ident()
        name = name_token.value

        # Parse optional type parameters (with optional inline docstrings)
        params = yield tycon_arg_parser().many()

        return SurfacePrimTypeDecl(name=name, params=params, location=loc, docstring=None, pragma=None)

    return parser


def prim_op_parser() -> P[SurfacePrimOpDecl]:
    """Parse a primitive operation declaration: prim_op ident : type.

    Returns:
        SurfacePrimOpDecl with name and type annotation
    """

    @generate
    def parser():
        # Match "prim_op" keyword
        prim_token = yield match_keyword("prim_op")
        loc = prim_token.location

        # Parse identifier name
        name_token = yield match_ident()
        name = name_token.value

        # Match "::" for type annotation
        yield match_symbol("::")

        # Parse type — constrained so that the next top-level declaration
        # (at the same column as prim_token) is never consumed as a type
        # application argument.  AfterPos(decl_col + 1) accepts only tokens
        # strictly indented past the declaration keyword.
        decl_col = prim_token.location.column
        ty = yield type_parser(AfterPos(col=decl_col + 1))

        return SurfacePrimOpDecl(
            name=name,
            type_annotation=ty,
            location=loc,
            docstring=None,
            pragma=None,
        )

    return parser


def import_decl_parser() -> P[SurfaceImportDeclaration]:
    """Parse an import declaration: import [qualified] module_name [as alias] [import_spec].

    Grammar:
        import_decl   ::= "import" ["qualified"] module_name ["as" alias] [import_spec]
        module_name   ::= IDENT ("." IDENT)*
        import_spec   ::= "(" ident_list ")" | "hiding" "(" ident_list ")"
        ident_list    ::= ident ("," ident)*

    Returns:
        SurfaceImportDeclaration with module, qualified, alias, items, and hiding
    """

    @generate
    def parser():
        import_token = yield match_keyword("import")
        loc = import_token.location

        qualified = yield (match_keyword("qualified")).optional()

        # Module name: IDENT ("." IDENT)*
        first_part = yield match_ident()
        module_parts = [first_part.value]
        while True:
            dot = yield (match_symbol(".")).optional()
            if dot is None:
                break
            part = yield match_ident()
            module_parts.append(part.value)
        module_name = ".".join(module_parts)

        alias = None
        as_kw = yield (match_keyword("as")).optional()
        if as_kw is not None:
            alias_token = yield match_ident()
            alias = alias_token.value

        items = None
        hiding = False

        hiding_kw = yield (match_keyword("hiding")).optional()
        if hiding_kw is not None:
            hiding = True

        unit_token = yield match_token(UnitToken).optional()
        if unit_token is not None:
            items = []
        else:
            open_paren = yield (match_symbol("(")).optional()
            if open_paren is not None:
                first_item = yield match_ident().optional()
                item_names: list[str] = []
                if first_item is not None:
                    item_names = [first_item.value]
                    while True:
                        comma = yield (match_symbol(",")).optional()
                        if comma is None:
                            break
                        item_token = yield match_ident()
                        item_names.append(item_token.value)
                yield match_symbol(")")
                items = item_names

        return SurfaceImportDeclaration(
            module=module_name,
            qualified=qualified is not None,
            alias=alias,
            items=items,
            hiding=hiding,
            location=loc,
        )

    return parser


# =============================================================================
# Main Declaration Entry Point
# =============================================================================


def decl_parser() -> P[SurfaceDeclaration]:
    """Main declaration parser - tries all declaration types with metadata.

    Tries in order:
    1. Data declaration
    2. Term declaration
    3. Primitive type declaration
    4. Primitive operation declaration

    Handles docstrings (-- |) and pragmas ({-# ... #-}) that appear before
    the declaration.

    Returns:
        The parsed declaration with docstring and pragma metadata attached
    """

    # Use top_decl_parser which handles metadata accumulation
    # and return just the first declaration
    @P
    def parser(tokens: list, index: int) -> Result:
        result = top_decl_parser()(tokens, index)
        if result.status:
            declarations = result.value
            if declarations:
                return Result.success(result.index, consolidate([declarations[0]])[0])
            return Result.failure(index, "expected at least one declaration")
        return Result.failure(index, result.expected)

    return parser


# =============================================================================
# Multiple Declarations Parser with Metadata
# =============================================================================


@dataclass
class RawDecl:
    """Raw declaration with unconsolidated metadata."""

    docstrings: list[str]
    pragmas: dict[str, str]
    decl: SurfaceDeclaration


def consolidate(raw_decls: list[RawDecl]) -> list[SurfaceDeclaration]:
    """Attach accumulated metadata to declarations.

    Uses dataclasses.replace to attach docstrings and pragmas.
    Imports are not handled here (they lack docstring/pragma fields).
    """
    result: list[SurfaceDeclaration] = []
    for rd in raw_decls:
        docstring = " ".join(rd.docstrings) if rd.docstrings else None
        pragmas = dict(rd.pragmas) if rd.pragmas else None
        result.append(replace(rd.decl, docstring=docstring, pragma=pragmas))
    return result


def top_import_parser() -> P[list[SurfaceImportDeclaration]]:
    """Parse import declarations at the top of a module.

    Skips docstrings and pragmas before imports (imports don't carry metadata).
    Stops naturally at the first non-import token.

    Returns:
        List of parsed import declarations
    """
    skip_meta = alt(match_docstring(), match_pragma()).many()
    import_entry = skip_meta >> import_decl_parser()
    return import_entry.many()


def top_decl_parser() -> P[list[RawDecl]]:
    """Parse non-import declarations with metadata accumulation.

    Collects docstrings and pragmas into RawDecl but does not attach them.
    Metadata attachment is done by consolidate() as a post-processing step.

    Returns:
        List of raw declarations with unconsolidated metadata
    """

    @generate
    def entry():
        meta = yield alt(match_docstring(), match_pragma()).many()
        decl = yield alt(data_parser(), term_parser(), prim_type_parser(), prim_op_parser())

        docstrings = [t.content for t in meta if isinstance(t, DocstringToken)]
        pragmas = {t.key: t.value for t in meta if isinstance(t, PragmaToken)}
        return RawDecl(docstrings, pragmas, decl)

    return entry.many()


# =============================================================================
# Public API
# =============================================================================


__all__ = [
    # Token matching
    "match_keyword",
    "match_symbol",
    "match_ident",
    # Constructor parser
    "constr_parser",
    # Declaration parsers
    "data_parser",
    "term_parser",
    "prim_type_parser",
    "prim_op_parser",
    "decl_parser",
    "top_decl_parser",
    "top_import_parser",
    "import_decl_parser",
    "RawDecl",
    "consolidate",
    "match_docstring",
    "match_pragma",
]
