# Change Plan: Remove `_E` and `_unwrap_e` from Fork Store

## Facts

- `bub_sf/src/bub_sf/store/fork_store.py` uses a custom exception wrapper pattern:
  - `_E` class (line 107): wraps `RepublicError` to carry it through async operations
  - `_unwrap_e` decorator (line 119): unwraps `_E` back to `RepublicError`
- `_E` is raised 10 times in `CoreOps` methods when errors occur
- `_unwrap_e` is applied to 7 `SQLiteForkTapeStore` methods:
  - `create`, `append`, `rename`, `reset`, `fork`, `fork_tape`, `fetch_all`
- The `_tranx` async context manager (line 494) properly handles exceptions:
  ```python
  except Exception as e:
      await self._conn.rollback()
      raise e from e
  ```
  Any exception raised inside `_tranx` is rolled back and re-raised as-is.
- `RepublicError` inherits from `Exception`, so it will be properly propagated by `_tranx`
- `_E` was likely introduced before `_tranx` was properly implemented, or to work around an older async context manager issue

## Design

Remove the `_E` / `_unwrap_e` indirection and raise `RepublicError` directly.

### Step 1: Remove `_E` class and `_unwrap_e` decorator

Delete lines 107-131 from `fork_store.py`:
```python
class _E(Exception):
    ...

def _unwrap_e(...):
    ...
```

### Step 2: Replace all `raise _E(RepublicError(...))` with `raise RepublicError(...)`

10 occurrences in `CoreOps`:
- Line 165: `raise _E(RepublicError(ErrorKind.UNKNOWN, "Failed to create tape"))`
- Line 194: `raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"Anchor name '{anchor_name}' already exists..."))`
- Line 228: `raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Tape '{old_name}' does not exist"))`
- Line 231: `raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"Tape '{new_name}' already exists"))`
- Line 246: `raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Source tape '{source_name}' does not exist"))`
- Line 251: `raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"Target tape '{target_name}' already exists"))`
- Line 254: `raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"entry_id {entry_id} is out of range..."))`

3 occurrences in `SQLiteForkTapeStore`:
- Line 395: `raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Tape '{tape}' does not exist"))`
- Line 416: `raise _E(RepublicError(ErrorKind.NOT_FOUND, f"Source tape '{source_name}' does not exist"))`
- Line 428: `raise _E(RepublicError(ErrorKind.INVALID_INPUT, f"Source tape '{source_name}' has no entries to fork from"))`

### Step 3: Remove all `@_unwrap_e` decorators

7 occurrences:
- `create` (line 368)
- `append` (line 375)
- `rename` (line 382)
- `reset` (line 390)
- `fork` (line 403)
- `fork_tape` (line 411)
- `fetch_all` (line 456)

Each method currently has this pattern:
```python
async def method(self, ...) -> T:
    @_unwrap_e
    async def _go():
        async with self._tranx() as _:
            await self._core.method(...)
    return await _go()
```

Simplify to:
```python
async def method(self, ...) -> T:
    async with self._tranx() as _:
        await self._core.method(...)
```

### Step 4: Clean up unused imports

Remove `functools` from imports if no longer used (check if used elsewhere).

## Why it works

- `_tranx` context manager already handles exception propagation correctly — it rolls back and re-raises the original exception
- `RepublicError` is a normal `Exception` subclass, so it propagates through `except Exception` blocks naturally
- Removing the wrapper reduces cognitive overhead and makes error handling explicit
- No behavior change — the same `RepublicError` exceptions are raised, just without the intermediate wrapper

## Files

1. `bub_sf/src/bub_sf/store/fork_store.py` — remove `_E` and `_unwrap_e`, simplify all store methods

## Test Coverage

- Existing tests in `bub_sf/tests/test_fork_store.py` should continue to pass
- Verify that error cases still raise the correct `RepublicError` with proper `ErrorKind`
- No new tests needed — this is a pure refactoring with no behavior change

## Related

- `changes/54-tape-primitives-handoff-and-role.md` — Depends on this refactoring (new `handoff` method should not use `_E` pattern)
