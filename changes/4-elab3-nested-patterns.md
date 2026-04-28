# Change Plan: Add Nested Pattern Support to elab3 AST

**Previous plan:** `changes/3-collect-pattern-vars-shallow.md`

## Why a new plan

The surface AST now supports nested constructor patterns (`SurfacePattern.vars: list[SurfacePattern]`). The elab3 AST currently has a flat `ConPat.vars: list[Id]`, which cannot represent patterns like `Cons (Pair a b) zs`. This plan makes the elab3 pattern hierarchy recursive to match.

## Facts

- `elab3/ast.py` defines `Pat`, `ConPat`, `LitPat`, and `DefaultPat`.
- `ConPat.vars` is `list[Id]` — a flat list of bound identifiers with no room for nesting.
- There are **zero usages** of `ConPat` in the current `elab3/` source or tests, so the change is non-breaking.
- The surface-to-elab3 conversion pipeline is not yet fully wired, so now is the right time to fix the AST shape.

## Design

### Add `VarPat`

Introduce a variable-pattern node that binds an `Id`:

```python
@dataclass(frozen=True)
class VarPat(Pat):
    """Variable pattern that binds an identifier: x."""
    id: Id
```

### Make `ConPat` recursive

Change `ConPat.vars: list[Id]` to `ConPat.args: list[Pat]`:

```python
@dataclass(frozen=True)
class ConPat(Pat):
    """Constructor pattern: Con arg1 arg2 ..."""
    con: Name
    args: list[Pat] = field(default_factory=list)
```

**Why rename `vars` to `args`:**
- In a recursive pattern AST, children are not always variables — they can be nested `ConPat`, `LitPat`, etc.
- `args` is the standard term (GHC uses `ConPat { pat_args :: [Pat] }`).
- This avoids the naming confusion we already hit in `SurfacePattern`.

### Keep `LitPat` and `DefaultPat`

These already fit naturally into the recursive hierarchy.

## Why It Works

- `VarPat` gives us a leaf node to put inside `ConPat.args`.
- `ConPat.args: list[Pat]` allows arbitrary nesting: `Cons (Pair (VarPat a) (VarPat b)) (VarPat zs)`.
- No existing code references `ConPat.vars`, so there's no downstream breakage.

## Files

- `systemf/src/systemf/elab3/ast.py` — add `VarPat`, change `ConPat.vars` to `ConPat.args`
