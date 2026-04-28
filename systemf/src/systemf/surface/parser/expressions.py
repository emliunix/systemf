"""Expression parsers for System F surface language.

Implements expression parsers using the new helper combinators with explicit
constraint passing (Idris2-style layout-aware parsing).

Parsers implemented:
- Token matching helper (typed match_token)
- Atom parsers (variable, constructor, literal, paren)
- Lambda and type abstraction parsers
- Application parser (left-associative)
- Main expression entry point
"""

from __future__ import annotations

from typing import TypeVar, cast

from parsy import Parser as P
from parsy import Result, alt, fail, generate
from systemf.surface.parser.helpers import (
    AfterPos,
    AnyIndent,
    AtPos,
    ValidIndent,
    block,
    block_entries,
    check_valid,
    column,
    match_token,
    must_continue,
    peek_column,
)
from systemf.surface.parser.type_parser import type_app_parser, type_atom_parser, type_parser


def match_ident() -> P[IdentifierToken]:
    """Match an identifier token."""
    return match_token(IdentifierToken)


from systemf.surface.parser.types import (
    AndToken,
    AppendToken,
    ArrowToken,
    CaseToken,
    ColonToken,
    CommaToken,
    DelimiterToken,
    DotToken,
    ElseToken,
    EqToken,
    GeToken,
    GtToken,
    DoubleColonToken,
    IdentifierToken,
    IfToken,
    InToken,
    KeywordToken,
    LambdaToken,
    LeftParenToken,
    LeToken,
    LetToken,
    LtToken,
    MinusToken,
    NeToken,
    NumberToken,
    OfToken,
    OperatorToken,
    OrToken,
    PlusToken,
    RightParenToken,
    SlashToken,
    StarToken,
    StringToken,
    ThenToken,
    TokenBase,
)
from systemf.surface.types import (
    SurfaceAbs,
    SurfaceAnn,
    SurfaceApp,
    SurfaceBranch,
    SurfaceCase,
    SurfaceIf,
    SurfaceLet,
    SurfaceLit,
    SurfaceLitPattern,
    SurfaceOp,
    SurfacePattern,
    SurfacePatternBase,
    SurfacePatternCons,
    SurfacePatternTuple,
    SurfaceTerm,
    SurfaceTuple,
    SurfaceType,
    SurfaceTypeApp,
    SurfaceVar,
    SurfaceVarPattern,
    SurfaceWildcardPattern,
    ValBind,
)

# Type variable for generic token parsers
T = TypeVar("T", bound=TokenBase)


# =============================================================================
# Keyword and Symbol Matchers
# =============================================================================


def match_keyword_value(value: str) -> P[KeywordToken]:
    """Match a generic KeywordToken with an exact keyword value."""

    @generate
    def parser():
        token = yield match_token(KeywordToken)
        if token.keyword != value:
            yield fail(f"expected keyword '{value}', got '{token.keyword}'")
        return token

    return parser


def match_operator(value: str) -> P[OperatorToken]:
    """Match an operator token with an exact operator string."""

    @generate
    def parser():
        token = yield match_token(OperatorToken)
        if token.operator != value:
            yield fail(f"expected operator '{value}', got '{token.operator}'")
        return token

    return parser


def match_delimiter(value: str) -> P[DelimiterToken]:
    """Match a delimiter token with an exact delimiter string."""

    @generate
    def parser():
        token = yield match_token(DelimiterToken)
        if token.delimiter != value:
            yield fail(f"expected delimiter '{value}', got '{token.delimiter}'")
        return token

    return parser


def match_symbol(value: str) -> P[OperatorToken | DelimiterToken]:
    """Match an operator or delimiter token with the given value."""
    return cast(P[OperatorToken | DelimiterToken], match_operator(value) | match_delimiter(value))


# =============================================================================
# Operator Token Matchers
# =============================================================================

# Arithmetic operators
PLUS = match_token(PlusToken)
MINUS = match_token(MinusToken)
STAR = match_token(StarToken)
SLASH = match_token(SlashToken)

# Comparison operators
EQ = match_token(EqToken)  # ==
NE = match_token(NeToken)  # /=
LT = match_token(LtToken)  # <
GT = match_token(GtToken)  # >
LE = match_token(LeToken)  # <=
GE = match_token(GeToken)  # >=

# Logical operators
AND = match_token(AndToken)  # &&
OR = match_token(OrToken)  # ||

# String concatenation
APPEND = match_token(AppendToken)  # ++

# Cons operator
COLON = match_token(ColonToken)  # :


# =============================================================================
# Atom Parsers (no constraint needed)
# =============================================================================


def variable_parser() -> P[SurfaceVar]:
    """Parse a variable reference: ident.

    Returns:
        SurfaceVar with the variable name and location
    """

    @generate
    def parser():
        token = yield match_token(IdentifierToken)
        return SurfaceVar(name=token.value, location=token.location)

    return parser


def literal_parser() -> P[SurfaceLit]:
    """Parse an integer or string literal.

    Returns:
        SurfaceLit with the value and location
    """

    @generate
    def parser():
        # Try integer literal first
        num_token = yield match_token(NumberToken).optional()
        if num_token is not None:
            return SurfaceLit(
                prim_type="Int", value=int(num_token.value), location=num_token.location
            )

        # Try string literal
        str_token = yield match_token(StringToken).optional()
        if str_token is not None:
            return SurfaceLit(
                prim_type="String", value=str_token.value, location=str_token.location
            )

        # Neither matched - fail
        yield fail("expected literal")

    return parser


def tuple_parser() -> P[SurfaceTerm]:
    """Parse a tuple expression: (e1, e2, ..., en).

    Sugar for nested Pair constructors: Pair e1 (Pair e2 (... en))

    Returns:
        SurfaceTuple containing the elements
    """

    @generate
    def parser():
        from systemf.surface.types import SurfaceTuple

        open_paren = yield match_token(LeftParenToken)
        loc = open_paren.location

        # Parse first element
        first = yield expr_parser(AnyIndent())
        elements = [first]

        # Parse comma-separated elements
        while True:
            yield match_token(CommaToken)
            elem = yield expr_parser(AnyIndent())
            elements.append(elem)

            # Check if we're at the closing paren
            close_paren = yield match_token(RightParenToken).optional()
            if close_paren is not None:
                break

        return SurfaceTuple(elements=elements, location=loc)

    return parser


def paren_parser() -> P[SurfaceTerm]:
    """Parse a parenthesized expression: ( expr ) or tuple: (e1, e2, ..., en).

    Returns:
        The parsed expression inside the parentheses, or a tuple if commas are present

    This parser uses type_parser() directly for parsing types.
    """

    @generate
    def parser():
        # Try tuple first (it requires a comma)
        tuple_result = yield tuple_parser().optional()
        if tuple_result is not None:
            return tuple_result

        # Regular parenthesized expression
        yield match_token(LeftParenToken)
        # Parse expression with AnyIndent constraint inside parens
        expr = yield expr_parser(AnyIndent())
        yield match_token(RightParenToken)
        return expr

    return parser


def atom_base_parser(constraint: ValidIndent | None = None) -> P[SurfaceTerm]:
    """Parse a base atom (no post-fix operators).

    Tries paren, constructor, literal, or variable in that order.

    Args:
        constraint: Optional layout constraint for constructor arguments

    Returns:
        The parsed atomic term
    """

    @generate
    def parser():
        # Try parenthesized expression first
        paren = yield paren_parser().optional()
        if paren is not None:
            return paren

        # Try literal
        lit = yield literal_parser().optional()
        if lit is not None:
            return lit

        # Try variable (includes all names, constructors resolved in elaborator)
        var = yield variable_parser().optional()
        if var is not None:
            return var

        # No match - fail
        yield fail("expected atom")

    return parser


def atom_parser(constraint: ValidIndent | None = None) -> P[SurfaceTerm]:
    """Parse an atom with optional post-fix operators.

    Post-fix operators include:
    - @T or [T]: Type application
    - :T: Type annotation

    Args:
        constraint: Optional layout constraint for constructor arguments

    Returns:
        The parsed atom, possibly wrapped in post-fix operators
    """

    @generate
    def parser():
        atom = yield atom_base_parser(constraint)

        # Apply post-fix operators greedily
        while True:
            # Type application with @ (only syntax supported)
            # Use type_atom_parser to only consume simple types
            # Complex types like (Maybe Int) require parentheses
            type_app = yield (
                match_token(OperatorToken).bind(
                    lambda tok: (
                        type_atom_parser() if tok.operator == "@" else fail("expected operator '@'")
                    )
                )
            ).optional()
            if type_app is not None:
                atom = SurfaceTypeApp(func=atom, type_arg=type_app, location=atom.location)
                continue

            # Type annotation (using :: not :)
            type_ann = yield (match_token(DoubleColonToken) >> type_parser()).optional()
            if type_ann is not None:
                atom = SurfaceAnn(term=atom, type=type_ann, location=atom.location)
                continue

            break

        return atom

    return parser


# =============================================================================
# Application Parser
# =============================================================================


def app_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse function application (left-associative).

    Parses one or more atoms and combines them into left-associative
    applications: ((f x) y) z

    Args:
        constraint: Layout constraint for checking additional argument columns

    Returns:
        SurfaceApp tree or a single atom if only one parsed
    """

    @generate
    def parser():
        # Parse first atom with constraint
        first = yield atom_parser(constraint)
        loc = first.location

        # Parse additional atoms for application, respecting constraint
        args: list[SurfaceTerm] = []
        while True:
            # Check constraint before parsing next argument
            if not isinstance(constraint, AnyIndent):
                next_col = yield peek_column()
                if next_col > 0 and not check_valid(constraint, next_col):
                    break

            arg = yield atom_parser(constraint).optional()
            if arg is None:
                break
            args.append(arg)

        # Build left-associative application chain
        if not args:
            return first

        result = first
        for arg in args:
            result = SurfaceApp(func=result, arg=arg, location=loc)

        return result

    return parser




# =============================================================================
# Operator Expression Parsers
# =============================================================================


def multiplicative_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse multiplicative expressions: left (*|/) right.

    Highest precedence among operators, just above application.

    Args:
        constraint: Layout constraint (passed through to operands)

    Returns:
        SurfaceOp tree for multiplicative operations or a single term
    """

    @generate
    def parser():
        # Parse left operand (application level)
        left = yield app_parser(constraint)
        loc = left.location

        # Parse zero or more (*|/) right-operand pairs
        ops_and_rights = []
        while True:
            # Try each operator
            op = yield (STAR | SLASH).optional()
            if op is None:
                break
            right = yield app_parser(constraint)
            ops_and_rights.append((op, right))

        # Build left-associative tree
        result = left
        for op, right in ops_and_rights:
            result = SurfaceOp(left=result, op=op.value, right=right, location=loc)

        return result

    return parser


def additive_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse additive expressions: left (+|-|++) right.

    Lower precedence than multiplicative, higher than comparison.

    Args:
        constraint: Layout constraint (passed through to operands)

    Returns:
        SurfaceOp tree for additive operations or a single term
    """

    @generate
    def parser():
        # Parse left operand (multiplicative level)
        left = yield multiplicative_parser(constraint)
        loc = left.location

        # Parse zero or more (+|-|++) right-operand pairs
        ops_and_rights = []
        while True:
            # Try each operator
            op = yield (PLUS | MINUS | APPEND).optional()
            if op is None:
                break
            right = yield multiplicative_parser(constraint)
            ops_and_rights.append((op, right))

        # Build left-associative tree
        result = left
        for op, right in ops_and_rights:
            result = SurfaceOp(left=result, op=op.value, right=right, location=loc)

        return result

    return parser


def cons_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse cons expressions: left : right (right-associative).

    Precedence 5 in Haskell, between additive (6) and comparison (4).
    Right-associative: 1 : 2 : Nil parses as 1 : (2 : Nil)

    Args:
        constraint: Layout constraint (passed through to operands)

    Returns:
        SurfaceOp tree for cons operations or a single term
    """

    @generate
    def parser():
        # Parse left operand (additive level - tighter)
        left = yield additive_parser(constraint)
        loc = left.location

        # Try to parse : right-operand
        colon = yield COLON.optional()
        if colon is None:
            return left

        # Right side uses cons_parser for right-associativity
        right = yield cons_parser(constraint)

        return SurfaceOp(left=left, op=":", right=right, location=loc)

    return parser


def comparison_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse comparison expressions: left (==|/=|<|>|<=|>=) right.

    Lower precedence than cons, higher than logical.

    Args:
        constraint: Layout constraint (passed through to operands)

    Returns:
        SurfaceOp tree for comparison operations or a single term
    """

    @generate
    def parser():
        # Parse left operand (cons level)
        left = yield cons_parser(constraint)
        loc = left.location

        # Parse zero or more comparison-operator right-operand pairs
        ops_and_rights = []
        while True:
            # Try each comparison operator
            op = yield (EQ | NE | LT | GT | LE | GE).optional()
            if op is None:
                break
            right = yield additive_parser(constraint)
            ops_and_rights.append((op, right))

        # Build left-associative tree
        result = left
        for op, right in ops_and_rights:
            result = SurfaceOp(left=result, op=op.value, right=right, location=loc)

        return result

    return parser


def logical_and_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse logical AND expressions: left && right.

    Lower precedence than comparison, higher than logical OR.

    Args:
        constraint: Layout constraint (passed through to operands)

    Returns:
        SurfaceOp tree for logical AND or a single term
    """

    @generate
    def parser():
        # Parse left operand (comparison level)
        left = yield comparison_parser(constraint)
        loc = left.location

        # Parse zero or more && right-operand pairs
        ops_and_rights = []
        while True:
            op = yield AND.optional()
            if op is None:
                break
            right = yield comparison_parser(constraint)
            ops_and_rights.append((op, right))

        # Build left-associative tree
        result = left
        for op, right in ops_and_rights:
            result = SurfaceOp(left=result, op=op.value, right=right, location=loc)

        return result

    return parser


def logical_or_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse logical OR expressions: left || right.

    Lowest precedence among operators.

    Args:
        constraint: Layout constraint (passed through to operands)

    Returns:
        SurfaceOp tree for logical OR or a single term
    """

    @generate
    def parser():
        # Parse left operand (logical AND level)
        left = yield logical_and_parser(constraint)
        loc = left.location

        # Parse zero or more || right-operand pairs
        ops_and_rights = []
        while True:
            op = yield OR.optional()
            if op is None:
                break
            right = yield logical_and_parser(constraint)
            ops_and_rights.append((op, right))

        # Build left-associative tree
        result = left
        for op, right in ops_and_rights:
            result = SurfaceOp(left=result, op=op.value, right=right, location=loc)

        return result

    return parser


def op_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse operator expressions with proper precedence.

    Entry point for operator parsing. Handles all operator types
    with correct precedence and left-associativity.

    Args:
        constraint: Layout constraint (passed through to operands)

    Returns:
        SurfaceTerm possibly wrapped in SurfaceOp nodes
    """
    return logical_or_parser(constraint)


# =============================================================================
# Lambda and Type Abstraction Parsers
# =============================================================================


def lambda_param_parser() -> P[tuple[str, SurfaceType | None]]:
    """Parse a single lambda parameter.

    Supports:
    - x (unannotated)
    - (x :: T) (annotated with parentheses)

    Note: bare ``x :: T`` (without parens) is intentionally not supported because
    it creates ambiguity with the lambda arrow: ``\\x :: Int -> body`` could be
    parsed as ``\\x :: (Int -> body)`` or ``(\\x :: Int) -> body``.

    Returns:
        Tuple of (parameter_name, optional_type)
    """

    @generate
    def parser():
        paren_param = (
            yield (match_token(LeftParenToken) >> match_ident() << match_token(DoubleColonToken))
            .bind(
                lambda name_token: (
                    type_parser().map(lambda ty: (name_token.name, ty))
                    << match_token(RightParenToken)
                )
            )
            .optional()
        )

        if paren_param is not None:
            return paren_param

        ident = yield match_ident()
        return (ident.name, None)

    return parser


def lambda_parser(constraint: ValidIndent) -> P[SurfaceAbs]:
    """Parse a lambda abstraction: λx → e or \\x → e.

    Supports optional type annotation: λ(x :: T) → e
    Supports mixed annotated and unannotated params: λ(x :: Int) y → e

    Args:
        constraint: Layout constraint (passed through to body parser)

    Returns:
        SurfaceAbs with the lambda abstraction
    """

    @generate
    def parser():
        # Match lambda symbol (LAMBDA token represents \\ or λ)
        lam_token = yield match_token(LambdaToken)
        loc = lam_token.location

        # Parse one or more parameters (each can be annotated or not)
        annotated_params: list[tuple[str, SurfaceType | None]] = []
        while True:
            # Try to parse a parameter
            param = yield lambda_param_parser().optional()
            if param is None:
                break
            annotated_params.append(param)

        if not annotated_params:
            yield fail("lambda must have at least one parameter")

        # Parse arrow
        yield match_token(ArrowToken)

        # Parse body (respecting layout constraint)
        body = yield expr_parser(constraint)

        # Return a single SurfaceAbs with all parameters
        # Desugaring pass will convert to nested lambdas
        return SurfaceAbs(
            params=annotated_params,
            body=body,
            location=loc,
        )

    return parser


# =============================================================================
# Pattern Parser (for case alternatives)
# =============================================================================


def pattern_literal_parser() -> P[SurfaceLitPattern]:
    """Parse a literal pattern: 42 or \"hello\".

    Deterministic: literal tokens (NumberToken, StringToken) are disjoint
    from IdentifierToken, so there's no ambiguity with variable patterns.

    Returns:
        SurfaceLitPattern with prim_type and value
    """

    @generate
    def parser():
        num_token = yield match_token(NumberToken).optional()
        if num_token is not None:
            return SurfaceLitPattern(
                prim_type="Int", value=int(num_token.value), location=num_token.location
            )

        str_token = yield match_token(StringToken).optional()
        if str_token is not None:
            return SurfaceLitPattern(
                prim_type="String", value=str_token.value, location=str_token.location
            )

        yield fail("expected literal pattern")

    return parser


def pattern_atom_parser() -> P[SurfacePatternBase]:
    """Parse atomic patterns: identifier, literal, tuple, or grouped pattern.

    Used as constructor arguments or standalone patterns.
    Does NOT handle cons operator - that's done at higher level.

    Returns:
        SurfacePattern, SurfacePatternTuple, SurfacePatternCons, or SurfaceLitPattern
    """

    @generate
    def parser():
        # Try tuple first: (x, y)
        tuple_result = yield pattern_tuple_parser().optional()
        if tuple_result is not None:
            return tuple_result

        # Try grouped pattern: (pattern)
        open_paren = yield match_token(LeftParenToken).optional()
        if open_paren is not None:
            # Parse inner pattern (can include cons)
            inner = yield pattern_cons_parser()
            yield match_token(RightParenToken)
            return inner

        # Try literal pattern (deterministic: NumberToken/StringToken are disjoint from IdentifierToken)
        lit = yield pattern_literal_parser().optional()
        if lit is not None:
            return lit

        # Fall back to simple identifier - returns flat pattern structure
        name_token = yield match_token(IdentifierToken).optional()
        if name_token is None:
            yield fail("expected pattern")

        if name_token.value == "_":
            return SurfaceWildcardPattern(location=name_token.location)

        return SurfacePattern(
            patterns=[SurfaceVarPattern(name=name_token.value, location=name_token.location)],
            location=name_token.location
        )

    return parser


def pattern_base_parser() -> P[SurfacePatternBase]:
    """Parse a base pattern: variable, constructor with args, or literal.

    Returns a flat pattern list where all identifiers are SurfaceVarPattern,
    or a SurfaceLitPattern for literal patterns.
    The rename phase will disambiguate:
    - [VarPat("x")] -> single item: variable or nullary constructor
    - [VarPat("Cons"), VarPat("x"), ...] -> multiple items: constructor pattern

    Examples:
        x                    -> SurfacePattern(patterns=[VarPat("x")])
        Cons x xs           -> SurfacePattern(patterns=[VarPat("Cons"), VarPat("x"), VarPat("xs")])
        Cons (x, y) zs      -> SurfacePattern(patterns=[VarPat("Cons"), tuple, VarPat("zs")])
        Pair (Cons x xs) y  -> SurfacePattern(patterns=[VarPat("Pair"), cons, VarPat("y")])
        42                  -> SurfaceLitPattern(prim_type="Int", value=42)

    Returns:
        SurfacePattern or SurfaceLitPattern
    """

    @generate
    def parser():
        # Try literal pattern first (deterministic: disjoint token types)
        lit = yield pattern_literal_parser().optional()
        if lit is not None:
            return lit

        # Parse pattern name (constructor or variable)
        name_token = yield match_token(IdentifierToken).optional()
        if name_token is None:
            yield fail("expected pattern")

        name = name_token.value
        loc = name_token.location

        # Parse pattern arguments (atoms: identifiers, literals, tuples, grouped patterns)
        args: list[SurfacePatternBase] = []
        while True:
            # Try to parse an atomic pattern
            arg = yield pattern_atom_parser().optional()
            if arg is None:
                break
            args.append(arg)

        if name == "_":
            if args:
                yield fail("wildcard pattern _ cannot have arguments")
            return SurfaceWildcardPattern(location=loc)

        # Build flat pattern list: [VarPat(name), arg1, arg2, ...]
        # All identifiers are SurfaceVarPattern - rename phase disambiguates
        patterns: list[SurfacePatternBase] = [SurfaceVarPattern(name=name, location=loc)]
        patterns.extend(args)
        return SurfacePattern(patterns=patterns, location=loc)

    return parser


def pattern_tuple_parser() -> P[SurfacePattern]:
    """Parse a tuple pattern: (p1, p2, ..., pn).

    Sugar for nested Pair patterns: Pair p1 (Pair p2 (... pn))

    Returns:
        SurfacePatternTuple containing the elements
    """

    @generate
    def parser():
        from systemf.surface.types import SurfacePatternTuple

        open_paren = yield match_token(LeftParenToken)
        loc = open_paren.location

        # Parse first element using pattern_parser (handles nested tuples, constructors, vars)
        first = yield pattern_parser()
        elements = [first]

        # Parse comma-separated elements
        while True:
            yield match_token(CommaToken)
            elem = yield pattern_parser()
            elements.append(elem)

            # Check if we're at the closing paren
            close_paren = yield match_token(RightParenToken).optional()
            if close_paren is not None:
                break

        return SurfacePatternTuple(elements=elements, location=loc)

    return parser


def pattern_cons_parser() -> P[SurfacePatternBase]:
    """Parse a cons pattern: head : tail (right-associative).

    Examples:
        x : xs                -> SurfacePatternCons(head=x, tail=xs)
        x : y : zs           -> SurfacePatternCons(head=x, tail=SurfacePatternCons(head=y, tail=zs))
        Cons x xs            -> SurfacePattern(patterns=[VarPat("Cons"), VarPat("x"), VarPat("xs")])
        x                    -> SurfacePattern(patterns=[VarPat("x")])
        (x)                  -> SurfacePattern(patterns=[VarPat("x")])
        (Cons x xs)          -> SurfacePattern(patterns=[VarPat("Cons"), VarPat("x"), VarPat("xs")])
        (x : xs)             -> SurfacePatternCons(head=x, tail=xs)
        x : (y : zs)         -> SurfacePatternCons(head=x, tail=SurfacePatternCons(head=y, tail=zs))

    Returns:
        SurfacePatternCons if cons pattern, otherwise base pattern
    """
    from systemf.surface.types import SurfacePatternCons

    @generate
    def parser():
        # Parse left side (try grouping first, then base pattern)
        # Check if starts with '(' for grouping
        open_paren = yield match_token(LeftParenToken).optional()
        if open_paren is not None:
            # Parse inner pattern (cons allowed inside parens)
            inner = yield pattern_cons_parser()
            yield match_token(RightParenToken)
            left = inner
        else:
            # Regular base pattern (Constructor vars... or variable)
            left = yield pattern_base_parser()

        loc = left.location

        # Try to parse : tail
        colon = yield COLON.optional()
        if colon is None:
            return left

        # Right side uses pattern_cons_parser for right-associativity
        right = yield pattern_cons_parser()

        return SurfacePatternCons(head=left, tail=right, location=loc)

    return parser


def pattern_parser() -> P[SurfacePatternBase]:
    """Parse a pattern: tuple, cons, constructor, or variable pattern.

    Returns:
        SurfacePattern, SurfacePatternTuple, or SurfacePatternCons
    """

    @generate
    def parser():
        # Try tuple pattern first (must have commas: (x, y))
        tuple_result = yield pattern_tuple_parser().optional()
        if tuple_result is not None:
            return tuple_result

        # Try cons pattern (handles x : xs and falls back to base pattern)
        return (yield pattern_cons_parser())

    return parser


# =============================================================================
# Case Expression Parser (layout-sensitive)
# =============================================================================


def case_alt(constraint: ValidIndent) -> P[SurfaceBranch]:
    """Parse a single case branch: pattern → expr.

    Args:
        constraint: Layout constraint for the branch body

    Returns:
        SurfaceBranch with pattern and body expression
    """

    @generate
    def parser():
        pat = yield pattern_parser()
        loc = pat.location
        yield match_token(ArrowToken)

        # Transform constraint for the expression body (similar to let_binding)
        # This prevents the expression from consuming subsequent branches
        expr_constraint: ValidIndent
        match constraint:
            case AtPos(col=c):
                expr_constraint = AfterPos(col=c + 1)
            case _:
                expr_constraint = constraint

        body = yield expr_parser(expr_constraint)
        return SurfaceBranch(pattern=pat, body=body, location=loc)

    return parser


def case_parser(constraint: ValidIndent) -> P[SurfaceCase]:
    """Parse a case expression: case expr of branches.

    Layout-sensitive: captures column after 'of' and uses block_entries
    to parse branches at that indentation level.

    Args:
        constraint: Layout constraint (passed through to scrutinee)

    Returns:
        SurfaceCase with scrutinee and branches
    """

    @generate
    def parser():
        case_token = yield match_token(CaseToken)
        loc = case_token.location
        scrutinee = yield expr_parser(constraint)
        yield match_token_value_of(
            OfToken, "of", fallback=match_token(KeywordToken) >> match_keyword_value("of")
        )

        # Parse branches (supports both explicit braces { ... } and layout indentation)
        branches = yield block(case_alt)

        return SurfaceCase(scrutinee=scrutinee, branches=branches, location=loc)

    return parser


def match_token_value_of(
    token_cls: type[T], expected: str, fallback: P[KeywordToken] | None = None
) -> P[T | KeywordToken]:
    """Match a token class and also validate its textual value.

    Used as a compatibility bridge where keyword subclasses may or may not exist.
    """

    @generate
    def parser():
        token = yield match_token(token_cls).optional()
        if token is not None:
            text = getattr(token, "keyword", None) or getattr(token, "value", None)
            if text == expected:
                return token
        if fallback is not None:
            return (yield fallback)
        yield fail(f"expected {expected}")

    return parser


# =============================================================================
# Let Expression Parser (layout-sensitive)
# =============================================================================


def let_binding(constraint: ValidIndent) -> P[ValBind]:
    """Parse a single let binding: ident [params] [: type] = expr.

    Supports:
    - Simple binding: x = 1
    - Typed binding: x : Int = 1
    - Function binding: f x y = x + y (desugared to lambda)

    Args:
        constraint: Layout constraint for the binding start column

    Returns:
        ValBind with name, type_ann, value, and location
    """

    @generate
    def parser():
        var_token = yield match_token(IdentifierToken)
        var_name = var_token.value
        loc = var_token.location

        # Parse optional parameters (for function definitions like "f x y = ...")
        params = []
        while True:
            param_token = yield match_token(IdentifierToken).optional()
            if param_token is None:
                break
            params.append(param_token.value)

        # Optional type annotation (applies to the whole function if params present)
        var_type = yield (match_token(DoubleColonToken) >> type_parser()).optional()

        yield match_operator("=")

        # For expression value, use AfterPos to allow spanning multiple columns
        # If constraint is AtPos(col), expression can use columns > col (not >=)
        # This prevents consuming the next binding which is at column col
        expr_constraint: ValidIndent
        match constraint:
            case AtPos(col=c):
                expr_constraint = AfterPos(col=c + 1)  # Strictly greater than binding column
            case _:
                expr_constraint = constraint

        value = yield expr_parser(expr_constraint)

        # If we have parameters, build a lambda abstraction
        # f x y = body  becomes  f = \x y -> body
        if params:
            # Build nested lambdas from right to left
            for param in reversed(params):
                value = SurfaceAbs(var=param, var_type=None, body=value, location=loc)

        return ValBind(
            name=var_name,
            type_ann=var_type,
            value=value,
            location=loc
        )

    return parser


def let_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Parse a let expression: let bindings in expr.

    Layout-sensitive: captures column after 'let' and uses block_entries
    to parse bindings at that indentation level.

    Args:
        constraint: Layout constraint (passed through to expressions)

    Returns:
        SurfaceLet with list of bindings and body
    """

    @generate
    def parser():
        let_token = yield match_token(LetToken)
        loc = let_token.location

        # Enter layout mode: capture column of first binding token
        col = yield column()
        bindings = yield block_entries(AtPos(col=col), let_binding)

        # Validate 'in' keyword is at >= parent's column
        yield must_continue(constraint, "in")
        yield match_token(InToken)
        body = yield expr_parser(constraint)

        return SurfaceLet(bindings=bindings, body=body, location=loc)

    return parser


# =============================================================================
# If Expression Parser
# =============================================================================


def if_parser(constraint: ValidIndent) -> P[SurfaceIf]:
    """Parse an if-then-else expression: if expr then expr else expr.

    Args:
        constraint: Layout constraint (passed through to branch expressions)

    Returns:
        SurfaceIf with condition and branches
    """

    @generate
    def parser():
        if_token = yield match_token(IfToken)
        loc = if_token.location
        cond = yield expr_parser(constraint)
        yield match_token(ThenToken)
        then_branch = yield expr_parser(constraint)
        yield match_token(ElseToken)
        else_branch = yield expr_parser(constraint)
        return SurfaceIf(cond=cond, then_branch=then_branch, else_branch=else_branch, location=loc)

    return parser


# =============================================================================
# Main Expression Parser
# =============================================================================


def expr_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    """Main expression parser - tries all expression forms.

    Tries in order:
    1. Lambda abstraction
    2. Type abstraction
    3. If-then-else
    4. Case expression
    5. Let expression
    6. Operator expressions (includes application)

    Args:
        constraint: Layout constraint for layout-sensitive expressions

    Returns:
        The parsed expression
    """
    return alt(
        lambda_parser(constraint),
        if_parser(constraint),
        case_parser(constraint),
        let_parser(constraint),
        op_parser(constraint),
    )


# =============================================================================
# Public API
# =============================================================================


__all__ = [
    # Token matching
    "match_token",
    # Atom parsers
    "variable_parser",
    "literal_parser",
    "paren_parser",
    "atom_base_parser",
    "atom_parser",
    # Pattern parsers
    "pattern_parser",
    # Expression parsers
    "app_parser",
    "lambda_parser",
    "if_parser",
    "case_parser",
    "let_parser",
    "let_binding",
    "case_alt",
    "expr_parser",
]
