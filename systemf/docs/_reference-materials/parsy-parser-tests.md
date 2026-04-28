# Parsy Parser Test Contracts

This document defines the test expectations for the parsy-based parser implementation.

## Existing Test Preservation

All existing tests in `tests/test_surface_parser.py` must continue to pass without modification.

### Test Categories to Preserve

1. **Declaration Parsing**
   - Data declarations: `data Maybe a = Nothing | Just a`
   - Term declarations: `id = \x -> x`
   - Term declarations with type annotations: `id : forall a. a -> a = \x -> x`

2. **Term Parsing**
   - Variables: `x`
   - Lambda abstractions: `\x -> x`, `\x:T -> x`
   - Applications: `f x y`
   - Let bindings: `let x = 1 in x`
   - Type abstractions: `/\a. x`
   - Type applications: `f @T`, `f [T]`
   - Type annotations: `x : T`
   - Case expressions: `case x of { True -> 1 | False -> 2 }`
   - Constructors: `Just x`, `Nothing`

3. **Type Parsing**
   - Type variables: `a`
   - Type constructors: `Int`, `Maybe a`
   - Arrow types: `a -> b`, `a -> b -> c`
   - Forall types: `forall a. a -> a`

4. **Complex Programs**
   - Map function with nested lambdas
   - Data type with multiple constructors
   - Mutually recursive declarations

## New Test Cases Required

### Token Primitives Tests

```python
def test_match_token():
    """Test basic token matching."""
    tokens = [Token("IDENT", "x", Location(1, 1)), Token("EOF", "", Location(1, 2))]
    assert match_token("IDENT").parse(tokens).value == "x"

def test_match_token_failure():
    """Test token mismatch raises ParseError."""
    tokens = [Token("NUMBER", "42", Location(1, 1))]
    with pytest.raises(ParseError):
        match_token("IDENT").parse(tokens)
```

### Parser Combinator Tests

```python
def test_sep_by():
    """Test separator combinator."""
    tokens = [
        Token("IDENT", "a", Location(1, 1)),
        Token("BAR", "|", Location(1, 3)),
        Token("IDENT", "b", Location(1, 5)),
    ]
    parser = sep_by(match_token("IDENT").map(lambda t: t.value), match_token("BAR"))
    assert parser.parse(tokens) == ["a", "b"]

def test_sep_by_empty():
    """Test separator with no elements."""
    tokens = [Token("EOF", "", Location(1, 1))]
    parser = sep_by(match_token("IDENT").map(lambda t: t.value), match_token("BAR"))
    assert parser.parse(tokens) == []
```

### Left-Associativity Tests

```python
def test_application_left_associative():
    """Verify f a b parses as (f a) b, not f (a b)."""
    source = "f a b"
    result = parse_expression(source)
    # Should be App(App(f, a), b)
    assert isinstance(result, SurfaceApp)
    assert isinstance(result.func, SurfaceApp)
    assert result.func.func.name == "f"
    assert result.func.arg.name == "a"
    assert result.arg.name == "b"

def test_type_arrow_right_associative():
    """Verify a -> b -> c parses as a -> (b -> c)."""
    source = "x : a -> b -> c"
    decl = parse_program(source)[0]
    # Type should be Arrow(a, Arrow(b, c))
    assert isinstance(decl.type_annotation, SurfaceTypeArrow)
    assert isinstance(decl.type_annotation.ret, SurfaceTypeArrow)
```

### Location Preservation Tests

```python
def test_lambda_location():
    """Verify lambda location is from backslash token."""
    source = "\\x -> x"
    result = parse_expression(source)
    assert result.location.line == 1
    assert result.location.column == 1

def test_parse_error_location():
    """Verify parse errors report correct location."""
    source = "\\x - y"  # Missing > in arrow
    try:
        parse_expression(source)
        assert False, "Should have raised ParseError"
    except ParseError as e:
        assert e.location.line == 1
        assert "expected" in str(e).lower()
```

### Edge Cases

```python
def test_empty_program():
    """Parse empty string returns empty declaration list."""
    assert parse_program("") == []

def test_nested_parentheses():
    """Parse deeply nested parentheses."""
    source = "(((x)))"
    result = parse_expression(source)
    assert isinstance(result, SurfaceVar)
    assert result.name == "x"

def test_operator_precedence():
    """Verify type application binds tighter than function application."""
    source = "f @a x"
    result = parse_expression(source)
    # Should be App(TypeApp(f, a), x)
    assert isinstance(result, SurfaceApp)
    assert isinstance(result.func, SurfaceTypeApp)

def test_forall_multiple_vars():
    """Parse forall with multiple type variables."""
    source = "forall a b. a -> b -> a"
    result = parse_program("id : " + source + " = \\x y -> x")[0]
    # Should be Forall(a, Forall(b, Arrow(a, Arrow(b, a))))
    t = result.type_annotation
    assert isinstance(t, SurfaceTypeForall)
    assert t.var == "a"
    assert isinstance(t.body, SurfaceTypeForall)
    assert t.body.var == "b"
```

### Error Message Tests

```python
def test_unexpected_token_error():
    """Error messages should be clear about what was expected."""
    source = "data 123"  # NUMBER where CONSTRUCTOR expected
    try:
        parse_program(source)
    except ParseError as e:
        assert "CONSTRUCTOR" in str(e) or "constructor" in str(e).lower()

def test_unexpected_end_of_input():
    """Error at EOF should be handled gracefully."""
    source = "\\x -"  # Incomplete arrow
    try:
        parse_expression(source)
    except ParseError as e:
        assert "EOF" in str(e) or "end" in str(e).lower()
```

## Test Organization Strategy

### Test File Structure

```
tests/
├── test_surface_parser.py          # Keep existing tests
├── test_surface_parser_new.py      # New parsy-specific tests
│   ├── test_token_primitives()
│   ├── test_parsers_type.py
│   ├── test_parsers_term.py
│   ├── test_parsers_declaration.py
│   └── test_integration.py
└── conftest.py                     # Shared fixtures
```

### Fixtures

```python
# conftest.py
import pytest

@pytest.fixture
def parse_expression():
    """Fixture providing parse_expression function."""
    from systemf.surface.parser import parse_expression
    return parse_expression

@pytest.fixture
def parse_program():
    """Fixture providing parse_program function."""
    from systemf.surface.parser import parse_program
    return parse_program

@pytest.fixture
def location():
    """Create a location for testing."""
    from systemf.utils.location import Location
    return Location
```

## Parity Checklist

Compare output of old parser vs new parser for:

- [ ] All terms produce identical AST structure
- [ ] All types produce identical AST structure
- [ ] All declarations produce identical AST structure
- [ ] Location information matches exactly
- [ ] Error messages have same or better quality
- [ ] Same programs parse successfully (no regression)
- [ ] Same programs fail to parse (no new successful parses of invalid programs)

## Performance Considerations

The new parser should have comparable performance:

- [ ] Parse small programs (<10 lines) in <10ms
- [ ] Parse medium programs (100 lines) in <100ms
- [ ] Parse large programs (1000 lines) in <1s

## Regression Tests

Ensure these specific programs from original parser tests work:

```python
# From test_surface_parser.py
TEST_PROGRAMS = [
    "x = 1",
    "id = \\\\x -> x",
    "const = \\\\x y -> x",
    "data Bool = True | False",
    "data Maybe a = Nothing | Just a",
    "map : forall a b. (a -> b) -> List a -> List b = \\\\f xs -> case xs of { Nil -> Nil | Cons x xs -> Cons (f x) (map f xs) }",
]
```

## Success Criteria

1. **100% of existing tests pass** without modification
2. **All new test cases pass**
3. **AST parity**: Output matches old parser for all valid inputs
4. **Error quality**: Error messages are clear and include location
5. **Performance**: Within 2x of old parser speed
6. **Code coverage**: >90% line coverage for parser module
