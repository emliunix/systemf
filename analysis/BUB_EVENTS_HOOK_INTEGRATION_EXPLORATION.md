# Exploration: Events Channel Hook Integration

## Notes

### Note 1: Goal
Determine how `bub_events` can inject channel-specific knowledge into the agent prompt when processing events channel messages. We need to add contextual information (sender, topic) that helps the agent understand it's handling an event, not a chat message.

### Note 2: Scope
Investigate two hook candidates: `system_prompt` and `build_prompt`. Evaluate which hook can conditionally inject event context based on message provenance.

### Note 3: Constraints
- Must not break existing behavior for non-events channels
- Must work within the existing hook framework without modifying `bub/`
- Must be able to detect that a message originated from the events channel

## Facts

### Fact 1: system_prompt Hook Signature
`bub/src/bub/hookspecs.py:92-94`
```python
@hookspec
def system_prompt(self, prompt: str | list[dict], state: State) -> str:
    """Provide a system prompt to be prepended to all model prompts."""
```

### Fact 2: system_prompt Does Not Receive Message
`bub/src/bub/builtin/agent.py:563-566`
```python
def _system_prompt(self, prompt: str, state: State, allowed_skills: set[str] | None = None) -> str:
    if result := self.framework.get_system_prompt(prompt=prompt, state=state):
        return result
    return ""
```
The hook only receives `prompt` and `state`. No `message` parameter is available.

### Fact 3: build_prompt Hook Signature
`bub/src/bub/hookspecs.py:29-36`
```python
@hookspec(firstresult=True)
def build_prompt(self, message: Envelope, session_id: str, state: State) -> str | list[dict]:
    """Build model prompt for this turn."""
```

### Fact 4: build_prompt Receives Message
The hook receives `message` (Envelope/ChannelMessage), which contains `channel`, `context`, and all message fields.

### Fact 5: call_first Returns First Non-None Value
`bub/src/bub/hook_runtime.py:22-34`
```python
async def call_first(self, hook_name: str, **kwargs: Any) -> Any:
    for impl in self._iter_hookimpls(hook_name):
        ...
        value = await self._invoke_impl_async(...)
        if value is _SKIP_VALUE:
            continue
        if value is not None:
            return value
    return None
```
If an implementation returns `None`, execution falls through to the next implementation.

### Fact 6: Default build_prompt Implementation
`bub/src/bub/builtin/hook_impl.py:131-158`
```python
@hookimpl
async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
    content = content_of(message)
    if content.startswith(","):
        message.kind = "command"
        return content
    context = field_of(message, "context_str")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
    text = f"{context_prefix}{content}"
    ...
```

### Fact 7: Context Already Includes Sender and Topic
`bub_events/src/bub_events/channel.py:103`
```python
context={"sender": msg.sender, "topic": msg.topic, **msg.meta},
```
The events channel already places `sender` and `topic` in `ChannelMessage.context`.

### Fact 8: Context Is LLM-Facing
`analysis/BUB_EVENTS_CHANNEL_MESSAGE_EXPLORATION.md:216`
```
context: Prompt metadata. Auto-populated with $channel and chat_id. Custom keys visible to LLM during turn.
```

### Fact 9: Context Is Formatted Into Prompt
`bub/src/bub/builtin/hook_impl.py:137-140`
```python
context = field_of(message, "context_str")
now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
text = f"{context_prefix}{content}"
```
The `context_str` property formats context as `key=value|key=value` and prepends it to the prompt.

### Fact 10: Builtin Hooks Registered Before Entry Points
`bub/src/bub/framework.py:51-79`
```python
def _load_builtin_hooks(self) -> None:
    from bub.builtin.hook_impl import BuiltinImpl
    impl = BuiltinImpl(self)
    self._plugin_manager.register(impl, name="builtin")

def load_hooks(self) -> None:
    self._load_builtin_hooks()
    for entry_point in importlib.metadata.entry_points(group="bub"):
        ...
        self._plugin_manager.register(plugin, name=plugin_name)
```
Builtin hooks are registered first, then entry point plugins (including bub_events).

### Fact 11: Hook Execution Reverses Registration Order
`bub/src/bub/hook_runtime.py:153-157`
```python
def _iter_hookimpls(self, hook_name: str) -> list[Any]:
    hook = getattr(self._plugin_manager.hook, hook_name, None)
    if hook is None or not hasattr(hook, "get_hookimpls"):
        return []
    return list(reversed(hook.get_hookimpls()))
```
Hook implementations are executed in reverse registration order: bub_events runs before builtin.

### Fact 12: system_prompt Is Static by Design
`bub/src/bub/builtin/agent.py:572-582`
```python
def _system_prompt(self, prompt: str, state: State, allowed_skills: set[str] | None = None) -> str:
    blocks: list[str] = []
    if result := self.framework.get_system_prompt(prompt=prompt, state=state):
        blocks.append(result)
    tools_prompt = render_tools_prompt(REGISTRY.values())
    if tools_prompt:
        blocks.append(tools_prompt)
    workspace = workspace_from_state(state)
    if skills_prompt := self._load_skills_prompt(prompt, workspace, allowed_skills):
        blocks.append(skills_prompt)
    return "\n\n".join(blocks)
```
`system_prompt` hook feeds into agent's static system prompt construction alongside tools and skills. It should not contain per-message dynamic content.

## Claims

### Claim 1: system_prompt Cannot Detect Events Channel Messages
**Reasoning:** `system_prompt` (Fact 1) only receives `prompt` and `state` (Fact 2). It has no access to the `message` parameter, so it cannot check `message.channel == "bub-events"` or inspect `message.context`. Therefore it cannot conditionally inject event-specific context.
**References:** Fact 1, Fact 2

### Claim 2: build_prompt Hook Can Fallback to Builtin
**Reasoning:** `call_first` skips `None` results (Fact 5). If a custom `build_prompt` hook returns `None` for non-events messages, execution falls through to the builtin hook (Fact 6). Plugin execution order is reversed from registration (Fact 11), so bub_events hook runs before builtin. This means: return `None` → builtin handles normally; return non-None → we completely replace builtin's prompt construction.
**References:** Fact 5, Fact 6, Fact 10, Fact 11

### Claim 3: system_prompt Is Inappropriate for Per-Message Context
**Reasoning:** `system_prompt` hook is designed for static agent persona, tools, and skills (Fact 12). It only receives `prompt` and `state` (Fact 2), not `message`, so it cannot detect channel or topic. Using `load_state` to pass message info into state, then reading it in `system_prompt`, violates the static design intent. Per-message dynamic content belongs in `build_prompt`, not `system_prompt`.
**References:** Fact 1, Fact 2, Fact 12

### Claim 4: Custom build_prompt Hook Needed for Topic Documentation Loading
**Reasoning:** For basic sender/topic exposure, context propagation (Fact 9) is sufficient. However, for loading comprehensive topic documentation (`{workspace}/event_prompts/{topic}.md`), a custom hook is required. The hook must: (a) detect `message.channel == "bub-events"`, (b) read `topic` from `message.context`, (c) check if the markdown file exists, (d) add a reference instruction to the prompt. Because `build_prompt` is `firstresult=True`, the hook must replicate builtin's prompt construction logic (context prefix, date, media handling) for events, or return `None` to let builtin handle non-events.
**References:** Fact 3, Fact 4, Fact 6, Fact 7, Claim 2

### Claim 5: Topic Doc Should Be Referenced, Not Embedded
**Reasoning:** Topic documentation files (`events/<topic>.md`) may be large and comprehensive. Embedding the full content in every event prompt would be token-inefficient. Instead, the prompt should reference the file path and instruct the agent to read it if needed. The agent has `fs.read` tools available to load the content when relevant. This follows the principle of progressive disclosure: mention the resource exists, let the agent decide to load it.
**References:** Fact 6, Claim 4

### Claim 6: Prompt Must Indicate Missing Topic Docs
**Reasoning:** When an event has a `topic` but no corresponding `events/<topic>.md` file exists, the prompt should explicitly state this. This prevents the agent from hallucinating topic-specific knowledge or assuming documentation exists when it doesn't. The explicit "no recorded info" statement sets correct expectations.
**References:** Claim 5
