# Remove AgentRunner from Architecture Plan

## Context

CP44 introduced a three-layer architecture: `ChatClient` (parsing) → `TapeSession` (persistence) → `AgentRunner` (orchestration). TapeSession is already built. AgentRunner was planned as Phase 5 but never implemented.

## Decision

**Remove AgentRunner from the architecture.** A class for a 7-line loop is unnecessary overhead. The primitives are already composable — callers write their own loop.

## Current Status

### What exists

| Component | File | Status |
|-----------|------|--------|
| `ChatClient` | `republic/clients/chat.py` | Refactored. `chat()` / `stream()` implemented. |
| `TapeSession` | `republic/tape/session.py` | Fully implemented. `prepare()` / `run()` / `stream()` / `add_tool_results()` / `complete()`. |
| `ToolExecutor` | `republic/tools/executor.py` | Unchanged. `execute_async()`. |

### What does NOT exist

| Component | Status |
|-----------|--------|
| `AgentRunner` class | Never built |
| `test_agent_runner.py` | Never written |

## What AgentRunner Was Supposed to Do

Per CP44 `changes/44-chatclient-architectural-refactor.md:764-793`:

```
AgentRunner responsibilities:
1. Loop control: run → tool_execute → repeat → finished
2. require_runnable validation before first turn
3. max_iterations enforcement
4. Tool dispatch via ToolExecutor.execute_async()
5. Build ToolContext before execution
```

The pseudocode from the plan:

```python
class AgentRunner:
    async def run(self, prompt, session, tools) -> Finished:
        prepared = await session.prepare(prompt=prompt, tools=tools)
        result = await session.run(self._chat, prepared)
        while isinstance(result, ToolCallNeeded):
            execution = await self._tools.execute_async(result.tool_calls, tools=tools)
            prepared = await session.add_tool_results(result, execution.tool_results)
            result = await session.run(self._chat, prepared)
        await session.complete()
        return result
```

## Where Each Responsibility Goes

| Responsibility | New Location | Rationale |
|----------------|-------------|-----------|
| **Loop control** | Caller writes it | 7-line `while` loop. No class needed. |
| **require_runnable validation** | Caller or `ToolExecutor` | Already enforced by `ToolExecutor._build_tool_map()` when no runnable tools found. `get_tool_schemas()` + `normalize_tools()` already provide the split. |
| **max_iterations** | Caller | Simple counter in the caller's loop. Not complex enough to require a dedicated class. |
| **Tool dispatch** | Caller calls `ToolExecutor.execute_async()` | Already a one-liner. `AgentRunner` would have been a thin pass-through. |
| **ToolContext construction** | Caller or utility function | Currently `ChatClient._make_tool_context` (removed in CP44). A module-level `make_tool_context(prepared: PreparedChat) -> ToolContext` suffices. |

## Loop Pattern (Without AgentRunner)

Callers run:

```python
session = TapeSession("my-tape", store)
prepared = await session.prepare(prompt="do x", tools=tools)
result = await session.run(chat, prepared)

while isinstance(result, ToolCallNeeded):
    execution = await tool_executor.execute_async(result.tool_calls, tools=tools)
    prepared = await session.add_tool_results(result, execution.tool_results)
    result = await session.run(chat, prepared)

await session.complete()
# result is Finished
```

If `max_iterations` is needed:

```python
for _ in range(max_turns):
    if not isinstance(result, ToolCallNeeded):
        break
    execution = await tool_executor.execute_async(result.tool_calls, tools=tools)
    prepared = await session.add_tool_results(result, execution.tool_results)
    result = await session.run(chat, prepared)
else:
    raise RepublicError(ErrorKind.TOOL, "Max iterations exceeded")
```

## Impact Analysis

### Files to modify

| File | Action | Details |
|------|--------|---------|
| `changes/44-chatclient-architectural-refactor.md` | Update | Remove AgentRunner layer from architecture tables, boundary tables, code examples |
| `EXECUTION_PLAN.md` | Update | Remove Phase 5 AgentRunner step, merge TapeSession into earlier phase |
| `tasks/5-phase-5-build-tapesession-and-agentrunner.md` | Update | Rename to `5-phase-5-build-tapesession.md`, remove AgentRunner work items |
| `tasks/7-write-tests-for-refactored-api.md` | Update | Remove test_agent_runner.py references |
| `changes/46-test-cases-change-plan.md` | Update | Remove AgentRunner layer from architecture table (line 18), remove test_agent_runner.py test cases (lines 60-70), remove AgentRunner-related gaps (lines 180-182, 186) |
| `republic/src/republic/llm.py` | Update | Remove AgentRunner reference from docstring (line 29) |

### Files that stay unchanged

| File | Reason |
|------|--------|
| `republic/tape/session.py` | Primitive API unaffected. Loop is caller's responsibility. |
| `republic/tools/executor.py` | Already has `execute_async()`. No changes needed. |
| `republic/clients/chat.py` | Already tape-agnostic. No changes needed. |

### Test impact

| Area | Change |
|------|--------|
| `test_agent_runner.py` | **Delete from plan** — never written, so nothing to delete |
| AgentRunner gaps in test plan | Remove: max_iterations, streaming, require_runnable, tool errors |
| Loop integration tests | Move to `test_tape_session.py`: add `test_full_tool_loop_executes_and_returns_final` |
| Bub agent tests | Loop logic tested via bub agent integration (already exists) |

## Open Question

Should we provide a `run_agent()` convenience function (not a class)?

```
async def run_with_tools(prompt, session, chat, tools, max_turns=10) -> Finished:
    ...
```

**Recommendation**: No. The loop is 7 lines. A convenience function obscures the loop and adds an API surface to maintain. If multiple call sites use identical loops, extract into the calling project (e.g., `bub/src/bub/builtin/agent.py`), not into `republic`.

## Checklist

- [ ] Update `changes/44-chatclient-architectural-refactor.md` — remove AgentRunner layer
- [ ] Update `EXECUTION_PLAN.md` — remove Phase 5 AgentRunner step
- [ ] Update `tasks/5-phase-5-build-tapesession-and-agentrunner.md` — rename + strip AgentRunner
- [ ] Update `tasks/7-write-tests-for-refactored-api.md` — remove test_agent_runner.py
- [ ] Update `changes/46-test-cases-change-plan.md` — remove AgentRunner layer
- [ ] Update `republic/src/republic/llm.py` — remove AgentRunner from docstring
