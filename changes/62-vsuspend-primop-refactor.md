# 62 — Simplify prim ops with `VSuspend`

Tracks: `systemf/ELAB3_PROJECT_STATUS.md` Next Steps #13 (`#refactoring`).

## Goal

Replace the `VPartial` + `SessionAwareFinish` pair with a single value
constructor `VSuspend` that suspends evaluation while a primitive/constructor
is awaiting more arguments. Every primitive (builtin primop, data constructor,
session/async primop) is built the same way through **one uniform finish
signature**, removing the dual-callback dispatch in the evaluator.

## Facts (current behavior)

### The two types being unified

`systemf/src/systemf/elab3/types/vpartial.py`:

- `VPartial(name: str, arity: int, done: list[Val], finish: Callable[[list[Val]], Val] | SessionAwareFinish)`.
  - `VPartial.create(name, arity, finish)`: if `arity == 0`, calls `finish([])` immediately; else returns `VPartial(name, arity, [], finish)`.
- `SessionAwareFinish`: wraps `func(vals, session) -> Val`; `__call__(vals, *, session=None)`. `from_async(func)` returns `SessionAwareFinish(lambda vals, session: VAsync(func(vals, session)))`.
- The `finish` field is therefore a **union** of two shapes, and the module carries a `TODO` about `create` / `None`.

### Evaluator dispatch

`systemf/src/systemf/elab3/eval.py`:

- `Ar` continuation (`call_continue`, ~line 236): accepts `VClosure() | VPartial()` in function position.
- `Ap` continuation (~line 246-257): for `VPartial(name, arity, done, finish)`:
  ```python
  new_done = done + [v]
  if arity == len(new_done):
      if isinstance(finish, SessionAwareFinish):
          res = finish(new_done, session=self.ctx.get_session())
      else:
          res = finish(new_done)
      return await self.call_continue(await unasync(res), k2)
  else:
      return await self.call_continue(VPartial(name, arity, new_done, finish), k2)
  ```
- `EvalCtx` protocol (line ~100) declares `get_session() -> REPLSessionProto | None`.
- `VAsync` + `unasync` (line 294) unwrap async primitive results. The comment states "VPartial apply is the only place where VAsync can appear".

### All construction sites (call sites to migrate)

1. `systemf/src/systemf/elab3/repl.py:137` — `_builtins_primops._reg`: `builtins[surface] = VPartial.create(surface, arity, func)` where `func` is a **pure** `list[Val] -> Val` from `builtins_rts.py` (int_plus, string_concat, error, mk_ref, …).
2. `systemf/src/systemf/elab3/repl_session.py:120` — `add_return`: `VPartial.create(fun_name.surface, 1, _fun)`, `_fun` is pure `list[Val] -> Val`.
3. `systemf/src/systemf/elab3/repl_session.py:291` — `mk_mod_inst` for `ACon`: `VPartial.create(con_name.surface, arity, _mk_data(tag))`; `_mk_data` returns pure `list[Val] -> Val` producing `VData(tag, args)`.
4. `bub_sf/src/bub_sf/bub_ext.py:146-158` — `TapeOps.get_primop`: `VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(self._method))`. The 6 methods have signature `(args: list[Val], session) -> Val` and each returns `VAsync(_go())` (sync fn returning VAsync).
5. `bub_sf/src/bub_sf/bub_ext.py:237` — `LLMOps`: `VPartial.create(name.surface, match_res.orig_arg_num, SessionAwareFinish.from_async(_fun))`; `_fun` is `async (vals, session) -> Val`.

### Importers of `types.vpartial`

- `eval.py`: `from .types.vpartial import SessionAwareFinish, VPartial`
- `repl.py:27`: `from .types.vpartial import VPartial`
- `repl_session.py:24`: `from .types.vpartial import VPartial`
- `val_pp.py:5`: `from .types.vpartial import VPartial` (renders `<func {name} {arity}>` at line 21)
- `bub_sf/src/bub_sf/bub_ext.py:26`: `from systemf.elab3.types.vpartial import VPartial, SessionAwareFinish`
- `systemf/tests/test_elab3/test_eval.py:56`: `from systemf.elab3.types.vpartial import VPartial`
- `types/__init__.py` does **not** export `VPartial` (no change needed there).

### Test facts

- `systemf/tests/test_elab3/test_eval.py`:
  - line 409-412: `Cons 1` → asserts `isinstance(p1, VPartial)`, `p1.done == [VLit(LitInt(1))]`.
  - line 647-654 `test_primops_are_vpartial`: asserts `int_plus` resolves to `VPartial` with `name == "int_plus"`, `arity == 2`, `done == []`.
  - `FakeCtx` (line 150) implements `EvalCtx` but **does not define `get_session`**. It currently works because pure finishes take the non-session branch. After this change every finish is called with `self.ctx.get_session()`, so `FakeCtx` must gain `get_session`.
- `bub_sf/tests/test_bub_ext.py`: calls the `TapeOps`/`LLMOps` methods directly and asserts `isinstance(result, VAsync)` (9 sites). These call the underlying methods, **not** `VPartial`/`SessionAwareFinish`, so they remain valid as long as the methods still return `VAsync`. (test_bub_ext.py also imports names from `bub_ext`; confirm it does not import `VPartial`/`SessionAwareFinish` — it does not.)

## Design

### New module `systemf/src/systemf/elab3/types/suspend.py`

```python
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field

from .protocols import REPLSessionProto
from .val import Val, VAsync

# Uniform primitive finish signature: receives all collected args + the
# current session (None outside a REPL session), returns the result Val.
# May return a VAsync for asynchronous primitives.
type PrimFinish = Callable[[list[Val], REPLSessionProto | None], Val]


@dataclass
class VSuspend(Val):
    """A suspended primitive or data-constructor application.

    Evaluation *suspends* (stays a VSuspend) until ``arity`` arguments have
    been collected, then runs ``finish(args, session)``.
    """
    name: str
    arity: int
    done: list[Val]
    finish: PrimFinish

    @staticmethod
    def create(name: str, arity: int, finish: PrimFinish) -> Val:
        if arity == 0:
            return finish([], None)
        return VSuspend(name, arity, [], finish)


def finish_async(
    func: Callable[[list[Val], REPLSessionProto | None], Coroutine[None, None, Val]],
) -> PrimFinish:
    """Adapt an async finish into the uniform (sync-returning) PrimFinish by
    deferring it as a VAsync (unwrapped by the evaluator)."""
    return lambda args, session: VAsync(func(args, session))
```

`finish_async` replaces `SessionAwareFinish.from_async` (one call site). It is a
plain function, not a class — no `__call__`/union type.

Delete `systemf/src/systemf/elab3/types/vpartial.py`.

### Evaluator (`eval.py`)

- Import: `from .types.suspend import VSuspend` (drop `SessionAwareFinish, VPartial`).
- `Ar` case: `case VClosure() | VSuspend():` (replace `VPartial`).
- `Ap` case:
  ```python
  case VSuspend(name=name, arity=arity, done=done, finish=finish):
      new_done = done + [v]
      if arity == len(new_done):
          res = finish(new_done, self.ctx.get_session())
          return await self.call_continue(await unasync(res), k2)
      else:
          return await self.call_continue(
              VSuspend(name, arity, new_done, finish), k2
          )
  ```
- Keep `VAsync` + `unasync` unchanged.

### Registration sites

- `repl.py` `_reg`: `builtins[surface] = VSuspend.create(surface, arity, lambda args, _session, _f=func: _f(args))`. (Default-arg binding avoids late-binding of `func`; `func` is a per-call parameter so even a bare closure is safe, but the explicit bind is defensive and clear.) `builtins_rts.py` stays untouched (pure `list[Val] -> Val`).
- `repl_session.py` `add_return`: change `_fun` to `def _fun(args: list[Val], _session) -> Val:` (add ignored session param) and call `VSuspend.create(fun_name.surface, 1, _fun)`.
- `repl_session.py` `mk_mod_inst` + `_mk_data`: `_mk_data(tag)` returns `def _con(args, _session): return VData(tag, args)`; call `VSuspend.create(con_name.surface, arity, _mk_data(tag))`.
- `bub_ext.py` `TapeOps.get_primop`: drop `SessionAwareFinish(...)`, pass the bound method directly: `VSuspend.create(name.surface, len(arg_tys), self._current_tape)` (and the other 5). The methods already match `PrimFinish` `(args, session) -> Val` and return `VAsync`.
- `bub_ext.py` `LLMOps`: `return VSuspend.create(name.surface, match_res.orig_arg_num, finish_async(_fun))`.
- `bub_ext.py` import line: `from systemf.elab3.types.suspend import VSuspend, finish_async` (drop the vpartial import). `VAsync` import from `types.val` stays.

### Pretty printer (`val_pp.py`)

- Import `VSuspend` from `.types.suspend`; change `case VPartial(name=name, arity=arity)` → `case VSuspend(name=name, arity=arity)`, keep output `<func {name} {arity}>`.

### Tests

- `systemf/tests/test_elab3/test_eval.py`:
  - Import `VSuspend` from `systemf.elab3.types.suspend` (replace vpartial import).
  - line ~409-412: assert `isinstance(p1, VSuspend)` (field `.done` unchanged).
  - `test_primops_are_vpartial` → rename to `test_primops_are_vsuspend`, assert `isinstance(result, VSuspend)` (`.name`, `.arity`, `.done` unchanged). Update the section banner comment.
  - `FakeCtx`: add
    ```python
    def get_session(self):
        return None
    ```
- `bub_sf/tests/test_bub_ext.py`: no change expected (asserts on `VAsync` from methods). Verify no `VPartial`/`SessionAwareFinish` import; if present, update.

## Why it works

- The evaluator's only structural requirement is: a value in function position
  that collects `arity` args then produces a result. `VSuspend` preserves that
  contract; `create` keeps the nullary-constructor fast path.
- Unifying `finish` to `(args, session) -> Val` lets the evaluator always pass
  `session` (may be `None`), deleting the `isinstance(finish, SessionAwareFinish)`
  branch. Pure primops/constructors simply ignore the session param.
- `VAsync`/`unasync` are orthogonal to the partial-application machinery, so
  async primitives keep working unchanged; `finish_async` provides the same
  convenience `SessionAwareFinish.from_async` did, without a class.
- Every construction site funnels through `VSuspend.create`, making the three
  kinds of primitive uniform.

## Scope / non-goals

- **Not** eliminating explicit `arity` tracking via generator/coroutine-based
  suspension. That would require rewriting every primitive as a
  yielding coroutine (incl. async generators) and is high-risk; the arity field
  is inherent to currying primitives. The complexity actually removed here is
  the dual finish type + evaluator branch, which is what makes the sites
  non-uniform.
- **Not** removing `VAsync` (explicitly out of the "VPartial/SessionAwareFinish"
  scope named by the item; removing it would churn `bub_ext.py` + its 9 tests).

## Files

- Add: `systemf/src/systemf/elab3/types/suspend.py`
- Delete: `systemf/src/systemf/elab3/types/vpartial.py`
- Modify: `systemf/src/systemf/elab3/eval.py`
- Modify: `systemf/src/systemf/elab3/repl.py`
- Modify: `systemf/src/systemf/elab3/repl_session.py`
- Modify: `systemf/src/systemf/elab3/val_pp.py`
- Modify: `bub_sf/src/bub_sf/bub_ext.py`
- Modify: `systemf/tests/test_elab3/test_eval.py`
- Doc: move item #13 to Completed in `systemf/ELAB3_PROJECT_STATUS.md`
