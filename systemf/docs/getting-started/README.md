# System F Documentation

Welcome to the System F documentation. This is a polymorphic lambda calculus (System F) implementation with modern type inference, algebraic data types, and an interactive REPL.

## Quick Links

- [Getting Started](#getting-started) - Install and run your first program
- [Architecture](architecture.md) - System design and component overview
- [Syntax Reference](syntax.md) - Language syntax and examples
- [Elaborator Design](ELABORATOR_DESIGN.md) - Type inference pipeline details
- [REPL Guide](#repl) - Interactive usage

## Getting Started

### Installation

```bash
cd systemf
# Install dependencies
uv sync
```

### Running the REPL

```bash
uv run python -m systemf.eval.repl
```

### Example Session

```systemf
> 42
it :: __ = 42

> True
it :: __ = True

> not True
it :: __ = False

> id :: ∀a. a → a = λx → x
id :: ∀a. a → a = <function>

> id 42
it :: Int = 42
```

### Running a File

```bash
uv run python -m systemf.eval.repl myfile.sf
```

## Language Features

### Types

```systemf
-- Primitive types
Int, String, Bool

-- Type constructors
List Int, Maybe a, Either a b

-- Function types
Int → Int, ∀a. a → a

-- Wildcard types (inferred)
x :: _ = 42
```

### Data Types

```systemf
data Maybe a = Nothing | Just a

data List a = Nil | Cons a (List a)

data Either a b = Left a | Right b
```

### Functions

```systemf
-- Lambda expressions
id :: ∀a. a → a = λx → x

-- Pattern matching
map :: ∀a b. (a → b) → List a → List b
map = λf → λxs →
  case xs of
    Nil → Nil
    Cons x xs' → Cons (f x) (map f xs')
```

### Operators

```systemf
1 + 2      -- int_plus
5 - 3      -- int_minus
4 * 5      -- int_multiply
10 / 2     -- int_divide
x == y     -- int_eq
x < y      -- int_lt
```

### Cons Operator

System F uses `:` as the list cons operator:

```systemf
-- Lists can use cons operator
nums = 1 : 2 : 3 : Nil  -- equivalent to Cons 1 (Cons 2 (Cons 3 Nil))

-- Pattern matching with cons
head :: ∀a. List a → a
head = λxs →
  case xs of
    Cons x _ → x
```

## REPL Commands

- `:quit` or `:q` - Exit REPL
- `:help` or `:h` - Show help
- `:env` - Show current environment
- `:load <file>` - Load definitions from file
- `:{` and `:}` - Start/end multiline input

## Documentation Structure

- **[architecture.md](architecture.md)** - High-level architecture, component relationships
- **[syntax.md](syntax.md)** - Complete syntax specification
- **[ELABORATOR_DESIGN.md](ELABORATOR_DESIGN.md)** - Type inference implementation
- **[TYPE_INFERENCE_ALGORITHM.md](TYPE_INFERENCE_ALGORITHM.md)** - Algorithm details
- **[IMPLICIT_INSTANTIATION.md](IMPLICIT_INSTANTIATION.md)** - Implicit type instantiation
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common issues and solutions
- **[design/](design/)** - Design documents (parsers, etc.)

## Testing

```bash
# Run all tests
uv run pytest tests/

# Run specific test file
uv run pytest tests/test_surface/test_inference.py -v

# Run with coverage
uv run pytest tests/ --cov=systemf
```

## Development

### Key Directories

```
systemf/
├── src/systemf/
│   ├── core/          # Core AST and type system
│   ├── surface/       # Surface language (parser, elaborator)
│   │   ├── parser/    # Lexer and parser
│   │   ├── inference/ # Type elaborator
│   │   └── llm/       # LLM pragma processing
│   └── eval/          # Evaluator and REPL
├── tests/             # Test suite
└── docs/              # Documentation
```

### Recent Changes

See the journal entries in `/journal/` for development history and recent fixes.

## Troubleshooting

### Parser Errors

**Problem:** `expected 'expected valid declaration starting with IDENT'`

**Solution:** Use full declaration syntax with type annotation:
```systemf
-- Wrong
x = 42

-- Correct
x :: Int = 42
```

### Type Errors

**Problem:** `Undefined variable` for primitives

**Solution:** Load the prelude first or use fully qualified names:
```systemf
:load prelude.sf
```

### Pattern Matching Issues

**Problem:** `Case` pattern matching fails

**Solution:** Ensure patterns use correct field names (dataclass field ordering):
```python
# Use keyword arguments in pattern matching
case Constructor(name=name, args=args):
    pass
```

## Contributing

1. Follow the skill-first workflow (check `.agents/skills/`)
2. Write tests for new features
3. Update documentation for API changes
4. Run the full test suite before committing

## License

[Your License Here]
