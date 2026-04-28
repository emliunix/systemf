---
title: "System F Documentation"
category: "meta"
status: "current"
last-updated: "2026-03-03"
description: "Main entry point for System F documentation"
---

# System F Documentation

Welcome to the System F documentation. This is a polymorphic lambda calculus (System F) implementation with modern type inference, algebraic data types, and an interactive REPL.

**📚 [View Complete Documentation Index](./INDEX.md)** - Full navigation and search

---

## Quick Start

### 🚀 [Getting Started](./getting-started/README.md)
- Installation instructions
- Running the REPL
- Your first program
- Examples

### 📖 [Syntax Reference](./reference/syntax.md)
- Complete language syntax
- Type system
- Pattern matching
- Operators

### 🔧 [Troubleshooting](./development/troubleshooting.md)
- Common errors and solutions
- Pattern matching issues
- Type inference problems
- Debugging tips

---

## Architecture

### 🏗️ [Architecture Overview](./architecture/overview.md)
- High-level system design
- Multi-pass pipeline
- Component relationships
- Interactive REPL

### 🔬 Deep Dives
- [Elaborator Design](./architecture/elaborator-design.md) - Type inference implementation
- [Type Inference Algorithm](./architecture/type-inference-algorithm.md) - Algorithm details
- [Implicit Instantiation](./architecture/implicit-instantiation.md) - Automatic polymorphism
- [Scoped AST Design](./architecture/scoped-ast-design.md) - AST structure

---

## Development

### 🔧 [Troubleshooting](./development/troubleshooting.md)
Common issues and solutions for development.

### 📋 [Design Decisions](./development/design-decisions.md)
Log of architectural decisions.

### 🐛 [Known Issues](./development/type-inference-bugs.md)
Current bugs and their status.

---

## Documentation Structure

```
docs/
├── INDEX.md                    [Complete navigation index]
├── README.md                   [This file - entry point]
├── getting-started/
│   └── README.md              [Installation and quickstart]
├── reference/
│   └── syntax.md              [Language reference]
├── architecture/
│   ├── overview.md            [System architecture]
│   ├── elaborator-design.md   [Type elaboration]
│   ├── type-inference-algorithm.md
│   ├── implicit-instantiation.md
│   └── ...
├── development/
│   ├── troubleshooting.md     [Issue resolution]
│   ├── design-decisions.md    [Decision log]
│   └── type-inference-bugs.md [Known issues]
├── _reference-materials/       [Design documents]
│   └── design/
└── _archive/                   [Old/deprecated docs]
```

---

## Quick Links by Task

| Task | Documentation |
|------|--------------|
| **Install and run** | [Getting Started](./getting-started/README.md) |
| **Learn syntax** | [Syntax Reference](./reference/syntax.md) |
| **Fix errors** | [Troubleshooting](./development/troubleshooting.md) |
| **Understand types** | [Architecture - Pipeline](./architecture/overview.md#multi-pass-pipeline) |
| **Add primitives** | [Architecture - Primitives](./architecture/overview.md#pluggable-primitives-system) |
| **Debug pattern matching** | [Troubleshooting](./development/troubleshooting.md#pattern-matching-issues) |

---

## Example Session

```systemf
$ uv run python -m systemf.eval.repl -p prelude.sf

System F REPL v0.1.0
Loading prelude... (59 definitions)

> 42
it : __ = 42

> True
it : __ = True

> not True
it : __ = False

> id : ∀a. a → a = Λa. λx:a. x
id : ∀a. a → a = <function>

> id [Int] 42
it : Int = 42
```

---

## Testing

```bash
# Run all tests
uv run pytest tests/

# Run specific modules
uv run pytest tests/test_surface/test_inference.py -v
uv run pytest tests/test_eval/test_evaluator.py -v

# Run with coverage
uv run pytest tests/ --cov=systemf --cov-report=html
```

---

## Contributing

1. Check [Documentation Index](./INDEX.md) for existing docs
2. Follow the [skill-first workflow](../.agents/skills/)
3. Write tests for new features
4. Update documentation for API changes
5. Run the full test suite before committing

See [Contributing Guide](../CONTRIBUTING.md) for detailed guidelines.

---

## License

MIT
