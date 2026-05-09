# Vendor Reasoning Content Field Behavior

**Date:** 2026-05-07
**Subagent:** S1 — DeepSeek + OpenAI Explorer
**Parent:** `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md`

---

## Notes

### Note 1: Scope and Dimensions

This exploration investigates how DeepSeek and OpenAI define the behavior of reasoning content fields in their chat completion APIs across 7 dimensions:

1. Field Name & Location
2. Response Format (non-streaming)
3. Streaming Format
4. Request Format (history playback)
5. Tool Call Coexistence
6. Model Gating
7. Special Rules

### Note 2: Critical Difference Between Vendors

DeepSeek and OpenAI have fundamentally different approaches to reasoning content exposure:

- **DeepSeek** exposes `reasoning_content` as a plain text field in the Chat Completions API response. It can coexist with `content` and `tool_calls` in the same message.
- **OpenAI** does NOT expose reasoning content in the Chat Completions API. Reasoning is discarded after each request. The Responses API provides reasoning items via a separate mechanism (encrypted content with item IDs).

This difference has significant implications for tape entry design in Bub/Republic.

### Note 3: Open Questions

1. Does OpenAI's Chat Completions API ever return `reasoning_content` for any model (e.g., via a beta flag or undocumented parameter)? Evidence suggests no, but third-party providers (like vLLM, Azure) may add it.
2. For DeepSeek, does `reasoning_content` appear in the `assistant` message when sent as request history, or is it only valid in the response? Docs say it can be passed back but is ignored for non-tool-call turns.
3. For OpenAI Responses API, what is the exact shape of reasoning items when included in the `input` array for subsequent turns?

---

## Facts

### DeepSeek

#### Fact 1: Field name is `reasoning_content` at top-level of message object

From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md` (source: https://api-docs.deepseek.com/api/create-chat-completion):

```
message.reasoning_content: string | null
"For thinking mode only. The reasoning contents of the assistant message, before the final answer."
```

#### Fact 2: Non-streaming response shape includes `reasoning_content` alongside `content` and `tool_calls`

From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:

```json
{
  "message": {
    "content": "Hello! How can I help you today?",
    "reasoning_content": "The user greeted me...",
    "tool_calls": [...],
    "role": "assistant"
  }
}
```

#### Fact 3: Streaming delivers `reasoning_content` in `delta` object

From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:

```
delta.reasoning_content: string | null
"For thinking mode only. The reasoning contents of the assistant message, before the final answer."
```

Example SSE:
```
data: {"choices": [{"delta": {"reasoning_content": "Let me think...", "role": "assistant"}, ...}]}
```

#### Fact 4: For non-tool-call turns, `reasoning_content` can be passed back but is ignored

From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md` (source: https://api-docs.deepseek.com/guides/thinking_mode):

> "Between two `user` messages, if the model **did not perform a tool call**, the intermediate assistant's `reasoning_content` does not need to participate in the context concatenation. If passed to the API in subsequent turns, it will be ignored."

#### Fact 5: For tool-call turns, `reasoning_content` MUST be passed back or API returns 400

From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md`:

> "Unlike turns in thinking mode that do not involve tool calls, for turns that do perform tool calls, the `reasoning_content` must be fully passed back to the API in all subsequent requests. If your code does not correctly pass back `reasoning_content`, the API will return a 400 error."

#### Fact 6: A single assistant message can contain `content`, `reasoning_content`, and `tool_calls` simultaneously

From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md`, sample output:

```
Turn 1.1
reasoning_content="The user is asking about the weather in Hangzhou tomorrow. I need to get tomorrow's date first, then call the weather function."
content="Let me check tomorrow's weather in Hangzhou for you. First, let me get tomorrow's date."
tool_calls=[ChatCompletionMessageFunctionToolCall(id='call_00_kw66qNnNto11bSfJVIdlV5Oo', function=Function(arguments='{}', name='get_date'), type='function', index=0)]
```

This shows `content` is non-empty while `tool_calls` is present and `reasoning_content` is present.

#### Fact 7: Both `deepseek-v4-flash` and `deepseek-v4-pro` support thinking mode

From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:

```
model: string, required
Possible values: ["deepseek-v4-flash", "deepseek-v4-pro"]
```

Both models support the `thinking` parameter.

#### Fact 8: `thinking` parameter controls mode; `reasoning_effort` controls depth

From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:

```
thinking.type: "enabled" | "disabled", default "enabled"
reasoning_effort: "high" | "max"
```

For compatibility: `low` and `medium` are mapped to `high`, `xhigh` is mapped to `max`.

#### Fact 9: Usage reports reasoning tokens separately

From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:

```json
{
  "usage": {
    "completion_tokens": 0,
    "completion_tokens_details": {
      "reasoning_tokens": 0
    }
  }
}
```

#### Fact 10: `reasoning_content` from tool-calling turns persists across all future turns, including new user questions

From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md`:

> "Additionally, in the Turn 2 request, we still pass the `reasoning_content` generated in Turn 1 to the API."

This means even when the user asks a completely new question (Turn 2), the `reasoning_content` from the tool-calling Turn 1 must remain in the message history.

---

### OpenAI

#### Fact 11: OpenAI Chat Completions API has NO `reasoning_content` field

From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md`:

OpenAI SDK `ChatCompletionMessage` class (`/home/liu/Documents/systemf/.venv/lib/python3.14/site-packages/openai/types/chat/chat_completion_message.py`):
```python
class ChatCompletionMessage(BaseModel):
    content: Optional[str] = None
    refusal: Optional[str] = None
    role: Literal["assistant"]
    annotations: Optional[List[Annotation]] = None
    audio: Optional[ChatCompletionAudio] = None
    function_call: Optional[FunctionCall] = None
    tool_calls: Optional[List[ChatCompletionMessageToolCallUnion]] = None
```

No `reasoning_content` field exists.

#### Fact 12: OpenAI Chat Completions API discards reasoning after every request

From `analysis/vendor_reasoning_content/raw/openai_api_docs.md` (source: https://community.openai.com/t/chat-completion-api-with-reasoning-models/1281778):

> "In the Chat Completions API, the model's reasoning is discarded after every API request. It is only possible to retain reasoning items in context using the stateful Responses API, with the `store` parameter set to `true`."

This is an official OpenAI staff response.

#### Fact 13: OpenAI streaming delta also has no `reasoning_content` field

From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md`:

OpenAI SDK `ChoiceDelta` class (`/home/liu/Documents/systemf/.venv/lib/python3.14/site-packages/openai/types/chat/chat_completion_chunk.py`):
```python
class ChoiceDelta(BaseModel):
    content: Optional[str] = None
    function_call: Optional[ChoiceDeltaFunctionCall] = None
    refusal: Optional[str] = None
    role: Optional[Literal["developer", "system", "user", "assistant", "tool"]] = None
    tool_calls: Optional[List[ChoiceDeltaToolCall]] = None
```

No `reasoning_content` field.

#### Fact 14: any-llm-sdk extends OpenAI types with `reasoning` field because official SDK lacks it

From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (`any_llm/types/completion.py:28-36`):

```python
# OpenAI Completion API doesn't include reasoning information, so we need to extend the openai type

class Reasoning(BaseModel):
    content: str

class ChatCompletionMessage(OpenAIChatCompletionMessage):
    reasoning: Reasoning | None = None
```

And for streaming (`any_llm/types/completion.py:63-64`):
```python
class ChoiceDelta(OpenAIChoiceDelta):
    reasoning: Reasoning | None = None
```

#### Fact 15: OpenAI Responses API uses `reasoning` items with IDs for stateful persistence

From `analysis/vendor_reasoning_content/raw/openai_api_docs.md` (source: https://developers.openai.com/cookbook/examples/responses_api/reasoning_items):

> "Because the Responses API is stateful, these reasoning tokens persist: just include their IDs in subsequent messages to give future responses access to the same reasoning items."

> "If a turn includes a function call (which may require an extra round trip outside the API), you do need to include the reasoning items—either via `previous_response_id` or by explicitly adding the reasoning item to `input`."

#### Fact 16: For Responses API function calling, reasoning items must be passed back

From `analysis/vendor_reasoning_content/raw/openai_api_docs.md` (source: https://developers.openai.com/api/docs/guides/reasoning):

> "When doing function calling with a reasoning model in the Responses API, we highly recommend you pass back any reasoning items returned with the last function call (in addition to the output of your function)."

#### Fact 17: Republic maps `reasoning_effort` to `reasoning.effort` for Responses API

From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (`republic/src/republic/core/execution.py:412-420`):

```python
@staticmethod
def _with_responses_reasoning(
    kwargs: dict[str, Any],
    reasoning_effort: Any | None,
) -> dict[str, Any]:
    if reasoning_effort is None:
        return kwargs
    if "reasoning" in kwargs:
        return kwargs
    return {**kwargs, "reasoning": {"effort": reasoning_effort}}
```

#### Fact 18: `reasoning_effort` parameter values vary by model

From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (`openai/types/shared_params/reasoning.py`):

- `gpt-5.1` defaults to `none` (no reasoning by default)
- Models before `gpt-5.1` default to `medium`
- `gpt-5-pro` defaults to `high`
- Supported values: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`

#### Fact 19: OpenAI Codex transport requests `reasoning.encrypted_content`

From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (`republic/src/republic/clients/openai_codex.py:15`):

```python
DEFAULT_CODEX_INCLUDE = ("reasoning.encrypted_content",)
```

This shows OpenAI's Responses API can return encrypted reasoning content when explicitly requested.

#### Fact 20: Republic treats `reasoning` items as metadata-only in Responses API

From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (`republic/src/republic/clients/chat.py:32`):

```python
RESPONSES_METADATA_ONLY_ITEM_TYPES = frozenset({"reasoning", "compaction"})
```

---

## Claims

### Claim 1: DeepSeek and OpenAI have incompatible reasoning content models

**Reasoning:** DeepSeek exposes `reasoning_content` as a plain string field in the Chat Completions API response, on the same message object as `content` and `tool_calls` (Fact 1, Fact 2, Fact 6). OpenAI's Chat Completions API does not expose reasoning content at all — it is discarded after each request (Fact 11, Fact 12). OpenAI only exposes reasoning through the Responses API using stateful reasoning items with IDs (Fact 15). This means a unified tape format cannot simply store a `reasoning_content` string and expect it to work for both vendors.

**References:** Fact 1, Fact 2, Fact 6, Fact 11, Fact 12, Fact 15

### Claim 2: DeepSeek requires conditional preservation of reasoning_content in message history

**Reasoning:** For non-tool-call turns, DeepSeek ignores `reasoning_content` when passed back in the message history (Fact 4). For tool-call turns, omitting `reasoning_content` causes a 400 error (Fact 5). Furthermore, reasoning content from tool-calling turns must persist across ALL future turns, even unrelated user questions (Fact 10). This means any message reconstruction logic must distinguish between tool-calling and non-tool-calling assistant messages and conditionally include or strip `reasoning_content`.

**References:** Fact 4, Fact 5, Fact 10

### Claim 3: OpenAI's Chat Completions API cannot preserve reasoning across turns

**Reasoning:** The official OpenAI Chat Completions API discards reasoning after every request (Fact 12). There is no `reasoning_content` field in either the non-streaming message type or the streaming delta type (Fact 11, Fact 13). The any-llm-sdk extends these types with a `reasoning` field specifically to support other providers like DeepSeek (Fact 14). For OpenAI models, reasoning preservation requires migrating to the Responses API, which uses a completely different mechanism (reasoning items with IDs, stateful conversations via `previous_response_id` or explicit input items) (Fact 15, Fact 16).

**References:** Fact 11, Fact 12, Fact 13, Fact 14, Fact 15, Fact 16

### Claim 4: Tool call coexistence with reasoning differs between vendors

**Reasoning:** DeepSeek allows a single assistant message to contain `content`, `reasoning_content`, and `tool_calls` simultaneously (Fact 6). The sample output shows non-empty `content` alongside `tool_calls` and `reasoning_content`. For OpenAI Chat Completions API, an assistant message typically has either `content` OR `tool_calls`, with `content` being null when `tool_calls` are present. OpenAI's Responses API can return both `message` and `function_call` output items in the same response, but they are separate items in an output array, not fields on a single message object.

**References:** Fact 6, Fact 11, `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#Fact 4`

### Claim 5: Republic's current architecture is designed for OpenAI's Responses API reasoning model, not Chat Completions reasoning

**Reasoning:** Republic maps `reasoning_effort` to `reasoning.effort` for the Responses API (Fact 17). It treats `reasoning` items as metadata-only (Fact 20). It does not have any logic for handling `reasoning_content` in Chat Completions messages because OpenAI's Chat Completions API does not expose it. The any-llm-sdk extends OpenAI types with a `reasoning` field, but this is for third-party provider compatibility (Fact 14). To support DeepSeek's `reasoning_content` model, Republic/Bub would need new logic in message reconstruction (e.g., `_select_messages`) to conditionally include `reasoning_content` based on whether the turn had tool calls.

**References:** Fact 14, Fact 17, Fact 20, `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#Implication for Reasoning Content Storage`

---

## Open Questions

1. **OpenAI Chat Completions undocumented behavior:** Is there any undocumented parameter or beta feature that causes OpenAI's Chat Completions API to return `reasoning_content`? Evidence from SDK types, official docs, and community forums all say no, but this could change.

2. **DeepSeek request validation:** Does DeepSeek validate the `reasoning_content` field when it appears in an assistant message in the request? The docs say it is "ignored" for non-tool-call turns, but it is unclear if invalid values cause errors.

3. **OpenAI Responses API reasoning item shape:** What is the exact JSON shape of a reasoning item when explicitly added to the `input` array in a Responses API request? The docs reference `previous_response_id` and `input` items but do not show the full shape.

4. **DeepSeek streaming ordering:** In streaming mode, do `reasoning_content` deltas always appear before `content` deltas, or can they be interleaved? The docs imply reasoning comes "before the final answer" but do not specify chunk-level ordering guarantees.

5. **Azure OpenAI reasoning:** Does Azure OpenAI's Chat Completions API expose `reasoning_content` for DeepSeek models or other reasoning models deployed via Azure? This is a deployment-specific question.
