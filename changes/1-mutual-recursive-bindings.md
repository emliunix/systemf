# Change Plan: Mutual Recursive Bindings Support

## Facts

### Current State
- `bindings()` in `typecheck_expr.py:300` already has SCC analysis infrastructure (`scc.py`)
- The function splits bindings into recursive/non-recursive groups and processes them
- `let()` at line 134 builds `CoreLet(NonRec)` for all bindings, even recursive ones
- `tc_valbinds()` in `typecheck.py:73` uses `bindings()` for module-level declarations

### How bindings() Works
1. Returns `R` via callback `cb: Callable[[list[tuple[Id, TyCkRes]]], R]`
2. Each group adds env entries, then calls callback with accumulated `(Id, lambda: C.var(id))` pairs
3. The actual Core term building happens in the caller (`let()` or `tc_valbinds`)

### Current Recursive Group Issues
1. `_core` functions are defined but never passed to callbacks
2. For annotated bindings, `mono_id_annotated` is created but not unified with `mono_id`
3. Multiple binding case returns placeholder `C.var(mono_ids[0])`
4. No impedance matching when poly types differ from inferred types

## Design

### Goal
Fix `bindings()` to properly handle recursive groups by:
1. Returning proper `TyCkRes` thunks that build `CoreLet(Rec)` terms
2. Unifying annotated types with mono types in recursive groups
3. Supporting impedance matching for polymorphic recursive bindings

### Changes

#### 1. Change `bindings()` return type
Instead of returning `list[tuple[Id, TyCkRes]]`, return `list[tuple[Id, Ty]]` + a builder function. But this would break `let()` and `tc_valbinds()`.

**Better approach**: Keep the same interface but make the `TyCkRes` thunks build proper Core terms.

#### 2. Fix `_process_recursive_group`
- For annotated bindings: unify `mono_id.ty` with annotated type before checking RHS
- Build proper `TyCkRes` that returns `CoreLet(Rec(...), C.var(poly_id))` wrapped in `CoreTyLam` when polymorphic
- Return the actual Core terms through the callback chain

#### 3. Update `let()` to handle recursive groups
- Currently builds nested `NonRec` lets
- Need to detect recursive groups and build `Rec` instead
- Or: change `bindings()` to return group information

**Decision**: Change `bindings()` to return `list[tuple[Id, TyCkRes, bool]]` where `bool` indicates if recursive. But this breaks existing callers.

**Better decision**: Keep interface, but have `TyCkRes` build the proper term. For `let()`, we need to know which bindings are recursive to build `Rec` vs `NonRec`.

**Final design**: 
- `bindings()` returns `list[tuple[Id, TyCkRes, bool]]` where bool = is_recursive
- Update `let()` to group consecutive recursive bindings into `Rec`
- Update `tc_valbinds()` to handle the new format

### Implementation Steps

1. **Modify `bindings()` return type** to `list[tuple[Id, TyCkRes, bool]]`
2. **Fix `_process_recursive_group`** to:
   - Unify annotated types with mono types
   - Build proper `TyCkRes` thunks
   - Handle impedance matching
3. **Update `let()`** to build `CoreLet(Rec)` for recursive groups
4. **Update `tc_valbinds()`** to handle new return format
5. **Add tests** for recursive and mutually recursive bindings

## Files to Change

1. `systemf/src/systemf/elab3/typecheck_expr.py` - Fix `bindings()`, `_process_recursive_group()`, `let()`
2. `systemf/src/systemf/elab3/typecheck.py` - Update `tc_valbinds()`
3. `systemf/tests/test_elab3/test_bindings.py` - New test file

## Why It Works

- SCC analysis already correctly identifies recursive groups
- Two-phase typechecking (mono IDs → check RHSs → generalize) is sound
- `CoreLet(Rec)` properly supports mutual recursion in Core
- Impedance matching via wrappers handles poly/mono type differences

## Testing Strategy

1. Self-recursive binding (factorial)
2. Mutual recursive bindings (even/odd)
3. Mixed recursive and non-recursive
4. Polymorphic recursive binding
5. Annotated recursive binding
