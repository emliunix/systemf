"""Type parser for System F surface language.

Extracted from declarations.py to eliminate circular dependencies.
Types are parsed independently and have no dependencies on expressions.

Parsers implemented:
- Type atoms (variables, constructors, parenthesized types)
- Type applications (constructor applied to arguments)
- Function types (arrows)
- Universal quantification (forall)
- Tuple types

Layout-sensitive parsing
------------------------
All parsers accept an optional ``constraint: ValidIndent`` argument that is
threaded through every sub-parser.  The semantics follow Idris2's approach:

- ``AnyIndent()``  — no column restriction (default, used inside parens/tuples)
- ``AfterPos(c)``  — token must be at column >= c (used for declaration bodies)

The constraint is checked at two places:

1. Before each additional argument in ``type_app_parser`` (mirrors Idris2's
   ``many (argExpr fname indents)`` where ``argExpr`` starts with
   ``continue indents``).
2. Before the optional ``->`` arrow in ``type_arrow_parser`` (mirrors Idris2's
   ``continue indents`` guard in ``typeExpr``).

``peek_column()`` returns 0 at EOF; ``check_valid`` returns False for column 0
against any real constraint, so both EOF and layout boundaries terminate loops
non-consumingly.
"""

from __future__ import annotations

from typing import List, TypeVar

import parsy
from parsy import Parser, Result, alt, fail, generate

from systemf.surface.parser.helpers import (
    check_valid,
    match_token,
    peek_column,
)
from systemf.surface.parser.types import (
    AnyIndent,
    ArrowToken,
    CommaToken,
    DocstringToken,
    DocstringType,
    DotToken,
    ForallToken,
    IdentifierToken,
    LeftBracketToken,
    LeftParenToken,
    RightBracketToken,
    RightParenToken,
    TokenBase,
    UnitToken,
    ValidIndent,
)
from systemf.surface.types import (
    SurfaceListType,
    SurfaceType,
    SurfaceTypeConstructor,
    SurfaceUnitType,
    SurfaceTypeVar,
)

T = TypeVar("T")
type P[T] = Parser[List[TokenBase], T]


# =============================================================================
# Token Matching Helpers
# =============================================================================


def match_forall() -> P[ForallToken]:
    """Match a forall token (``forall`` keyword or ``∀``)."""

    @Parser
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.failure(index, "expected forall")
        token = tokens[index]
        if isinstance(token, ForallToken):
            return Result.success(index + 1, token)
        return Result.failure(index, f"expected forall, got {str(token)}")

    return parser


def match_inline_docstring() -> P[str | None]:
    """Match an inline docstring token (``-- ^``).

    Always succeeds: returns the docstring content if present, ``None``
    otherwise (non-consuming on no-match).
    """

    @Parser
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.success(index, None)
        token = tokens[index]
        if isinstance(token, DocstringToken) and token.docstring_type == DocstringType.FOLLOWING:
            return Result.success(index + 1, token.content)
        return Result.success(index, None)

    return parser


def match_inline_docstring_strict() -> P[str]:
    """Match an inline docstring token (``-- ^``).

    Fails if no inline docstring is present. Required for ``many``
    combinator in ``doc_type_parser``.
    """

    @Parser
    def parser(tokens: list, index: int) -> Result:
        if index >= len(tokens):
            return Result.failure(index, "expected inline docstring")
        token = tokens[index]
        if isinstance(token, DocstringToken) and token.docstring_type == DocstringType.FOLLOWING:
            return Result.success(index + 1, token.content)
        return Result.failure(index, "expected inline docstring")

    return parser


def attach_docs(ty: SurfaceType, pre: list[str], post: list[str]) -> SurfaceType:
    """Attach pre/post docstrings to a type node.

    Concatenates pre and post docs with newline separator if both exist.
    Uses dataclasses.replace to update the frozen dataclass.
    """
    from dataclasses import replace

    docs = pre + post
    if not docs:
        return ty
    docstring = "\n".join(docs)
    return replace(ty, docstring=docstring)


# =============================================================================
# Forward Declaration for Recursive Type Parser
# =============================================================================

# Used by type_atom_parser (parenthesised types) and type_tuple_parser.
# Both of these appear inside explicit delimiters, so they always use
# AnyIndent — the forward-declaration is initialised at the bottom of
# this module with type_parser(AnyIndent()).
_type_parser: P[SurfaceType] = parsy.forward_declaration()


# =============================================================================
# Type Parsers
# =============================================================================


def tycon_arg_parser() -> P[SurfaceTypeVar]:
    """Parse a single type-constructor argument with optional inline docstrings.

    Grammar:  ("--^" doc)* ident ("--^" doc)*
    """

    @generate
    def parser():
        pre_docs = yield match_inline_docstring_strict().many()
        ident_tok = yield match_token(IdentifierToken)
        post_docs = yield match_inline_docstring_strict().many()
        docs = pre_docs + post_docs
        docstring = "\n".join(docs) if docs else None
        return SurfaceTypeVar(
            name=ident_tok.value,
            location=ident_tok.location,
            docstring=docstring,
        )

    return parser


@generate
def type_tuple_parser() -> P[SurfaceType]:
    """Parse a tuple type: ``(t1, t2, ..., tn)``.

    Sugar for nested ``Pair`` types.  Always uses ``AnyIndent`` because the
    content is enclosed in parentheses.
    """
    from systemf.surface.types import SurfaceTypeTuple

    open_paren = yield match_token(LeftParenToken)
    loc = open_paren.location

    first = yield _type_parser
    elements = [first]

    while True:
        yield match_token(CommaToken)
        elem = yield _type_parser
        elements.append(elem)

        close_paren = yield match_token(RightParenToken).optional()
        if close_paren is not None:
            break

    return SurfaceTypeTuple(elements=elements, location=loc)


@generate
def unit_type_parser() -> P[SurfaceType]:
    """Parse unit type syntax: ()."""
    token = yield match_token(UnitToken)
    return SurfaceUnitType(location=token.location)


@generate
def type_list_parser() -> P[SurfaceType]:
    """Parse list type syntax: [t]."""
    open_bracket = yield match_token(LeftBracketToken)
    loc = open_bracket.location
    element = yield _type_parser
    yield match_token(RightBracketToken)
    return SurfaceListType(element=element, location=loc)


def type_atom_parser() -> P[SurfaceType]:
    """Parse a type atom — the smallest syntactic unit of a type.

    Tries in order:

    1. Parenthesised type — resets layout to ``AnyIndent`` (Idris2 semantics).
    2. Type constructor (uppercase identifier).
    3. Type variable (lowercase identifier).

    Returns ``None`` (non-consuming) if none of the above match so that callers
    can use ``.optional()`` cleanly.
    """

    @generate
    def parser():
        unit_ty = yield unit_type_parser.optional()
        if unit_ty is not None:
            return unit_ty

        list_ty = yield type_list_parser.optional()
        if list_ty is not None:
            return list_ty

        # Parenthesised type — layout constraint is reset inside parens.
        open_paren = yield match_token(LeftParenToken).optional()
        if open_paren is not None:
            inner = yield _type_parser
            yield match_token(RightParenToken)
            return inner

        ident_token = yield match_token(IdentifierToken).optional()
        if ident_token is not None:
            name = ident_token.value
            loc = ident_token.location
            if name[0].isupper():
                return SurfaceTypeConstructor(name=name, args=[], location=loc)
            else:
                return SurfaceTypeVar(name=name, location=loc)

        return None

    return parser


def type_app_parser(constraint: ValidIndent = None) -> P[SurfaceType]:
    """Parse a type application: ``F a b …``

    Parses one mandatory head atom followed by zero or more argument atoms.
    Before each additional argument the layout constraint is checked via
    ``peek_column()`` — this is the direct equivalent of Idris2's
    ``many (argExpr fname indents)`` where ``argExpr`` starts with
    ``continue indents``.

    Args:
        constraint: Layout constraint.  ``AnyIndent`` disables column checks.

    Returns:
        ``SurfaceType`` — either a single atom or an applied constructor.
    """
    if constraint is None:
        constraint = AnyIndent()

    @generate
    def parser():
        # Try tuple first — it starts with '(' but is a distinct syntactic form.
        tuple_result = yield type_tuple_parser.optional()
        if tuple_result is not None:
            return tuple_result

        # Mandatory head.
        first = yield type_atom_parser().optional()
        if first is None:
            yield fail("expected type")
            return None  # unreachable; satisfies type checker

        loc = first.location
        args: list[SurfaceType] = []

        while True:
            # Layout check: peek_column() returns 0 at EOF; any real constraint
            # rejects 0, so this terminates naturally at EOF as well.
            if not isinstance(constraint, AnyIndent):
                next_col = yield peek_column()
                if next_col == 0 or not check_valid(constraint, next_col):
                    break

            arg = yield type_atom_parser().optional()
            if arg is None:
                break
            args.append(arg)

        if not args:
            return first

        # Build SurfaceTypeConstructor with collected args.
        match first:
            case SurfaceTypeConstructor(name=name, args=[], location=_):
                return SurfaceTypeConstructor(name=name, args=args, location=loc)
            case SurfaceTypeVar(name=name, location=_):
                # Type variable in applied position (higher-kinded context).
                return SurfaceTypeConstructor(name=name, args=args, location=loc)
            case SurfaceTypeConstructor(name=name, args=existing_args, location=_):
                return SurfaceTypeConstructor(
                    name=name, args=existing_args + args, location=loc
                )
            case _:
                return SurfaceTypeConstructor(name=str(first), args=args, location=loc)

    return parser


def doc_type_parser(constraint: ValidIndent = None) -> P[SurfaceType]:
    """Parse a type with optional pre/post inline docstrings.

    Grammar::

        doc_type ::= ("--^" doc)* type_app ("--^" doc)*

    This wraps ``type_app_parser`` with docstring absorption at a
    precedence level tighter than arrow but looser than type application.

    Args:
        constraint: Layout constraint propagated to ``type_app_parser``.

    Returns:
        ``SurfaceType`` with ``docstring`` field populated if docs present.
    """
    if constraint is None:
        constraint = AnyIndent()

    @generate
    def parser():
        pre_docs = yield match_inline_docstring_strict().many()
        ty = yield type_app_parser(constraint)
        post_docs = yield match_inline_docstring_strict().many()
        return attach_docs(ty, pre_docs, post_docs)

    return parser


def type_arrow_parser(constraint: ValidIndent = None) -> P[SurfaceType]:
    """Parse a function type.  Right-associative.

    Grammar::

        type_arrow ::= type_app ("--^ doc"? "->" type_arrow)?

    The optional ``->`` is guarded by a layout check (mirrors Idris2's
    ``continue indents`` placed before the optional arrow in ``typeExpr``).

    Args:
        constraint: Layout constraint.  The ``->`` arrow is only consumed when
                    the token's column satisfies the constraint.

    Returns:
        ``SurfaceType`` — function type or a single application/atom.
    """
    if constraint is None:
        constraint = AnyIndent()

    @generate
    def parser():
        from systemf.surface.types import SurfaceTypeArrow

        left = yield doc_type_parser(constraint)
        loc = left.location

        # Guard the arrow with a column check before consuming it.
        # Non-consuming failure here causes the optional(..) below to yield None
        # cleanly, matching Idris2's `continue indents` semantics.
        if not isinstance(constraint, AnyIndent):
            next_col = yield peek_column()
            if next_col == 0 or not check_valid(constraint, next_col):
                return left

        arrow = yield match_token(ArrowToken).optional()
        if arrow is None:
            return left

        right = yield type_arrow_parser(constraint)
        return SurfaceTypeArrow(arg=left, ret=right, location=loc)

    return parser


def type_forall_parser(constraint: ValidIndent = None) -> P[SurfaceType]:
    """Parse a universally quantified type.

    Grammar::

        type_forall ::= ("forall" | "∀") ident+ "." type

    The outer ``constraint`` is propagated into the body so that layout
    boundaries are respected even inside a ``forall``.

    Args:
        constraint: Layout constraint propagated to the forall body.

    Returns:
        ``SurfaceType`` — one or more nested ``SurfaceTypeForall`` nodes.
    """
    if constraint is None:
        constraint = AnyIndent()

    @generate
    def parser():
        from systemf.surface.types import SurfaceTypeForall

        forall_token = yield match_forall()
        loc = forall_token.location

        var_tokens = yield match_token(IdentifierToken).at_least(1)
        yield match_token(DotToken)

        body = yield type_parser(constraint)

        result = SurfaceTypeForall(
            vars=[vt.value for vt in var_tokens],
            body=body,
            location=loc,
        )

        return result

    return parser


def type_parser(constraint: ValidIndent = None) -> P[SurfaceType]:
    """Top-level type parser.

    Tries ``forall`` first (with constraint propagated), then ``->`` form.

    This parser does **not** consume EOF — wrap with ``<< eof`` at entry
    points that require complete consumption.

    Args:
        constraint: Layout constraint.  Defaults to ``AnyIndent()`` (no
                    restriction).  Pass ``AfterPos(decl_col + 1)`` from
                    declaration parsers to respect top-level layout.

    Returns:
        ``SurfaceType`` — the parsed type.
    """
    if constraint is None:
        constraint = AnyIndent()
    return alt(
        type_forall_parser(constraint),
        type_arrow_parser(constraint),
    )


# Initialise the forward declaration used by type_atom_parser and
# type_tuple_parser.  Both contexts appear inside explicit delimiters
# (parentheses / tuple syntax) so AnyIndent is always correct here.
_type_parser.become(type_parser(AnyIndent()))


__all__ = [
    # Token matching helpers
    "match_token",
    "match_forall",
    "match_inline_docstring",
    "match_inline_docstring_strict",
    "attach_docs",
    # Type parsers (factories — call to get a Parser)
    "tycon_arg_parser",
    "type_tuple_parser",   # @generate Parser object (zero-arg, used inside parens)
    "type_atom_parser",
    "type_app_parser",
    "doc_type_parser",
    "type_arrow_parser",
    "type_forall_parser",
    # Main entry point
    "type_parser",
]
