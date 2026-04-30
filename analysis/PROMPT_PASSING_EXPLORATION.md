# Prompt Passing in Bub Agent — list[dict] Type Exploration

## Notes

### Note 1: Investigation Context
The Bub agent accepts prompts as `str | list[dict]` throughout its pipeline. This exploration traces the origin, construction, flow, and consumption of `list[dict]` prompts to understand the multimodal message format used in the framework.

### Note 2: Scope
- IN: How `list[dict]` prompts are constructed, passed, and consumed
- IN: The OpenAI-style multimodal format
- OUT: Internal LLM API implementation details (republic tape)
- OUT: Hook plugin architecture beyond prompt-related hooks

### Note 3: Central Questions
1. Where is `list[dict]` created and what does it contain?
2. How does the prompt flow from entry point to LLM invocation?
3. When is text extracted from `list[dict]` vs. passing the full structure?
4. How does the framework handle backward compatibility with plain `str` prompts?

---

## Facts

### Fact 1: Prompt Type Declaration in Hooks
`bub/src/bub/hookspecs.py:30`
```python
def build_prompt(self, message: Envelope, session_id: str, state: State) -> str | list[dict]:
```

`bub/src/bub/hookspecs.py:39`
```python
def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
```

`bub/src/bub/hookspecs.py:44`
```python
def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
```

### Fact 2: Prompt Construction with Media Attachments
`bub/src/bub/builtin/hook_impl.py:131-157`
```python
async def build_prompt(self, message: ChannelMessage, session_id: str, state: State) -> str | list[dict]:
    content = content_of(message)
    if content.startswith(","):
        message.kind = "command"
        return content
    context = field_of(message, "context_str")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
    text = f"{context_prefix}{content}"

    media = field_of(message, "media") or []
    if not media:
        return text

    media_parts: list[dict] = []
    for item in cast("list[MediaItem]", media):
        match item.type:
            case "image":
                data_url = await item.get_url()
                if not data_url:
                    continue
                media_parts.append({"type": "image_url", "image_url": {"url": data_url}})
            case _:
                pass  # TODO: Not supported for now
    if media_parts:
        return [{"type": "text", "text": text}, *media_parts]
    return text
```

### Fact 3: Agent Entry Points Accept Both Types
`bub/src/bub/builtin/agent.py:87-108`
```python
async def run(
    self,
    *,
    session_id: str,
    prompt: str | list[dict],
    state: State,
    model: str | None = None,
    allowed_skills: Collection[str] | None = None,
    allowed_tools: Collection[str] | None = None,
) -> str:
    if not prompt:
        return "error: empty prompt"
    tape = self.tapes.session_tape(session_id, workspace_from_state(state))
    tape.context = replace(tape.context, state=state)
    merge_back = not session_id.startswith("temp/")
    async with self.tapes.fork_tape(tape.name, merge_back=merge_back):
        await self.tapes.ensure_bootstrap_anchor(tape.name)
        if isinstance(prompt, str) and prompt.strip().startswith(","):
            return await self._run_command(tape=tape, line=prompt.strip())
        return await self._agent_loop(
            tape=tape, prompt=prompt, model=model, allowed_skills=allowed_skills, allowed_tools=allowed_tools
        )
```

`bub/src/bub/builtin/agent.py:110-150`
```python
async def run_stream(
    self,
    *,
    session_id: str,
    prompt: str | list[dict],
    state: State,
    model: str | None = None,
    allowed_skills: Collection[str] | None = None,
    allowed_tools: Collection[str] | None = None,
) -> AsyncStreamEvents:
    if not prompt:
        events = [
            StreamEvent("text", {"delta": "error: empty prompt"}),
            StreamEvent("final", {"text": "error: empty prompt", "ok": False}),
        ]
        return self._events_from_iterable(events)
    # ...fork tape, check command, then:
    events = await self._agent_loop(
        tape=tape,
        prompt=prompt,
        model=model,
        allowed_skills=allowed_skills,
        allowed_tools=allowed_tools,
        stream_output=True,
    )
```

### Fact 4: Agent Loop Carries Prompt Through Iterations
`bub/src/bub/builtin/agent.py:216-256`
```python
async def _agent_loop(
    self,
    *,
    tape: Tape,
    prompt: str | list[dict],
    model: str | None = None,
    allowed_skills: Collection[str] | None = None,
    allowed_tools: Collection[str] | None = None,
    stream_output: bool = False,
) -> AsyncStreamEvents | str:
    next_prompt: str | list[dict] = prompt
    display_model = model or self.settings.model
    await self.tapes.append_event(
        tape.name,
        "loop.start",
        {
            "model": display_model,
            "prompt": prompt,
            "allowed_skills": list(allowed_skills) if allowed_skills else None,
            "allowed_tools": list(allowed_tools) if allowed_tools else None,
        },
    )
    if stream_output:
        state = StreamState()
        iterator = self._stream_events_with_auto_handoff(
            tape=tape,
            prompt=next_prompt,
            state=state,
            model=model,
            allowed_skills=allowed_skills,
            allowed_tools=allowed_tools,
        )
        return AsyncStreamEvents(iterator, state=state)
    else:
        return await self._run_tools_with_auto_handoff(
            tape=tape,
            prompt=next_prompt,
            model=model,
            allowed_skills=allowed_skills,
            allowed_tools=allowed_tools,
        )
```

### Fact 5: Text Extraction for System Prompt
`bub/src/bub/builtin/agent.py:521-561`
```python
async def _run_once(
    self,
    *,
    tape: Tape,
    prompt: str | list[dict],
    model: str | None = None,
    allowed_tools: Collection[str] | None = None,
    allowed_skills: Collection[str] | None = None,
    stream_output: bool = False,
) -> AsyncStreamEvents | ToolAutoResult:
    prompt_text = prompt if isinstance(prompt, str) else _extract_text_from_parts(prompt)
    if allowed_tools is not None:
        allowed_tools = {name.casefold() for name in allowed_tools}
    if allowed_skills is not None:
        allowed_skills = {name.casefold() for name in allowed_skills}
        tape.context.state["allowed_skills"] = list(allowed_skills)
    if allowed_tools is not None:
        tools = [tool for tool in REGISTRY.values() if tool.name.casefold() in allowed_tools]
    else:
        tools = list(REGISTRY.values())
    async with asyncio.timeout(self.settings.model_timeout_seconds):
        if stream_output:
            return await tape.stream_events_async(
                prompt=prompt,
                system_prompt=self._system_prompt(
                    prompt_text, state=tape.context.state, allowed_skills=allowed_skills
                ),
                max_tokens=self.settings.max_tokens,
                tools=model_tools(tools),
                model=model,
            )
        else:
            return await tape.run_tools_async(
                prompt=prompt,
                system_prompt=self._system_prompt(
                    prompt_text, state=tape.context.state, allowed_skills=allowed_skills
                ),
                max_tokens=self.settings.max_tokens,
                tools=model_tools(tools),
                model=model,
            )
```

### Fact 6: Text Extraction Function
`bub/src/bub/builtin/agent.py:655-657`
```python
def _extract_text_from_parts(parts: list[dict]) -> str:
    """Extract text content from multimodal content parts."""
    return "\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
```

### Fact 7: Framework-Level Prompt Passing
`bub/src/bub/framework.py:105-144`
```python
async def process_inbound(self, inbound: Envelope, stream_output: bool = False) -> TurnResult:
    session_id = await self._hook_runtime.call_first("resolve_session", message=inbound)
    state = {"_runtime_workspace": str(self.workspace)}
    for hook_state in reversed(await self._hook_runtime.call_many("load_state", ...)):
        if isinstance(hook_state, dict):
            state.update(hook_state)
    prompt = await self._hook_runtime.call_first(
        "build_prompt", message=inbound, session_id=session_id, state=state
    )
    if not prompt:
        prompt = content_of(inbound)
    model_output = ""
    try:
        model_output = await self._run_model(inbound, prompt, session_id, state, stream_output)
    finally:
        await self._hook_runtime.call_many("save_state", ...)
```

`bub/src/bub/framework.py:149`
```python
async def _run_model(
    self,
    inbound: Envelope,
    prompt: str | list[dict],
    session_id: str,
    state: dict[str, Any],
    stream_output: bool,
) -> str:
```

### Fact 8: Subagent Tool Propagates Multimodal Prompts
`bub/src/bub/builtin/tools.py:51-68`
```python
class SubAgentInput(BaseModel):
    prompt: str | list[dict] = Field(
        ..., description="The initial prompt for the sub-agent, either as a string or a list of message parts."
    )

@tool(name="subagent", context=True, model=SubAgentInput)
async def run_subagent(param: SubAgentInput, *, context: ToolContext) -> str:
    agent = _get_agent(context)
    # ...
    async for event in await agent.run_stream(
        session_id=subagent_session,
        prompt=param.prompt,
        state=state,
        model=param.model,
        allowed_tools=allowed_tools,
        allowed_skills=param.allowed_skills,
    ):
        # ...
```

### Fact 9: Tape Store Redacts Non-Text Parts
`bub/src/bub/builtin/store.py:80-95`
```python
@staticmethod
def _redact_prompt(prompt: list[dict]) -> Any:
    if not isinstance(prompt, list):
        return prompt
    new_prompt = []
    for part in prompt:
        if part.get("type") == "text":
            new_prompt.append(part)
    return new_prompt
```

### Fact 10: Hook Runtime Delegation Preserves Type
`bub/src/bub/hook_runtime.py:163-192`
```python
async def run_model(self, prompt: str | list[dict], session_id: str, state: dict[str, Any]) -> str | None:
    for _, plugin in reversed(self._plugin_manager.list_name_plugin()):
        if hasattr(plugin, "run_model"):
            output = await self.call_first("run_model", prompt=prompt, session_id=session_id, state=state)
            return cast(str, output)
        elif hasattr(plugin, "run_model_stream"):
            stream = await self.call_first("run_model_stream", prompt=prompt, session_id=session_id, state=state)
            text = ""
            async for event in stream:
                if event.kind == "text":
                    text += str(event.data.get("delta", ""))
            return text
    return None
```

---

## Claims

### Claim 1: list[dict] is the OpenAI Multimodal Message Format
**Status:** ✅ VALIDATED (2026-04-30)
**Reasoning:** The `build_prompt` hook constructs `list[dict]` only when media attachments are present. Each dict has a `"type"` field with values `"text"` or `"image_url"`, matching the OpenAI Chat Completions API content format for vision models. When no media is present, a plain `str` is returned for backward compatibility.

**References:** Fact 2, Fact 6

### Claim 2: The Prompt Type is Preserved Throughout the Entire Pipeline
**Status:** ✅ VALIDATED (2026-04-30)
**Reasoning:** From `build_prompt` through `framework.process_inbound`, `_run_model`, `hook_runtime.run_model`, `builtin_hook_impl.run_model`, to `Agent.run`/`run_stream`, and finally to `Agent._agent_loop` and `_run_once`, the `prompt` parameter consistently maintains the `str | list[dict]` union type. No layer forces normalization to string.

**References:** Fact 1, Fact 3, Fact 4, Fact 7, Fact 10

### Claim 3: Text Extraction Happens Only for System Prompt Generation
**Status:** ✅ VALIDATED (2026-04-30)
**Reasoning:** In `_run_once`, the code extracts text from `list[dict]` via `_extract_text_from_parts` to pass to `_system_prompt`, which needs plain text for skill hint matching and tool rendering. However, the original `prompt` (whether `str` or `list[dict]`) is passed unchanged to `tape.run_tools_async` or `tape.stream_events_async`, preserving multimodal content for the LLM API.

**References:** Fact 5, Fact 6

### Claim 4: Subagents Inherit Full Multimodal Prompt Capability
**Status:** ✅ VALIDATED (2026-04-30)
**Reasoning:** The `subagent` tool accepts `str | list[dict]` in its Pydantic model and forwards it directly to `Agent.run_stream`. This means a parent agent can dispatch a multimodal prompt (including images) to a subagent without losing media context.

**References:** Fact 8

### Claim 5: Non-Text Media Parts are Redacted from Tape Storage
**Status:** ✅ VALIDATED (2026-04-30)
**Reasoning:** The `ForkTapeStore._redact_prompt` method strips all non-`"text"` parts from `list[dict]` prompts before storage. This suggests images and other media are intentionally excluded from tape persistence, likely to save space or avoid storing large base64 data.

**References:** Fact 9

### Claim 6: The Framework Uses Type Safety for Backward Compatibility
**Status:** ✅ VALIDATED (2026-04-30)
**Reasoning:** By declaring `str | list[dict]` at every interface point and using `isinstance(prompt, str)` checks (e.g., in `_run_once` and `_run_command`), the framework gracefully handles both legacy string prompts and modern multimodal prompts without breaking existing code paths or plugins.

**References:** Fact 3, Fact 5, Fact 7

---

## Validation Log

**Date:** 2026-04-30
**Validator:** Subagent (read REFERENCE.md first)
**Method:** Verified each claim against cited source code locations

| Claim | Status | Notes |
|-------|--------|-------|
| Claim 1 | ✅ Yes | OpenAI format confirmed at hook_impl.py:131-157 |
| Claim 2 | ✅ Yes | Type preserved through all layers, no normalization |
| Claim 3 | ✅ Yes | Extraction only for _system_prompt(), original passed to LLM |
| Claim 4 | ✅ Yes | SubAgentInput.prompt typed str \| list[dict], forwarded directly |
| Claim 5 | ✅ Yes | _redact_prompt strips non-text parts at store.py:80-95 |
| Claim 6 | ✅ Yes | isinstance checks at agent.py:92,135,531 for backward compat |

**Phase 3 (Merge):** N/A — This is a master file (no session file to merge).

---

## Summary

The `list[dict]` type in Bub's prompt passing represents **OpenAI-style multimodal message parts**. It is:

- **Constructed** in `build_prompt` when media (images) are attached to messages
- **Preserved** through the entire framework pipeline from inbound processing to LLM invocation
- **Extracted** to plain text only for system prompt generation (skill/tool matching)
- **Forwarded intact** to the underlying LLM API via republic's tape system
- **Redacted** during tape storage to keep only text parts
- **Inherited** by subagents, enabling multimodal delegation

This design maintains backward compatibility with plain string prompts while supporting vision/multimodal models through a unified `str | list[dict]` type signature.
