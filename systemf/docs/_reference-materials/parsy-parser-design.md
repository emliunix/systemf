# Parsy-Based Parser Architecture Design

## Overview

This document specifies the architecture for replacing the 600-line recursive descent parser with a parsy-based parser using monadic parser combinators and Python generators (@generate decorator).

## Goals

1. Replace imperative recursive descent with declarative parser combinators
2. Use `@generate` decorator for Haskell-like do-notation syntax
3. Maintain compatibility with existing Lexer, Token, and AST types
4. Preserve location information for error messages
5. Enable easier maintenance and extension

## Module Structure

### File Organization

```
src/systemf/surface/
├── __init__.py
├── ast.py                 # Existing - no changes
├── lexer.py               # Existing - no changes
├── parser.py              # NEW - parsy-based parser (replaces old parser.py)
├── parsers/               # NEW - parser modules (optional split)
│   ├── __init__.py
│   ├── tokens.py          # Token matching primitives
│   ├── types.py           # Type expression parsers
│   ├── terms.py           # Term expression parsers
│   └── declarations.py    # Declaration parsers
└── parsy_parser.py        # Alternative: single-file approach
```

**Decision**: Use **single-file approach** (`parser.py` replacement) for simplicity. The grammar is small enough (~20 rules) to fit comfortably in one file.

### Naming Conventions

| Component | Naming Pattern | Example |
|-----------|---------------|---------|
| Parser functions | `parse_<rule>` | `parse_expression`, `parse_type` |
| @generate parsers | `<rule>_parser` | `lambda_parser`, `app_parser` |
| Token matchers | `match_<token>` | `match_ident`, `match_arrow` |
| Helpers | `_<name>` | `_make_app`, `_left_fold` |

## Token Stream Integration

### Token Matching Primitives

Parsy works with any sequence, including lists of Token objects. We need primitives that match tokens by type:

```python
from parsy import generate, Parser

def match_token(token_type: str) -> Parser:
    """Match a token of specific type, return the token."""
    @Parser
    def match(tokens, index):
        if index < len(tokens) and tokens[index].type == token_type:
            return Result.success(index + 1, tokens[index])
        return Result.failure(index, f"expected {token_type}")
    return match

def match_value(token_type: str, value: str) -> Parser:
    """Match a token with specific type and value."""
    @Parser
    def match(tokens, index):
        if index < len(tokens):
            tok = tokens[index]
            if tok.type == token_type and tok.value == value:
                return Result.success(index + 1, tok)
        return Result.failure(index, f"expected {token_type}({value!r})")
    return match
```

### Token Matchers (Pre-defined)

```python
# Keywords
DATA = match_token("DATA")
LET = match_token("LET")
IN = match_token("IN")
CASE = match_token("CASE")
OF = match_token("OF")
FORALL = match_token("FORALL")
LAMBDA = match_token("LAMBDA")
TYPELAMBDA = match_token("TYPELAMBDA")

# Operators
ARROW = match_token("ARROW")
EQUALS = match_token("EQUALS")
COLON = match_token("COLON")
BAR = match_token("BAR")
AT = match_token("AT")
DOT = match_token("DOT")

# Delimiters
LPAREN = match_token("LPAREN")
RPAREN = match_token("RPAREN")
LBRACKET = match_token("LBRACKET")
RBRACKET = match_token("RBRACKET")
LBRACE = match_token("LBRACE")
RBRACE = match_token("RBRACE")

# Values
IDENT = match_token("IDENT").map(lambda t: t.value)
CONSTRUCTOR = match_token("CONSTRUCTOR").map(lambda t: t.value)
NUMBER = match_token("NUMBER").map(lambda t: t.value)
EOF = match_token("EOF")
```

### Location Preservation

Since tokens carry location information, we extract it from the first token consumed:

```python
@generate
def lambda_parser():
    loc = (yield LAMBDA).location  # Capture location from token
    var = yield IDENT
    var_type = yield (COLON >> type_parser()).optional()
    yield ARROW
    body = yield term_parser()
    return SurfaceAbs(var, var_type, body, loc)
```

## Grammar-to-Parser Mapping

### 1. Declarations

```
decl ::= "data" CON ident* "=" constr ("|" constr)*
       | ident (":" type)? "=" term
```

**Design**: Use @generate for clarity with multiple components.

```python
@generate
def data_declaration():
    loc = (yield DATA).location
    name = yield CONSTRUCTOR
    params = yield IDENT.many()
    yield EQUALS
    constrs = yield sep_by1(constructor, BAR)
    return SurfaceDataDeclaration(name, params, constrs, loc)

@generate
def term_declaration():
    name = yield IDENT
    type_ann = yield (COLON >> type_parser()).optional()
    yield EQUALS
    body = yield declaration_body()
    return SurfaceTermDeclaration(name, type_ann, body, loc)

declaration = data_declaration | term_declaration
```

### 2. Terms

```
term ::= "\" ident (":" type)? "->" term
       | "let" ident "=" term "in" term
       | "case" term "of" "{" branch* "}"
       | "/\" ident "." term
       | app
```

**Design**: Recursive grammar - use @generate with forward reference.

```python
@generate
def lambda_parser():
    loc = (yield LAMBDA).location
    var = yield IDENT
    var_type = yield (COLON >> type_parser()).optional()
    yield ARROW
    body = yield term_parser()  # Forward reference
    return SurfaceAbs(var, var_type, body, loc)

@generate
def let_parser():
    loc = (yield LET).location
    name = yield IDENT
    yield EQUALS
    value = yield term_parser()
    yield IN
    body = yield term_parser()
    return SurfaceLet(name, value, body, loc)

@generate
def case_parser():
    loc = (yield CASE).location
    scrutinee = yield term_parser()
    yield OF
    yield LBRACE
    branches = yield sep_by(branch, BAR)
    yield RBRACE
    return SurfaceCase(scrutinee, branches, loc)

@generate
def type_abs_parser():
    loc = (yield TYPELAMBDA).location
    var = yield IDENT
    yield DOT
    body = yield term_parser()
    return SurfaceTypeAbs(var, body, loc)

term_parser = lambda_parser | let_parser | case_parser | type_abs_parser | app_parser
```

### 3. Applications (Left-Associative)

```
app ::= atom+
```

**Design**: Use `many()` then left-fold to build left-associative chain.

```python
def _left_fold_app(atoms, loc):
    """Build left-associative application chain."""
    result = atoms[0]
    for arg in atoms[1:]:
        result = SurfaceApp(result, arg, loc)
    return result

@generate
def app_parser():
    loc = (yield peek_location()).location
    atoms = yield atom_parser.at_least(1)
    if len(atoms) == 1:
        return atoms[0]
    return _left_fold_app(atoms, loc)
```

### 4. Atoms

```
atom ::= ident
       | CON atom*
       | "(" term ")"
       | atom "@" type
       | atom "[" type "]"
       | atom ":" type
```

**Design**: Parse atom first, then post-fix operators in a loop.

```python
@generate
def atom_parser():
    atom = yield atom_base()
    
    # Post-fix operators: @T, [T], :T
    while True:
        type_app = yield (AT >> type_parser()).optional()
        if type_app:
            atom = SurfaceTypeApp(atom, type_app, atom.location)
            continue
            
        type_bracket = yield (LBRACKET >> type_parser() << RBRACKET).optional()
        if type_bracket:
            atom = SurfaceTypeApp(atom, type_bracket, atom.location)
            continue
            
        type_ann = yield (COLON >> type_parser()).optional()
        if type_ann:
            atom = SurfaceAnn(atom, type_ann, atom.location)
            continue
            
        break
    
    return atom

@generate
def atom_base():
    # Parenthesized term
    paren = yield (LPAREN >> term_parser() << RPAREN).optional()
    if paren:
        return paren
    
    # Variable
    ident = yield match_token("IDENT").optional()
    if ident:
        return SurfaceVar(ident.value, ident.location)
    
    # Constructor or constructor application
    con = yield match_token("CONSTRUCTOR").optional()
    if con:
        args = yield atom_base.many()
        return SurfaceConstructor(con.value, args, con.location)
    
    # Number literal
    num = yield match_token("NUMBER").optional()
    if num:
        return SurfaceConstructor(num.value, [], num.location)
```

### 5. Types

```
type ::= forall_type
forall_type ::= "forall" ident+ "." arrow_type
              | arrow_type
arrow_type ::= app_type ("->" arrow_type)?
app_type ::= atom_type+
atom_type ::= ident | CON | "(" type ")"
```

**Design**: Same pattern as terms - left-fold for application, right recursion for arrow.

```python
@generate
def forall_type():
    loc = (yield FORALL).location
    vars = yield IDENT.at_least(1)
    yield DOT
    body = yield forall_type | arrow_type  # Try forall first for nesting
    # Build nested forall from right to left
    for var in reversed(vars):
        body = SurfaceTypeForall(var, body, loc)
    return body

@generate
def arrow_type():
    arg = yield app_type()
    arrow = yield (ARROW >> arrow_type()).optional()
    if arrow:
        loc = arg.location
        return SurfaceTypeArrow(arg, arrow, loc)
    return arg

@generate
def app_type():
    loc = (yield peek_location()).location
    atoms = yield atom_type().at_least(1)
    if len(atoms) == 1:
        return atoms[0]
    return _left_fold_type_app(atoms, loc)

def _left_fold_type_app(atoms, loc):
    """Build left-associative type constructor application."""
    result = atoms[0]
    for arg in atoms[1:]:
        if isinstance(result, SurfaceTypeConstructor):
            result = SurfaceTypeConstructor(
                result.name, result.args + [arg], result.location
            )
        else:
            result = SurfaceTypeConstructor(str(result), [arg], loc)
    return result

@generate
def atom_type():
    # Parenthesized
    paren = yield (LPAREN >> type_parser() << RPAREN).optional()
    if paren:
        return paren
    
    # Type variable
    ident = yield match_token("IDENT").optional()
    if ident:
        return SurfaceTypeVar(ident.value, ident.location)
    
    # Type constructor
    con = yield match_token("CONSTRUCTOR").optional()
    if con:
        return SurfaceTypeConstructor(con.value, [], con.location)

type_parser = forall_type | arrow_type
```

### 6. Branches and Patterns

```
branch ::= pattern "->" term
pattern ::= CON ident*
```

```python
@generate
def branch():
    loc = (yield peek_location()).location
    pat = yield pattern()
    yield ARROW
    body = yield term_parser()
    return SurfaceBranch(pat, body, loc)

@generate
def pattern():
    loc = (yield peek_location()).location
    con = yield match_token("CONSTRUCTOR")
    vars = yield IDENT.many()
    return SurfacePattern(con.value, vars, loc)
```

## Helper Parsers

### sep_by1 and sep_by

```python
def sep_by1(parser, sep):
    """Parse one or more parser separated by sep."""
    @generate
    def sep_by1_parser():
        first = yield parser
        rest = yield (sep >> parser).many()
        return [first] + rest
    return sep_by1_parser

def sep_by(parser, sep):
    """Parse zero or more parser separated by sep."""
    return sep_by1(parser, sep).optional() or []
```

### peek_location

```python
@Parser
def peek_location(tokens, index):
    """Peek at next token without consuming, return its location."""
    if index < len(tokens):
        return Result.success(index, tokens[index])
    return Result.failure(index, "unexpected end of input")
```

## Error Handling Strategy

### Location Preservation

1. **From tokens**: Capture `token.location` at the start of each @generate parser
2. **In combinators**: Use `Parser.desc()` to add context to error messages
3. **Error types**: Wrap parsy.ParseError in custom ParseError with location

### Error Message Format

```python
class ParseError(Exception):
    def __init__(self, message: str, location: Location):
        super().__init__(f"{location}: {message}")
        self.location = location

def parse_tokens(tokens: list[Token]) -> list[SurfaceDeclaration]:
    try:
        return program.parse(tokens)
    except parsy.ParseError as e:
        # e.expected: what was expected
        # e.index: token index where failure occurred
        loc = tokens[e.index].location if e.index < len(tokens) else tokens[-1].location
        raise ParseError(f"expected {e.expected}", loc)
```

### Recovery Strategy

For declaration body parsing (where we need to stop at new declarations):

```python
@generate
def declaration_body():
    """Parse term, stopping when we see start of next declaration."""
    term = yield term_parser()
    
    # Peek ahead - if next tokens look like new declaration, stop
    # This is handled by the declaration parser, not here
    return term
```

## Forward Declaration Pattern

For mutually recursive rules (term → atom → term via parenthesized):

```python
# Forward declaration using @generate laziness
@generate
def term_parser():
    """Forward reference - actual definition below."""
    return (yield term_expr)

# Define actual parser
term_expr = lambda_expr | let_expr | case_expr | type_abs_expr | app_expr
```

Alternatively, use Python's late binding:

```python
# Define parsers, then combine
def make_parsers():
    @generate
    def atom_parser():
        # References term_parser which is defined later
        paren = yield (LPAREN >> term_parser << RPAREN).optional()
        ...
    
    @generate
    def term_parser():
        ...
    
    return term_parser, atom_parser

term_parser, atom_parser = make_parsers()
```

## Integration with Existing Code

### Parser Entry Point

```python
class ParsyParser:
    """Parsy-based parser for surface language."""
    
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
    
    def parse(self) -> list[SurfaceDeclaration]:
        """Parse token stream into declarations."""
        try:
            return program.parse(self.tokens)
        except parsy.ParseError as e:
            loc = self._get_error_location(e)
            raise ParseError(f"expected {e.expected}", loc)
    
    def _get_error_location(self, e: parsy.ParseError) -> Location:
        idx = min(e.index, len(self.tokens) - 1)
        return self.tokens[idx].location

# Convenience functions (same API as old parser)
def parse_expression(source: str, filename: str = "<stdin>") -> SurfaceTerm:
    tokens = Lexer(source, filename).tokenize()
    parser = ParsyParser(tokens)
    decls = parser.parse()
    if len(decls) != 1 or not isinstance(decls[0], SurfaceTermDeclaration):
        raise ParseError("Expected single term declaration", Location(1, 1, filename))
    return decls[0].body

def parse_program(source: str, filename: str = "<stdin>") -> list[SurfaceDeclaration]:
    tokens = Lexer(source, filename).tokenize()
    parser = ParsyParser(tokens)
    return parser.parse()
```

## Operator Precedence Summary

| Precedence | Operator | Associativity | Parser |
|------------|----------|---------------|--------|
| 1 (tightest) | Parentheses, atoms | - | `atom_base` |
| 2 | Type application (@T, [T]) | Left | Post-fix loop in `atom_parser` |
| 3 | Type annotation (:T) | Left | Post-fix loop in `atom_parser` |
| 4 | Function application | Left | `app_parser` with left-fold |
| 5 | Lambda, Let, Case, TypeAbs | Right | `term_parser` alternatives |
| 6 | Type arrows (->) | Right | `arrow_type` |
| 7 | Type forall | Right | `forall_type` |
| 8 (loosest) | Declaration | - | `declaration` |

## Implementation Checklist

### Phase 1: Token Primitives
- [ ] Create token matching functions (`match_token`, `match_value`)
- [ ] Define all token matchers (DATA, LET, etc.)
- [ ] Test token primitives

### Phase 2: Type Parsers
- [ ] Implement `atom_type`
- [ ] Implement `app_type` with left-fold
- [ ] Implement `arrow_type` with right recursion
- [ ] Implement `forall_type`
- [ ] Test all type parsers

### Phase 3: Term Parsers
- [ ] Implement `atom_base`
- [ ] Implement `atom_parser` with post-fix operators
- [ ] Implement `app_parser` with left-fold
- [ ] Implement `lambda_parser`, `let_parser`, `case_parser`, `type_abs_parser`
- [ ] Test all term parsers

### Phase 4: Declaration Parsers
- [ ] Implement `constructor`
- [ ] Implement `data_declaration`
- [ ] Implement `term_declaration`
- [ ] Implement `declaration_body`
- [ ] Test all declaration parsers

### Phase 5: Integration
- [ ] Create `ParsyParser` class
- [ ] Implement error handling
- [ ] Add convenience functions (`parse_expression`, `parse_program`)
- [ ] Port existing tests
- [ ] Run full test suite

## References

- Parsy documentation: https://parsy.readthedocs.io/
- @generate decorator: https://parsy.readthedocs.io/en/latest/ref/generating.html
- Token-based parsing: https://parsy.readthedocs.io/en/latest/howto/lexing.html
- Original parser: `src/systemf/surface/parser.py` (600 lines, recursive descent)
