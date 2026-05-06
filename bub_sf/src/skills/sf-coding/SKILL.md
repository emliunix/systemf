---
name: sf-coding
description: |
  SystemF coding assistance and typechecking. Use when:
  (1) Writing or editing SystemF (.sf) programs,
  (2) Typechecking SystemF modules with sf-check CLI,
  (3) Understanding SystemF syntax, types, or compilation errors,
  (4) Debugging type errors in SystemF code.
---

# sf-coding

SystemF language support for coding and typechecking.

## Quick Reference

### Typecheck a module

```bash
uv run bub sf-check -L <search-path> <module.name>
```

- `-L PATH`: Add search path (repeatable)
- Module path uses dot notation: `foo.bar` resolves to `foo/bar.sf`

### Example

```bash
uv run bub sf-check -L src/skills/sf-coding/references example
```

This loads `example.sf` as module `example` and typechecks it.

## SystemF Syntax

### Imports

```systemf
import builtins
import my.module
```

### Data types

```systemf
data Maybe a = Nothing | Just a
```

### Functions

```systemf
-- With type annotation and lambda
id :: forall a. a -> a = \x -> x

-- With pattern matching
fromMaybe :: forall a. a -> Maybe a -> a = \default ma ->
  case ma of
    Nothing -> default
    Just a -> a
```

### Primitive operations

```systemf
{-# LLM #-}
prim_op my_op :: String -> String
```

## Common Errors

**Cannot unify types**
- Type mismatch in expression
- Check that arguments match parameter types

**Module not found**
- Check search paths with `-L`
- Verify dot notation maps to correct file path

**Name not found**
- Missing import
- Typo in identifier

## References

- Example program: [references/example.sf](references/example.sf)
