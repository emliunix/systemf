# Change: Tape Primitives — `needs_compact`, `inferior_tape`, and sibling fixes

**Status:** Implemented on `feat-primitives` branch
**Commits:** `a92c888`, `d0ca698`, `5ccd22d`
**Status.md todos:** #27 (new primitives), #21 (test rot)
**Area:** `bub_sf/src/bub_sf/bub.sf`, `bub_sf/src/bub_sf/bub_ext.py`, `bub_sf/tests/test_bub_ext.py`, `test.sf`

## Problem

`main.sf`'s auto-compaction path (`with_compact`) calls two primitives that had no implementation, blocking the idle-compaction pipeline wired in change #57 / status #20:

- `needs_compact :: Tape -> Bool` — used in `main.sf`, **not declared or implemented anywhere**.
- `inferior_tape :: String -> Tape -> Tape` — declared in `bub.sf`, used in `main.sf`, but **no `_inferior_tape` impl and no `get_primop` case**.

While implementing these, the test suite revealed that **all** existing tape-primitive tests were broken (a fixture drift) and three sibling primitives had arg-extractor bugs that would also crash `main.sf` at runtime.

## Facts

- Tape primitives live in `BubOps` (`bub_sf/src/bub_sf/bub_ext.py`) and are dispatched by name in `BubOps.get_primop`.
- Each primitive returns either a plain `Val` (`_current_tape`) or `VAsync(_go)` for async ops; `_go` returns the result `Val`.
- Tape names are carried as `VPrim(str)`; `prim_val`/`str_val`/`maybe_val` extract them (`sf_helpers.py`).
- `TapeService.info(tape_name)` returns `TapeInfo` (`bub/src/bub/builtin/tape.py:111`) with `entries_since_last_anchor` and `anchors`.
  - A non-existent tape yields `entries=0, anchors=0` (the fork store resolves unknown tapes to `tape_id=-1`, silent empty — see `docs/tape.md`).
  - `TapeService.create()` adds a `session/start` bootstrap anchor and raises "Tape already exists" if one is present — so it is **not** idempotent.
- `Bool` is represented as `VData`: `bi.TRUE_VAL = VData(0, [])`, `bi.FALSE_VAL = VData(1, [])`.
- `Role` is `VData(0, [])` for `User`, `VData(1, [])` for `Assistant`; `_role_val` already maps these to `"user"`/`"assistant"`.
- `_get_agent(session)` reads `session.state["bub_state"]["_runtime_agent"]` — the test fixture had to match this nesting.
- The existing test fixture `MockSession.state = {"_runtime_agent": agent}` no longer matched `_get_agent`'s `state["bub_state"]` lookup → **all 14 tests were failing** before this change.
- Sequencing of effects in `bub.sf` uses lambda-application, not `;`: see `compact` (`(\_unit -> effect2) effect1`). The `;` form in `main.sf`'s `with_compact` is invalid (`sf-check` rejects it — see Notes).

## Design

### Part 1 — New primitives (commit `a92c888`)

Declarations added to `bub.sf`:

```systemf
-- | Check whether the tape has grown enough since the last anchor to warrant compaction.
prim_op needs_compact :: Tape -> Bool

-- | Get-or-create an inferior (named child) tape: name is {parent}/{tag}.
--   Idempotent — returns the existing tape if it already exists.
prim_op inferior_tape :: String -- ^ tag
  -> Tape -- ^ parent tape
  -> Tape
```

Implementations in `BubOps`:

```python
COMPACT_THRESHOLD_ENTRIES = 40  # module-level constant

def _needs_compact(self, args, session):
    agent = _get_agent(session)
    tape_name = prim_val(args[0])
    async def _go():
        info = await agent.tapes.info(tape_name)
        return bi.TRUE_VAL if info.entries_since_last_anchor > COMPACT_THRESHOLD_ENTRIES else bi.FALSE_VAL
    return VAsync(_go())

def _inferior_tape(self, args, session):
    agent = _get_agent(session)
    tag = str_val(args[0])
    parent_tape = prim_val(args[1])
    tape_name = f"{parent_tape}/{tag}"
    async def _go():
        # get-or-create: a non-existent tape has no bootstrap anchor
        info = await agent.tapes.info(tape_name)
        if info.anchors == 0:
            await agent.tapes.create(tape_name)
        return VPrim(tape_name)
    return VAsync(_go())
```

Dispatch added to `get_primop`:
```python
case "needs_compact":
    return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(self._needs_compact))
case "inferior_tape":
    return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(self._inferior_tape))
```

### Part 2 — Fix arg extractors in sibling primitives (commit `d0ca698`)

Three primitives used the wrong extractor for their declared argument type and would raise at runtime when `main.sf` reached them:

| Primitive | Location | Bug | Fix |
|---|---|---|---|
| `_tape_append` | `bub_ext.py` `_tape_append` | `prim_val(args[1])` on `Role` (a `VData`) | `_role_val(args[1])` |
| `_tape_make` | `bub_ext.py` `_tape_make` | `maybe_val(str_val, args[1])` on `name :: String` | `str_val(args[1])` |
| `_tape_handoff` | `bub_ext.py` `_tape_handoff` | `maybe_val(str_val, args[1])` on `name :: String` | `str_val(args[1])` |

Two stale test expectations updated to match the (intentional) uuid-suffix behavior of `_tape_fork` and `_tape_handoff`.

### Part 3 — Test fixture repair + `test.sf` guard (commits `a92c888`, `5ccd22d`)

- `MockSession.state` fixed to `{"bub_state": {"_runtime_agent": agent}}` so `_get_agent` resolves (unblocked all tests).
- Stale `_make_tape`/`_fork_tape` test references renamed to `_tape_make`/`_tape_fork`.
- `test.sf` added at repo root: typecheck-level programs using every primitive + the `with_compact`/`record_intent` compositions. Verified via `uv run bub sf-check test -L .` → `OK: test`.

## Why it works

- **`needs_compact` uses the right metric.** `entries_since_last_anchor` resets after each handoff anchor, so it exactly measures "growth since the last compaction" — the quantity a compaction threshold should bound.
- **`inferior_tape` is get-or-create.** `info().anchors == 0` distinguishes a non-existent/unbootstrapped tape from a live one (live tapes carry the `session/start` anchor), so it creates exactly once and is idempotent across turns — letting the intent-tracking tape accumulate records across the session.
- **`inferior_tape` is naming-only, not a fork.** A tracking tape should not inherit the full conversation; the `{parent}/{tag}` name just provides hierarchy. This matches `tape_make`'s empty-create semantics but with a deterministic (uuid-free) name.
- **Sibling fixes match declared types.** `String` args arrive as `VLit(LitString)` (use `str_val`); `Maybe String` arrive as `VData` (use `maybe_val`); `Role` arrives as `VData` (use `_role_val`). Each fix applies the extractor matching the declared SF type.
- **`test.sf` is a signature guard.** `sf-check` elaborates against the real `bub.sf`, so any incompatible primitive signature change fails it.

## Files

1. `bub_sf/src/bub_sf/bub.sf` — add `needs_compact` and `inferior_tape` declarations.
2. `bub_sf/src/bub_sf/bub_ext.py` — add `COMPACT_THRESHOLD_ENTRIES`, `_needs_compact`, `_inferior_tape`, dispatch cases; fix arg extractors in `_tape_make`, `_tape_append`, `_tape_handoff`.
3. `bub_sf/tests/test_bub_ext.py` — fix `MockSession` fixture; rename stale `_make_tape`/`_fork_tape`; add `TestNeedsCompact`, `TestInferiorTape`; align uuid-suffix expectations.
4. `test.sf` — new typecheck-level regression guard.
5. `status.md` — todos #21 (make_tape tests) and #27 (missing primitives) resolved.

## Test Coverage

`bub_sf/tests/test_bub_ext.py` — **11 passing**:
- `TestNeedsCompact`: returns `TRUE` above threshold, `FALSE` at/below.
- `TestInferiorTape`: creates when missing (anchors==0), idempotent when exists (anchors>0).
- `TestTapeAppend` / `TestTapeHandoff` / `TestMakeTape` / `TestForkTape`: repaired and green.

`test.sf` — `bub sf-check test -L .` → `OK: test`.

## Notes

- **Threshold is a constant, not config.** `COMPACT_THRESHOLD_ENTRIES = 40` is a module-level value. Change #57 envisioned `BUB_AUTO_COMPACT_THRESHOLD` env config; that plumbing is deferred — a constant is sufficient until config is wired.
- **`main.sf`'s `;` sequencing is invalid.** `sf-check` rejects `if … then … else () ; action` (`Unexpected character: ';'`). The working idiom (from `compact` in `bub.sf`) is `(\_unit -> effect2) effect1`. `main.sf` (systemf worktree) still has the broken `;` form and must be fixed when next touched. `test.sf` uses the lambda-application form. (See also `changes/60-seq-operator.md`.)
- **`compact` still targets `current_tape()`.** `with_compact` in `main.sf` checks `needs_compact` on the inferior tape but `compact Nothing` compacts `current_tape()`, not the passed tape — a pre-existing `main.sf` logic bug, out of scope here (this change only adds primitives; it does not fix `main.sf`).
- **`uv.lock` churn from `uv run --with` was left unstaged** in the `feat-primitives` worktree.

## Related

- `changes/54-tape-primitives-handoff-and-role.md` — prior tape-primitive change (`tape_handoff`, `Role`)
- `changes/57-idle-triggered-auto-compaction.md` — idle detection; compaction delegated to SF `main` (status #20)
- `changes/60-seq-operator.md` — the `;` operator this change sidesteps
- `docs/tape.md` — fork store query semantics (status #25)
- `status.md` — todos #21, #27
