# Exploration: bub_events Bidirectional Request-Response

## Notes

### Note 1: Goal
Find a mechanism to link inbound HTTP requests to outbound framework responses in `bub_events` channel without modifying any code in the `bub/` package.

### Note 2: Constraint
The `bub/` package must remain untouched. All changes must be confined to `bub_events/`.

## Facts

### Fact 1: process_inbound Flow
`bub/src/bub/framework.py:105-144`
```python
async def process_inbound(self, inbound: Envelope, stream_output: bool = False) -> TurnResult:
    session_id = await self._hook_runtime.call_first(
        "resolve_session", message=inbound
    ) or self._default_session_id(inbound)
    ...
    outbounds = await self._collect_outbounds(inbound, session_id, state, model_output)
    for outbound in outbounds:
        await self._hook_runtime.call_many("dispatch_outbound", message=outbound)
```

### Fact 2: resolve_session Reads session_id
`bub/src/bub/builtin/hook_impl.py:106-112`
```python
def resolve_session(self, message: ChannelMessage) -> str:
    session_id = field_of(message, "session_id")
    if session_id is not None and str(session_id).strip():
        return str(session_id)
    ...
```

### Fact 3: render_outbound Copies session_id to Outbound
`bub/src/bub/builtin/hook_impl.py:290-306`
```python
def render_outbound(self, message, session_id, state, model_output):
    outbound = ChannelMessage(
        session_id=session_id,  # From parameter
        ...
    )
```

### Fact 4: render_outbound Does NOT Copy Context
Same code as Fact 3: no `context=...` parameter. Context from inbound is lost.

### Fact 5: dispatch_output Copies session_id to send() Message
`bub/src/bub/channels/manager.py:96-104`
```python
outbound = ChannelMessage(
    session_id=str(field_of(message, "session_id", ...)),
    ...
)
await channel.send(outbound)
```

### Fact 6: Hookspec for render_outbound is NOT firstresult
`bub/src/bub/hookspecs.py:63-72`
No `firstresult=True` marker. `call_many` is used, which aggregates all hook results.

### Fact 7: call_many Aggregates ALL Results
`bub/src/bub/hook_runtime.py:36-48`
```python
async def call_many(self, hook_name: str, **kwargs: Any) -> list[Any]:
    results: list[Any] = []
    for impl in self._iter_hookimpls(hook_name):
        ...
        results.append(value)
    return results
```

### Fact 8: _collect_outbounds Merges All Batches
`bub/src/bub/framework.py:216-246`
```python
async def _collect_outbounds(...):
    batches = await self._hook_runtime.call_many("render_outbound", ...)
    outbounds: list[Envelope] = []
    for batch in batches:
        outbounds.extend(unpack_batch(batch))
```

### Fact 9: Framework Ignores dispatch_outbound Return Values
`bub/src/bub/framework.py:137-139`
Return values from `call_many` are not checked or used.

### Fact 10: Builtin render_outbound Always Returns One Outbound
`bub/src/bub/builtin/hook_impl.py:290-306`
Always returns `[outbound]` for every message.

## Claims

### Claim 1: Context Cannot Be Used for Linking Without Modifying bub
**Reasoning:** `render_outbound` (Fact 4) does not copy `context` from inbound to outbound. Even if a custom `render_outbound` hook is added (Fact 6, Fact 7, Fact 8), the builtin hook still produces an outbound (Fact 10), resulting in duplicate messages. `call_many` cannot suppress other implementations.
**References:** Fact 4, Fact 6, Fact 7, Fact 8, Fact 10

### Claim 2: Hooks Cannot Solve the Linking Problem
**Reasoning:** `render_outbound` hook causes duplicates (Claim 1). `dispatch_outbound` hook cannot prevent builtin dispatch because `call_many` runs all implementations and ignores return values (Fact 9). No other hook has access to outbound creation.
**References:** Claim 1, Fact 9

### Claim 3: session_id Survives the Full Round-Trip
**Reasoning:** `resolve_session` (Fact 2) reads `session_id` from inbound. `render_outbound` (Fact 3) receives this as a parameter and writes it to outbound. `dispatch_output` (Fact 5) copies it to the `ChannelMessage` passed to `channel.send()`. Therefore `session_id` is fully propagated without any modifications to `bub/`.
**References:** Fact 2, Fact 3, Fact 5
