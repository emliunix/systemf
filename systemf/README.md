# SystemF

A polymorphic lambda calculus with algebraic data types, bidirectional type inference, and an interactive REPL.

## Features

- **Algebraic Data Types**: Sum types with pattern matching (`List a`, `Maybe a`, `Either a b`)
- **Bidirectional Type Inference**: Pierce & Turner style with implicit instantiation
- **Interactive REPL**: Type-check and evaluate expressions interactively
- **Primitive Operations**: Integer arithmetic, string operations, and boolean logic
- **Unicode Syntax**: Support for λ, →, ∀ characters
- **Module System**: Imports, exports, and separate compilation
- **Pluggable Primitives**: Extend the language with custom operations via the extension system

## Quick Start

```bash
# Run the REPL
uv run python -m systemf.elab3.repl_main

# Run the demo
uv run python -m systemf.elab3_demo

# Run tests
uv run pytest
```

## Example Session

```systemf
elab3 repl  (:browse <mod>  :info <name>  :import <mod>  :{ .. :}  :help  :quit)

>> 42
42 :: Int

>> True
True :: Bool

>> 1 + 2
3 :: Int

>> id :: forall a. a -> a = \x -> x
id :: forall a. a -> a

>>:{
mymap :: forall a b. (a -> b) -> List a -> List b = \f xs ->
  case xs of
    Nil -> Nil
    Cons x xs' -> Cons (f x) (mymap f xs')
:}
mymap :: forall a b. (a -> b) -> List a -> List b
```

## Project Structure

```
systemf/
├── src/systemf/
│   ├── elab3/              # Elaborator: Parse → Rename → Typecheck → Eval
│   │   ├── pipeline.py     # Compilation pipeline
│   │   ├── rename*.py      # Name resolution
│   │   ├── typecheck*.py   # Bidirectional inference
│   │   ├── eval.py         # Expression evaluator
│   │   ├── matchc.py       # Pattern compilation
│   │   ├── repl*.py        # REPL implementation
│   │   ├── types/          # Core AST, types, values
│   │   ├── builtins.py     # Built-in names
│   │   └── builtins_rts.py # Built-in runtime
│   ├── surface/            # Surface language parser
│   │   └── parser/         # Lexer and parser
│   ├── builtins.sf         # Standard library
│   └── demo.sf             # Demo module
├── tests/
│   ├── test_elab3/         # Elab3 tests (366)
│   └── test_surface/       # Surface parser tests (304)
└── docs/                   # Documentation
```

Pipeline: Parse → Rename → Typecheck → Evaluate

## Extension

Custom primitives can be added by implementing the extension protocol. See `bub_sf/src/bub_sf/` for an example integration with the [bub](https://github.com/bubbuild/bub) agent framework, which adds LLM-powered primitives to the language.

## License

Apache-2.0. See [LICENSE](../LICENSE) for details.
