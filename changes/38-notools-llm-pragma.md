# 38: Add `notools` LLM Pragma Option

**Date:** 2026-05-06
**Status:** Done
**Area:** `bub_sf/src/bub_sf/bub_ext.py`

## Facts

1. **Pragma format**: `{-# LLM #-}` pragma content is parsed as a string value in `dict[str, str]` under key `"LLM"`. Example: `{"LLM": "model=gpt-4"}` or `{"LLM": "notools"}`.
2. **Pragma access**: In `bub_ext.py:86`, `thing.metas.pragma.get("LLM")` returns the pragma content string (or `None` if no LLM pragma).
3. **Agent tool control**: `Agent.run()` and `Agent.run_stream()` (in `bub/src/bub/builtin/agent.py:87-139`) accept `allowed_tools: Collection[str] | None`. Passing an empty list `[]` disables all tools; passing `None` allows all registered tools.
4. **LLM call paths**: `bub_ext.py` has two call paths:
   - `_stream_llm_call()` for `LLM a` return types — calls `run_agent_with_repl_and_stream()`
   - `_direct_llm_call()` for non-LLM return types — calls `run_agent_with_repl()`
5. **Current behavior**: Both paths pass no `allowed_tools`, so all tools are available to the LLM.

## Design

Parse the LLM pragma string for the `notools` and `noskills` keywords. When present, restrict the agent's capabilities accordingly.

### Pragma Grammar

```
{-# LLM [notools] [noskills] [other options...] #-}
```

### `notools` Keyword

When present, restricts tools to only the essential `sf.repl` tool:

```python
case "notools": agent_kwargs["allowed_tools"] = ["sf.repl"]
```

**Why keep `sf.repl`?** `sf.repl` is the core tool that allows the LLM to interact with the SystemF REPL and set return values. Without it, the synthesized function cannot communicate its result back to the program. The `notools` option suppresses all *other* tools (file system, bash, web, etc.) while preserving this essential capability.

### `noskills` Keyword

When present, disables all markdown skills (system prompt injections):

```python
case "noskills": agent_kwargs["allowed_skills"] = []
```

This prevents skill-based system prompts from being injected, giving a cleaner context window when skills are not needed.

### Implementation

In `bub_sf/src/bub_sf/bub_ext.py`, in the `_fun` async closure inside `LLMOps.get_primop()` (around line 91):

```python
llm_opts = [s.strip() for s in llm_prag.split(" ")]
agent_kwargs = {}
for opt in llm_opts:
    match opt:
        case "notools": agent_kwargs["allowed_tools"] = ["sf.repl"]
        case "noskills": agent_kwargs["allowed_skills"] = []
        case _: pass
```

The `agent_kwargs` dict is then forwarded through the call chain via `**kwargs` using a `TypedDict`:

```python
class LLMCallConfig(TypedDict, total=False):
    allowed_tools: list[str] | None
    allowed_skills: list[str] | None
    model: str | None
```

### Modified Functions

- `run_agent_with_repl()`: add `**kwargs: Unpack[LLMCallConfig]` parameter, forward to `agent.run(...)`
- `run_agent_with_repl_and_stream()`: add `**kwargs: Unpack[LLMCallConfig]` parameter, forward to `agent.run_stream(...)`
- `_stream_llm_call()`: add `**kwargs: Unpack[LLMCallConfig]` parameter
- `_direct_llm_call()`: add `**kwargs: Unpack[LLMCallConfig]` parameter
- `LLMOps.get_primop()`: parse pragma for `notools`/`noskills`, populate `agent_kwargs`

## Why It Works

- The agent framework already supports `allowed_tools` and `allowed_skills` filtering.
- Token splitting (`pragma_str.split()`) is safe for simple keywords — quoted values won't match exactly.
- `sf.repl` is intentionally kept as the minimum viable tool for the synthesized function to operate.
- The `TypedDict` with `Unpack` provides type-safe kwargs forwarding.

## Files

- `bub_sf/src/bub_sf/bub_ext.py` — parse pragma, forward kwargs through call chain
- `bub_sf/tests/` — add tests for `notools` and `noskills` pragma options

## Related

- `status.md` item 18
- `status.md` item 9 (LLM pragma to support temporary flag, allowed tools config, model config)
- `changes/37-funcall-prompt-level-instruct.md` — sibling pragma feature
