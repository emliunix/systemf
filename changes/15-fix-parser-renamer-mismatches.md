# Change Plan: Fix Parser/Renamer Type Mismatches

**Status**: Corrected - Implementing ValBind Structure  
**Priority**: High - Blocking 13 expression tests  
**Estimated Impact**: 10 source files, 50+ test sites

## Executive Summary

Two structural mismatches between the parser and renamer are blocking expression renaming tests:

1. **Literal Type Case Mismatch**: Parser produces `prim_type="Int"`/`"String"` (uppercase), renamer expects `"int"`/`"string"` (lowercase)
2. **Let Binding Structure Mismatch**: Parser returns `tuple[str, SurfaceType | None, SurfaceTerm]`, but the type system defines `list[ValBind]`

---

## Bug 1: Literal Type Case Sensitivity (FIXED)

### Current State (Fixed)

**Parser** (`expressions.py:215,222`):
```python
return SurfaceLit(prim_type="Int", value=int(num_token.value), location=num_token.location)
return SurfaceLit(prim_type="String", value=str_token.value, location=str_token.location)
```

**Renamer** (`rename.py:323-330`):
```python
def prim_to_lit(prim_type: str, value: object) -> Lit:
    match prim_type.lower():  # ✅ FIXED - normalizes to lowercase
        case "string":
            return LitString(cast(str, value))
        case "int":
            return LitInt(cast(int, value))
        case _:
            raise Exception(f"unknown literal type: {prim_type}")
```

**Why this approach**: Normalizing at the boundary (renamer) maintains robustness without changing the parser's clear uppercase convention used throughout test files.

---

## Bug 2: Let Binding Structure

### Decision Rationale: Use ValBind Structure

**Why ValBind, not tuples:**

1. **Intention-Revealing Name**: `ValBind` clearly signals "this is a value binding" rather than an anonymous 3-tuple
2. **Type Safety**: Attribute access (`binding.name`) is type-safe; tuple indexing (`binding[0]`) is fragile
3. **Consistency with Type System**: The type definitions already specify `list[ValBind]` - the code should honor this
4. **Self-Documenting**: `binding.type_ann` is clearer than `binding[1]`

**Acknowledging the Effort:**

This change requires updating **10 files** instead of 2:
- 1 parser file (to construct ValBind)
- 7 desugar/scoping/inference passes (to access attributes)
- 1 renamer file (to access attributes)
- 1 types file (already correct)

This is significant work, but **correct structure first, effort evaluation second**. The ValBind type was created for a reason - it provides semantic clarity and type safety that anonymous tuples cannot match.

### Current State (To Fix)

**Parser** (`expressions.py:1054,1107`):
```python
def let_binding(constraint: ValidIndent) -> P[tuple[str, SurfaceType | None, SurfaceTerm]]:
    # ... parser logic ...
    return (var_name, var_type, value)  # ❌ Returns tuple
```

**Type Definition** (`types.py:370,394`):
```python
@dataclass(frozen=True, kw_only=True)
class ValBinds(SurfaceTerm):
    bindings: list[ValBind]  # ✅ Correct type
    body: SurfaceTerm

@dataclass(frozen=True, kw_only=True)  
class ValBindsScoped(SurfaceTerm):
    bindings: list[ValBind]  # ✅ Correct type
    body: SurfaceTerm
```

**ValBind Definition** (`types.py:331-345`):
```python
@dataclass(frozen=True, kw_only=True)
class ValBind(SurfaceNode):
    name: str
    type_ann: SurfaceType | None
    value: SurfaceTerm
```

### Downstream Passes (All use tuple unpacking - must change to attribute access)

| File | Line | Current (tuple) | Change To (ValBind) |
|------|------|-----------------|---------------------|
| cons_pattern_pass.py | 108 | `for name, var_type, value in bindings:` | `for b in bindings: name=b.name, var_type=b.type_ann, value=b.value` |
| if_to_case_pass.py | 142 | `for name, var_type, value in bindings:` | Same pattern |
| multi_arg_lambda_pass.py | 60 | `[(name, var_type, desugar_fn(value)) for name, var_type, value in bindings]` | Same pattern |
| multi_var_type_abs_pass.py | 131 | `for name, var_type, value in bindings:` | Same pattern |
| operator_pass.py | 123 | `for name, var_type, value in bindings:` | Same pattern |
| scope_pass.py | 198 | `for var_name, var_type, value in bindings:` | Same pattern |
| checker.py | 170 | `for var_name, var_type, value in bindings:` | Same pattern |
| bidi_inference.py | 524, 892 | `for var_name, var_type_ann, value in bindings:` | Same pattern |

### Fix Strategy

**Step 1**: Update `let_binding` to return `ValBind`:
```python
def let_binding(constraint: ValidIndent) -> P[ValBind]:  # ✅ Return type
    # ... parser logic ...
    return ValBind(  # ✅ Construct proper object
        name=var_name,
        type_ann=var_type,
        value=value,
        location=loc  # Need to capture proper location
    )
```

**Step 2**: Update all 7 desugar/scoping/inference passes to access ValBind attributes instead of tuple unpacking:
```python
# Before:
for name, var_type, value in bindings:
    new_bindings.append((name, var_type, new_value))

# After:
for b in bindings:
    new_bindings.append(ValBind(
        name=b.name,
        type_ann=b.type_ann,
        value=new_value,
        location=b.location
    ))
```

**Step 3**: Update renamer's `binding_names` function (already expects ValBind):
```python
def binding_names(bindings: Iterable[ValBind]) -> list[tuple[str, SurfaceType | None, Location | None]]:
    return [(b.name, b.type_ann, b.location) for b in bindings]  # Already correct!
```

**Step 4**: Update renamer to access ValBind attributes in rename_expr:
```python
# Before:
case SurfaceLet(bindings=bindings, body=body):
    name_ty_locs = binding_names(bindings)  # Already returns tuples
    names = [self.new_name(n, loc) for (n, _, loc) in name_ty_locs]

# After (no change needed - binding_names handles ValBind -> tuple conversion):
case SurfaceLet(bindings=bindings, body=body):
    name_ty_locs = binding_names(bindings)
    names = [self.new_name(n, loc) for (n, _, loc) in name_ty_locs]
```

---

## Implementation Order

**Phase 1: Literal Type Fix** (COMPLETED)
1. ✅ Update `prim_to_lit` in `systemf/elab3/rename.py` to normalize case

**Phase 2: Parser Fix** (Next)
1. Update `let_binding` return type in `systemf/surface/parser/expressions.py`
2. Update `let_binding` to construct `ValBind` with proper location

**Phase 3: Downstream Passes** (After parser)
1. Update `cons_pattern_pass.py` to use ValBind attributes
2. Update `if_to_case_pass.py` to use ValBind attributes
3. Update `multi_arg_lambda_pass.py` to use ValBind attributes
4. Update `multi_var_type_abs_pass.py` to use ValBind attributes
5. Update `operator_pass.py` to use ValBind attributes
6. Update `scope_pass.py` to use ValBind attributes
7. Update `checker.py` to use ValBind attributes
8. Update `bidi_inference.py` to use ValBind attributes

**Phase 4: Test Verification**
1. Remove skips from `tests/test_elab3/test_rename_expr.py`
2. Run full test suite

---

## Files to Modify

### Source Files (10)
1. ✅ `systemf/elab3/rename.py` - `prim_to_lit` case normalization (DONE)
2. `systemf/surface/parser/expressions.py` - `let_binding` return ValBind
3. `systemf/surface/desugar/cons_pattern_pass.py` - Use ValBind attributes
4. `systemf/surface/desugar/if_to_case_pass.py` - Use ValBind attributes
5. `systemf/surface/desugar/multi_arg_lambda_pass.py` - Use ValBind attributes
6. `systemf/surface/desugar/multi_var_type_abs_pass.py` - Use ValBind attributes
7. `systemf/surface/desugar/operator_pass.py` - Use ValBind attributes
8. `systemf/surface/scoped/scope_pass.py` - Use ValBind attributes
9. `systemf/surface/scoped/checker.py` - Use ValBind attributes
10. `systemf/surface/inference/bidi_inference.py` - Use ValBind attributes

### Test Updates
1. `tests/test_elab3/test_rename_expr.py` - Remove skips for fixed bugs

---

## Why This Approach (Summary)

**Correct Structure Over Convenience:**

- `ValBind` is the semantically correct representation
- Named attributes are self-documenting (`b.type_ann` vs `b[1]`)
- Type-safe attribute access catches errors at compile time
- Aligns with existing type definitions
- Honest about the domain model

**Effort Acknowledgment:**

This requires touching 10 files instead of 2. Each downstream pass needs careful update to:
1. Iterate over bindings using `for b in bindings:`
2. Access attributes: `b.name`, `b.type_ann`, `b.value`, `b.location`
3. Construct new ValBind objects when transforming

The effort is justified because **code is read more than written**. The ValBind structure will make the codebase clearer and more maintainable for years to come.

---

## Rollback Plan

If issues arise:
1. Revert `prim_to_lit` change (1 line) - already done
2. Revert `let_binding` return statement (1 line)
3. Revert all downstream pass changes (mechanical)

No state or data migration needed - this is purely a code structure change.

---

## Verification

After implementation:
```bash
cd /home/liu/Documents/bub/systemf
uv run pytest tests/test_elab3/test_rename_expr.py -v
# Should show: 23 passed, 0 skipped

uv run pytest tests/test_surface/ -v
# All SurfaceLet tests should pass

uv run pytest tests/ -v
# Full test suite should pass
```

---

## Revision History

- **v1**: Incorrectly recommended changing type definition to tuples (backwards!)
- **v2**: Corrected to use ValBind structure throughout (this version)
  - Rationale: Type definitions exist for a reason; correct structure first
  - Acknowledged: 10 files vs 2 files, but worth it for semantic clarity
- **v3**: Rename ValBinds to SurfaceLet (this version)
  - Rationale: SurfaceLet is more accurate name for surface syntax construct
  - ValBindsScoped remains unchanged (to be deprecated with Scoped* types)
  - Purely internal rename - all code already uses SurfaceLet via import

---

## Revision 3: Rename ValBinds to SurfaceLet

**Rationale**: `SurfaceLet` is a more accurate name than `ValBinds`:
- It parallels `SurfaceIf`, `SurfaceCase`, `SurfaceAbs` - all surface syntax constructs
- `ValBinds` sounds like a plural container; `SurfaceLet` describes the syntactic construct
- All code already imports `SurfaceLet` (via alias), so this is purely internal cleanup
- `ValBindsScoped` will remain unchanged (to be deprecated with Scoped* types eventually)

**Scope of Change**:
- Rename class `ValBinds` to `SurfaceLet` in `types.py`
- Update docstrings referencing `ValBinds`
- Update backwards compatibility alias or remove it
- No other files change (they all use `SurfaceLet` via import)

**Files Modified**:
- `systemf/src/systemf/surface/types.py` - class rename only

**Impact**: Minimal - purely cosmetic rename, all code uses `SurfaceLet` already
