# Fix Rename Constructor Call in test_rename_lhs.py

**Status**: TODO
**References**: Change #22 (literal pattern parser support), `rename.py` constructor signature change

---

## Facts

The `Rename` class constructor in `systemf/src/systemf/elab3/rename.py` was changed to accept a `name_gen: NameGenerator` as its 4th argument (previously it was created internally from `ctx.uniq`).

The test helper `mk_rename()` in `systemf/tests/test_elab3/test_rename_lhs.py` was not updated:

```python
# BEFORE (broken) — line 30-31
def mk_rename(mod_name: str = "builtins") -> Rename:
    return Rename(FakeCtx(), ReaderEnv.empty(), mod_name)
```

This causes all 11 tests in `test_rename_lhs.py` to fail with:
```
TypeError: Rename.__init__() missing 1 required positional argument: 'name_gen'
```

---

## Design

### Change

Update `mk_rename()` to create a `NameGeneratorImpl` and pass it as the 4th argument.

```python
# AFTER — line 30-31
from systemf.elab3.name_gen import NameGeneratorImpl

def mk_rename(mod_name: str = "builtins") -> Rename:
    ctx = FakeCtx()
    return Rename(ctx, ReaderEnv.empty(), mod_name, NameGeneratorImpl(mod_name, ctx.uniq))
```

### Why

- The constructor signature change decouples `Rename` from knowing how to create a `NameGenerator`, allowing the caller (e.g., `pipeline.py`) to control name generation strategy.
- Tests must match the new signature.

---

## Files

- `systemf/tests/test_elab3/test_rename_lhs.py` — Update `mk_rename()` helper

---

## Verification

```bash
uv run pytest tests/test_elab3/test_rename_lhs.py -q
```

Expected: 11 passed.
