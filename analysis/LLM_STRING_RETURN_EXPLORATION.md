# Exploration: Special String Return for LLM-Synthesized Functions

**Date:** 2026-05-05
**Topic:** LLM synthesized functions with String return type

## Notes

### Note 1: Problem Statement
When a `{-# LLM #-}` synthesized function has return type `String`, the current implementation requires the LLM to call `set_return` via the `sf.repl` tool to communicate its result. This is awkward because the LLM's natural response message IS the return value. We should treat `String` return type specially: use the LLM's response directly.

### Note 2: Scope
- In scope: `_direct_llm_call` path (non-streaming, return type is `a`)
- Potentially in scope: `_stream_llm_call` path (streaming, return type is `LLM a`)
- Out of scope: Changing the `set_return` mechanism for non-String types

### Note 3: Entry Points
- `bub_sf/src/bub_sf/bub_ext.py:343` — `_direct_llm_call`
- `bub_sf/src/bub_sf/bub_ext.py:330` — `_stream_llm_call`
- `systemf/src/systemf/elab3/repl_session.py:107` — `add_return` (creates `set_return`)

## Facts

### Fact 1: Current `_direct_llm_call` discards agent output
`bub_sf/src/bub_sf/bub_ext.py:343-358`
```python
async def _direct_llm_call(
    session: REPLSessionProto, tape_name: str,
    name: Name, doc: str | None,
    arg_vals: list[Val], arg_tys: list[Ty], arg_docs: list[str | None],
    res: list[Val | None], res_ty: Ty, res_doc: str | None,
) -> Val:
    func_prompt = _build_func_prompt(...)
    _ = await run_agent_with_repl(session, tape_name, func_prompt)
    # return captured value, discard agent output
    if res[0] is None:
        raise Exception("Expected return value to be set by test_prim body")
    return res[0]
```

### Fact 2: `_stream_llm_call` returns raw stream tuple
`bub_sf/src/bub_sf/bub_ext.py:330-340`
```python
async def _stream_llm_call(...) -> Val:
    prompt = "\n".join([...])
    return VPrim((await run_agent_with_repl_and_stream(session, tape_name, prompt), res))
```

### Fact 3: `set_return` is created via `add_return`
`systemf/src/systemf/elab3/repl_session.py:107-120`
```python
def add_return(self, ref: list[Val | None], ty: Ty) -> None:
    ret_mod = f"Ret{self.ctx.next_replmod_id()}"
    fun_ty = TyFun(ty, TyConApp(name=bi.BUILTIN_UNIT, args=[]))
    def _fun(args: list[Val]) -> Val:
        ref[0] = args[0]
        return bi.UNIT_VAL
    fun_name = self.name_gen(ret_mod).new_name("set_return", None)
    ...
```

### Fact 4: `TyString` is a distinct type constructor
`systemf/src/systemf/elab3/types/ty.py:107-109`
```python
@dataclass(frozen=True, repr=False)
class TyString(TyLit):
    pass
```

### Fact 5: Return type matching extracts inner LLM type
`bub_sf/src/bub_sf/bub_ext.py:274-276`
```python
if (inner_res := _match_llm_ty(res_ty, session)) is not None:
    is_llm_res = True
    res_ty = inner_res
```
After this, `res_ty` is the unwrapped type (e.g., `String` for `LLM String`).

## Claims

### Claim 1: `_direct_llm_call` should use agent output for String returns
When `res_ty` is `TyString`, `_direct_llm_call` should return `VLit(LitString(output))` where `output` is the agent's response, instead of requiring `set_return` to be called.

**Reasoning:** The LLM's natural text response is the String value. Requiring a tool call to set a String return is awkward and unnecessary. For other types (Int, custom data), `set_return` is still needed because the LLM must produce structured data.

**References:** Fact 1, Fact 4, Note 1

### Claim 2: `_stream_llm_call` may also need special handling for String
When `res_ty` is `TyString` in `_stream_llm_call`, the stream events should be collected into a String instead of returning the raw `(AsyncStreamEvents, res)` tuple.

**Reasoning:** The current `_stream_llm_call` returns `VPrim((stream, res))` which is not a proper `Val` representation. If the inner type is `String`, we should consume the stream and produce a `VLit(LitString(...))`.

**References:** Fact 2, Fact 5

### Claim 3: `set_return` can be skipped for String returns
For String return types, we can avoid creating the `set_return` tool in the forked REPL session, or simply ignore it if created.

**Reasoning:** If we use the agent output directly, the `set_return` mechanism becomes redundant. However, keeping it doesn't hurt — the LLM may still call it, but we'll ignore the result.

**References:** Fact 3, Claim 1
