# System F Troubleshooting Guide

Common issues and their solutions.

## Parser Errors

### Error: "expected 'expected valid declaration starting with IDENT'"

**Cause:** The parser expects declarations with explicit type annotations, not bare assignments.

**Solution:** Add a type annotation or use wildcard `_`:

```systemf
-- Wrong
x = 42

-- Correct
x : Int = 42

-- Also correct (type inferred)
x : _ = 42
```

### Error: "expected one of ... at position"

**Cause:** Syntax error in expression or declaration.

**Solution:** Check for common mistakes:
- Missing type annotations on declarations
- Wrong arrow syntax (`->` vs `→`, use `→`)
- Missing parentheses around complex expressions
- Invalid characters in identifiers

## Type Errors

### Error: "Undefined variable: 'int_plus'"

**Cause:** Primitive operations aren't loaded. The prelude defines primitive signatures.

**Solution:** Load the prelude:

```bash
# Start REPL with prelude
uv run python -m systemf.eval.repl -p prelude.sf

# Or load interactively
> :load prelude.sf
```

### Error: "Type mismatch: expected 'Int', but got 'Int _x'"

**Cause:** Type variable scoping issue. The underscore in `Int _x` indicates an unsolved meta-variable.

**Solution:** 
- Use explicit type applications: `id [Int] 42`
- Add type annotations to help inference
- Check that type parameters are properly bound

### Error: "Undefined variable: 'x'"

**Cause:** Variable not in scope.

**Solution:**
- Check variable name spelling
- Load the file containing the definition
- Ensure the definition comes before usage in declarations

## Pattern Matching Issues

### Error: "Case" branch mismatch or unexpected behavior

**Cause:** Dataclass field ordering in pattern matching.

**Solution:** Use keyword arguments in pattern matching:

```python
# In evaluator or type checker

# Correct ✓
match term:
    case Abs(var_type=var_type, body=body):
        return VClosure(env, body)
    case App(func=func, arg=arg):
        ...

# Incorrect ✗ (breaks due to source_loc inheritance)
match term:
    case Abs(var_type, body):  # source_loc becomes var_type!
        ...
```

**Root Cause:** Python dataclasses put inherited fields first. `Term` has `source_loc`, so subclasses have field order: `[source_loc, ...own_fields...]`.

## Evaluation Errors

### Error: "Cannot apply non-function"

**Cause:** Attempting to apply a value that isn't a function.

**Solution:** Check that:
- The function expression evaluates to a closure or primitive
- Type application syntax is correct: `f [Int]` not `f Int`

### Error: "Division by zero"

**Cause:** Integer division by zero.

**Solution:** Add guards or checks before division:

```systemf
divide : Int → Int → Maybe Int
divide = λn. λm.
  case m == 0 of
    True → Nothing
    False → Just (int_divide n m)
```

### Error: "Unknown primitive: $prim.xxx"

**Cause:** Mismatch between PrimOp naming and evaluator lookup.

**Solution:** Ensure primitives are named correctly:
- AST stores: `PrimOp(name="int_plus")` (no `$prim.` prefix)
- Evaluator looks up: `$prim.int_plus` (adds prefix)

## REPL Issues

### Issue: REPL shows no output after expression

**Cause:** Empty input or parsing failed.

**Solution:** 
- Check for syntax errors in previous commands
- Try `:env` to see what's defined
- Use `:quit` and restart

### Issue: Multiline input doesn't work

**Cause:** Incorrect multiline syntax.

**Solution:**

```systemf
> :{
| map : ∀a b. (a → b) → List a → List b
| map = Λa. Λb. λf. λxs.
|   case xs of
|     Nil → Nil
|     Cons x xs' → Cons (f x) (map [a] [b] f xs')
| :}
```

Note: `:{` starts multiline, `:}` ends it.

## Test Failures

### Issue: Tests fail with "assert VInt(value=...) == VInt(value=...)"

**Cause:** Dataclass field ordering in pattern matching or construction.

**Solution:** Update tests to use keyword arguments:

```python
# Old (broken)
lam = Abs(TypeConstructor("Int", []), Var(0))

# New (fixed)
lam = Abs(var_type=TypeConstructor("Int", []), body=Var(index=0))
```

### Issue: Tests fail with type mismatches

**Cause:** Primitive naming convention changed.

**Solution:** Update test assertions to use new names (without `$prim.` prefix):

```python
# Old
assert desugared.func.func.name == "$prim.int_plus"

# New
assert desugared.func.func.name == "int_plus"
```

## Development Issues

### Issue: Import errors when running tests

**Cause:** Module path issues or missing dependencies.

**Solution:**

```bash
# Make sure you're in the right directory
cd systemf

# Install dependencies
uv sync

# Run with proper Python path
uv run pytest tests/
```

### Issue: LSP errors about type mismatches

**Cause:** Complex type system with dataclass inheritance.

**Solution:** These are often false positives from static analysis. Run the tests to verify correctness.

## Common Gotchas

### 1. Wildcard Types

Wildcard `_` works for type inference:
```systemf
x : _ = 42  -- Inferred as Int
```

But not in all positions. Use explicit types for polymorphic functions.

### 2. Type Applications

Must use brackets for type application:
```systemf
id [Int] 42  -- Correct
id Int 42    -- Wrong (parses as two arguments)
```

### 3. Constructor Patterns

Pattern matching requires parentheses for constructor args:
```systemf
case xs of
  Cons x xs' → ...    -- Correct
  Cons (x xs') → ...  -- Wrong
```

### 4. Unicode vs ASCII

Both work, but Unicode is preferred:
```systemf
λx. x    -- Lambda (Unicode)
\x. x    -- Lambda (ASCII)

→        -- Arrow (Unicode)
->       -- Arrow (ASCII)
```

### 5. Forward References

The REPL accumulates definitions, but each file load is independent. Reload the prelude if needed.

## Debugging Tips

### Enable Debug Output

Add print statements in the pipeline:

```python
# In elaborator
print(f"Inferring: {term}")
print(f"Context: {ctx}")
```

### Check Intermediate AST

```python
from systemf.surface.parser import Lexer, Parser
from systemf.surface.pipeline import ElaborationPipeline

tokens = Lexer("1 + 2").tokenize()
term = Parser(tokens).parse_expression()
print(f"Surface term: {term}")
```

### Verify Type Inference

```python
pipeline = ElaborationPipeline()
result = pipeline.run(declarations, constructors={})
if result.success:
    print(f"Types: {result.module.global_types}")
else:
    print(f"Errors: {result.errors}")
```

## Getting Help

1. Check the [Syntax Reference](syntax.md) for correct syntax
2. Review [Architecture](architecture.md) for design details
3. Look at test files for working examples
4. Check the journal in `/journal/` for recent changes
5. Run with `uv run python -m systemf.eval.repl` for interactive testing
