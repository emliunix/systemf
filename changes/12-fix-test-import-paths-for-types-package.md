# Fix test imports to align with types/ package reorganization

## Facts

### What moved
- `systemf/src/systemf/elab3/ty.py` → `systemf/src/systemf/elab3/types/ty.py`
- `systemf/src/systemf/elab3/ast.py` → `systemf/src/systemf/elab3/types/ast.py`
- `systemf/src/systemf/elab3/core.py` → `systemf/src/systemf/elab3/types/core.py`
- `systemf/src/systemf/elab3/mod.py` → `systemf/src/systemf/elab3/types/mod.py`
- `systemf/src/systemf/elab3/tything.py` → `systemf/src/systemf/elab3/types/tything.py`
- `systemf/src/systemf/elab3/types.py` deleted (replaced by types/ package)
- `NameCache` moved to `systemf/src/systemf/elab3/name_cache.py`

### types/__init__.py exports (only)
`REPLContext`, `Name`, `Ty`, `Module`, `TyThing`

### Constructor changes (from review)
1. `Name(mod, surface, unique, loc=None)` — tests used old positional order
2. `BoundTv(name=Name)` — tests used `BoundTv(name="a")` (string)
3. `AnId(name, type)` — tests used `AnId(name, term, ty)` (had `term` field)
4. Core types now use `Id` not bare strings: `CoreVar(id=Id)`, `NonRec(binder=Id, expr)`

## Design

### test_types.py
- Fix `BoundTv` import: `systemf.elab2.types` → `systemf.elab3.types.ty`
- Fix `Name` constructor to use keyword args
- Fix `AnId` — no `term` field, remove CoreLit usage
- Fix `ATyCon` — still `(name, tyvars, constructors)` OK
- Fix `ACon` — still `(name, tag, arity, field_types, parent)` OK
- Fix Core tests: `CoreVar`/`CoreLit`/`NonRec`/`Rec`/`CoreLet` need `Id` objects
- Imports from `systemf.elab3.types.ty`, `systemf.elab3.types.tything`, `systemf.elab3.types.core`

### test_zonk_and_cache.py
- Fix type imports to `systemf.elab3.types.ty`
- Fix `BoundTv(name="a")` → `BoundTv(name=Name(mod="<local>", surface="a", unique=-1))`
- Fix `NameCache` import to `systemf.elab3.name_cache`
- Line 86 `from systemf.elab3.types import Name` → `from systemf.elab3.types.ty import Name`

### test_rename_expr.py
- Fix `systemf.elab3.ast` → `systemf.elab3.types.ast`
- Fix `systemf.elab3.types import Name, TyInt, ...` → `systemf.elab3.types.ty import Name, TyInt, ...`

### test_rename_expr_types.py
- Fix `systemf.elab3.ast` → `systemf.elab3.types.ast`
- Fix `systemf.elab3.types import Name, BoundTv, ...` → `systemf.elab3.types.ty import Name, BoundTv, ...`

## Files
- **Modify**: `systemf/tests/test_elab3/test_types.py`
- **Modify**: `systemf/tests/test_elab3/test_zonk_and_cache.py`
- **Modify**: `systemf/tests/test_elab3/test_rename_expr.py`
- **Modify**: `systemf/tests/test_elab3/test_rename_expr_types.py`

## Verification

```bash
~/.local/bin/uv run pytest systemf/tests/test_elab3/ -v
```
