# System F Surface Syntax

This document describes the concrete syntax of the System F surface language.

## Let Expressions

### Single Binding

```systemf
let x = 1 in x
let x :: Int = 1 in x
```

**Syntax:**
- `let <ident> = <expr> in <expr>`
- `let <ident> :: <type> = <expr> in <expr>`

**Note:** Type annotations use `::` (double colon), not `:`.

### Multiple Bindings (Layout-Based)

```systemf
let
  x = 1
  y = 2
in x + y
```

**Note:** Multiple bindings use **layout** (indentation), not semicolons.

### Function Bindings

```systemf
let f x y = x + y in f 1 2
let f :: Int -> Int -> Int = \x y -> x + y in f 1 2
```

## Lambda Expressions

```systemf
\x -> x
\x :: Int -> x + 1
```

**Note:** Lambda parameter type annotations use `::` after the parameter name.

## Type Annotations

```systemf
x :: Int
1 :: Int
```

**Note:** All type annotations use `::` (double colon).

## Common Mistakes

### Wrong: Single colon for type annotation
```systemf
let x: Int = 1 in x  -- ERROR: use :: not :
```

### Wrong: Semicolon for multiple bindings
```systemf
let x = 1; y = 2 in x + y  -- ERROR: use layout instead
```

### Correct: Layout for multiple bindings
```systemf
let
  x = 1
  y = 2
in x + y
```
