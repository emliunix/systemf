# Exploration: Hook Mechanism for Request-Response Linking

## Notes

### Note 1: Scope
Determine whether any hook can be used to inject request metadata (like a request_id) into outbound messages without modifying the `bub/` package.

### Note 2: Hooks Under Investigation
- `render_outbound` — creates outbound messages from model output
- `dispatch_outbound` — dispatches outbound messages to channels

## Facts

### Fact 1: Hookspec for render_outbound
`bub/src/bub/hookspecs.py:63-72`
```python
@hookspec
def render_outbound(
    self,
    message: Envelope,
    session_id: str,
    state: State,
    model_output: str,
) -> list[Envelope]:
    """Render outbound messages from model output."""
```
No `firstresult=True` marker.

### Fact 2: Hookspec for dispatch_outbound
`bub/src/bub/hookspecs.py:74-77`
```python
@hookspec
def dispatch_outbound(self, message: Envelope) -> bool:
    """Dispatch one outbound message to external channel(s)."""
```
No `firstresult=True` marker.

### Fact 3: call_many Aggregates All Results
`bub/src/bub/hook_runtime.py:36-48`
```python
async def call_many(self, hook_name: str, **kwargs: Any) -> list[Any]:
    results: list[Any] = []
    for impl in self._iter_hookimpls(hook_name):
        call_kwargs = self._kwargs_for_impl(impl, kwargs)
        value = await self._invoke_impl_async(...)
        if value is _SKIP_VALUE:
            continue
        results.append(value)
    return results
```

### Fact 4: _collect_outbounds Merges All Batches
`bub/src/bub/framework.py:216-246`
```python
async def _collect_outbounds(...):
    batches = await self._hook_runtime.call_many("render_outbound", ...)
    outbounds: list[Envelope] = []
    for batch in batches:
        outbounds.extend(unpack_batch(batch))
    if outbounds:
        return outbounds
    ...
```

### Fact 5: unpack_batch Behavior
`bub/src/bub/envelope.py:35-42`
```python
def unpack_batch(batch: Any) -> list[Envelope]:
    if batch is None:
        return []
    if isinstance(batch, list | tuple):
        return list(batch)
    return [batch]
```

### Fact 6: Framework Dispatches All Outbounds
`bub/src/bub/framework.py:137-139`
```python
outbounds = await self._collect_outbounds(...)
for outbound in outbounds:
    await self._hook_runtime.call_many("dispatch_outbound", message=outbound)
```

### Fact 7: Framework Ignores dispatch_outbound Return Values
Same code as Fact 6: return values from `call_many` are not checked.

### Fact 8: Builtin render_outbound Always Returns One Outbound
`bub/src/bub/builtin/hook_impl.py:290-306`
```python
def render_outbound(self, message, session_id, state, model_output):
    outbound = ChannelMessage(
        session_id=session_id,
        channel=field_of(message, "channel", "default"),
        chat_id=field_of(message, "chat_id", "default"),
        content=model_output,
        output_channel=field_of(message, "output_channel", "default"),
        kind=field_of(message, "kind", "normal"),
    )
    return [outbound]
```

### Fact 9: Builtin dispatch_outbound Calls dispatch_via_router
`bub/src/bub/builtin/hook_impl.py:282-288`
```python
async def dispatch_outbound(self, message: Envelope) -> bool:
    content = content_of(message)
    session_id = field_of(message, "session_id")
    ...
    return await self.framework.dispatch_via_router(message)
```

### Fact 10: dispatch_via_router Calls ChannelManager.dispatch_output
`bub/src/bub/framework.py:198-206`
```python
async def dispatch_via_router(self, message: Envelope) -> bool:
    if self._outbound_router is None:
        return False
    return await self._outbound_router.dispatch_output(message)
```

## Claims

### Claim 1: render_outbound Hook Cannot Override Builtin Output
**Reasoning:** `render_outbound` is a `call_many` hook (Fact 1, Fact 3). The framework collects results from ALL implementations (Fact 4). The builtin hook always returns one outbound (Fact 8). If our hook also returns an outbound, `unpack_batch` (Fact 5) adds both to the list. The framework then dispatches BOTH (Fact 6). There is no mechanism to suppress the builtin hook's output.
**References:** Fact 1, Fact 3, Fact 4, Fact 5, Fact 6, Fact 8

### Claim 2: render_outbound Hook Causes Duplicate Messages for bub_events
**Reasoning:** For a bub_events message, the builtin hook creates an outbound without context (Fact 8). If our hook creates an outbound with context, `_collect_outbounds` (Fact 4) receives both batches and extends them into the outbounds list. Both outbounds are then dispatched (Fact 6). The channel receives two `send()` calls for the same logical response. For non-bub_events messages, our hook can return `None` which `unpack_batch` converts to `[]` (Fact 5), avoiding duplicates for other channels.
**References:** Fact 4, Fact 5, Fact 6, Fact 8

### Claim 3: dispatch_outbound Hook Cannot Prevent Builtin Dispatch
**Reasoning:** `dispatch_outbound` is a `call_many` hook (Fact 2, Fact 3). The framework calls ALL implementations for every outbound message (Fact 6). Even if our hook runs first and returns `True`, the builtin hook still runs afterward because `call_many` iterates through all implementations and the framework ignores return values (Fact 7). The builtin hook calls `dispatch_via_router` (Fact 9) which calls `ChannelManager.dispatch_output` (Fact 10) which calls `channel.send()`. Our hook cannot prevent this.
**References:** Fact 2, Fact 3, Fact 6, Fact 7, Fact 9, Fact 10

### Claim 4: Hooks Cannot Solve the Linking Problem Without Modifying bub
**Reasoning:** `render_outbound` hook causes duplicates (Claim 2). `dispatch_outbound` hook cannot intercept (Claim 3). No other hook in the pipeline (`resolve_session`, `build_prompt`, `load_state`, `save_state`) has access to outbound message creation. Therefore, no hook-based solution exists that satisfies the constraint of not modifying `bub/`.
**References:** Claim 2, Claim 3

### Claim 5: Hook-Based Solutions Require Either Modifying bub OR Accepting Duplicates
**Reasoning:** The only way to make `render_outbound` work would be to change it from `call_many` to `firstresult` in `bub/src/bub/hookspecs.py`, or to add a mechanism to suppress the builtin hook. Both require modifying `bub/`. Without such changes, any `render_outbound` hook for bub_events messages produces duplicates.
**References:** Claim 1, Claim 2
