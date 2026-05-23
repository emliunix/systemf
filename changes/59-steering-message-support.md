# 59: Steering Message Support

**Date:** 2026-05-23
**Status:** Design in progress
**Area:** `bub/src/bub/builtin/agent.py`, `bub/src/bub/builtin/hook_impl.py`

## Raw Design Input

> - the extension point is at run_stream_model hook
> - there' will be a queue bound to a session
> - and instead of calling the agent directly with the message
> - the message is put into the queue
> - and we call _ensure_agent() to ensure agent call is live for this session

> So what we do is to pass a queue direct into the agent loop for it to check if any message needs to be consumed immediately
> and that means we'll deprecate the serialization design which blocks the message

## What it's NOT

<edit>cite the 56 change and explain why it's not</edit>

## Problem

Agent loops run for minutes across multiple steps. Corrections sent mid-loop must reach the running loop immediately, not queue until the turn finishes.

## Key Insight

<edit>all we keep in the doc is key insight, so just move this up to what it's NOT</edit>

**changes/56 (Per-Session Message Serialization)** is deprecated. External blocking queues prevent steering from reaching the active loop. Instead, the queue is passed **into** the agent loop, which checks it between steps.

## Architecture

### Steering Queue

Per-session `asyncio.Queue` stored in `BuiltinImpl`:

<edit>should not be placed in BuiltinImpl, in `bub_sf/src/bub_sf/hook.py`, that's where we starts to process message, so queue is scoped to that hook method, under our hook impl</edit>

```python
class BuiltinImpl:
    _steering_queues: ClassVar[dict[str, asyncio.Queue[str]]] = {}

    @staticmethod
    def enqueue_steering(session_id: str, message: str) -> None:
        queue = BuiltinImpl._steering_queues.setdefault(session_id, asyncio.Queue())
        queue.put_nowait(message)
```

### Entry Point

`run_model_stream` passes the queue to the agent:

<edit>we should repurpose prompt (rename to prompts) arg to be or type of `str | Queue[str]`, for agent.run_stream</edit>

<edit>and for _ensure_agent(), it should be to await the current agent and until it finishes (for cases when it's already exiting) and checks if any message failed to be processed then respawn. _ensure_agent() itself should be a task too, that the next _ensure_agent awaits for</edit>

<edit>`run_model_stream` should still take prompt of str | list[dict]</edit>

```python
@hookimpl
async def run_model_stream(self, prompt, session_id, state):
    tape_name = get_tape_name(state)
    agent = self._get_agent()
    if (events := await agent.run_command_stream(tape_name, prompt, state)) is not None:
        return events
    
    steering_queue = self._steering_queues.get(session_id)
    return await agent.run_stream(
        tape_name=tape_name, prompt=prompt, state=state,
        steering_queue=steering_queue,
    )
```

### Agent Loop Integration

The loop checks the queue after each LLM response returns and before evaluating the result:

```python
async def _loop(self, session, prompt, state, ..., *, steering_queue=None):
    # ... setup ...
    
    for step in range(1, self.settings.max_steps + 1):
        async with asyncio.timeout(self.settings.model_timeout_seconds):
            turn_result = await session.run(self._chat, prepared)
        
        # Consume steering immediately after LLM response
        if steering_queue is not None:
            while not steering_queue.empty():
                await session.append_message(steering_queue.get_nowait(), role="user")
        
        match turn_result:
            case Finished(result):
                return result.text or ""
            case ToolCallNeeded() as needed:
                prepared, handoffs_left = await self._tool_call(...)
                # _prepare_turn() includes steering in next prompt
```

**Why after `session.run()`:** The LLM call is a blocking HTTP request. We cannot interrupt it mid-flight. Checking immediately after is acceptable — LLM calls are seconds, tool executions are minutes.

**Why append to session:** Steering must appear in the conversation history for the LLM to see it on subsequent turns. `session.append_message()` adds it to the deferred entries, which `_prepare_turn()` includes in the next `PreparedChat`.

### Streaming

Same check point in `_loop_stream_gen()` — after `_run_once()` yields all events for the step:

```python
async for event in _run_once(prepared, res):
    yield event

if steering_queue is not None:
    while not steering_queue.empty():
        await session.append_message(steering_queue.get_nowait(), role="user")
```

### Queue Lifecycle

- Created on-demand per session
- Checked between every step
- Not drained on turn completion — remaining messages stay for the next turn
- Optional cleanup on session end

## Facts

| # | Fact | Location |
|---|---|---|
| 1 | Agent loop is multi-step, each step = LLM call + optional tool execution | `agent.py:236-258` |
| 2 | `session.run()` blocks until LLM response completes | `agent.py:243` |
| 3 | `_tool_call()` rebuilds `prepared` via `_prepare_turn()` for next step | `agent.py:341-371` |
| 4 | `run_model_stream` is the framework entry point | `hook_impl.py:168-174` |
| 5 | `session.prepare()` builds the message list sent to LLM | `agent.py:506-515` |
| 6 | `TapeSession` buffers entries until flush | changes/58 |
| 7 | Commands bypass the agent loop | `hook_impl.py:164-166` |

## Claims

| # | Claim | Evidence |
|---|---|---|
| 1 | Steering queue must be passed into the agent loop, not managed externally | Facts 1, 2 |
| 2 | Steering is checked between steps, not within an LLM call | Fact 2 |
| 3 | Steering messages are appended to tape as user messages | Facts 5, 6 |
| 4 | `_prepare_turn()` is the injection point | Facts 3, 5 |
| 5 | Queue is bound to session ID, not tape name | Fact 4 |
| 6 | Steering deprecates message serialization (changes/56) | Claim 1 |

## Open Questions

1. Should steering trigger immediate re-prompt without tool execution?
2. Should there be a `developer`/`system` role for steering distinct from `user`?
3. Should we check steering between individual tool executions within `_tool_call()`?
4. Should steering be exposed as a tool for agents to enqueue?
5. Format: plain text, or structured with priority/expiration?

## References

- `changes/56-per-session-message-serialization.md` — deprecated
- `changes/58-session-handoff-and-store-fork.md` — tape session semantics
- `bub/src/bub/builtin/agent.py` — agent loop
- `bub/src/bub/builtin/hook_impl.py` — hook entry points
- `status.md` — Todo #24
