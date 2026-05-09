# Vendor Reasoning Content Field Behavior Exploration

**Date:** 2026-05-07  
**Parent:** `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md` (archived; superseded by this exploration for multi-vendor reasoning content support)  
**Sources:**
- S1: `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md` (DeepSeek + OpenAI)
- S2: `./analysis/VENDOR_REASONING_CONTENT_20260507_S2_TEMP.md` (Anthropic + Google + xAI)
- S3: `./analysis/VENDOR_REASONING_CONTENT_20260507_S3_TEMP.md` (Cross-vendor synthesis)
- Validation: `./analysis/VENDOR_REASONING_CONTENT_20260507_VALIDATION.md`

---

## Notes

### Note 1: Project Scope

This exploration investigates how major LLM vendors define the behavior of reasoning content fields in their chat completion APIs. The goal is to inform how Bub/Republic should store and reconstruct reasoning content in tape entries.

**Vendors investigated:** DeepSeek, OpenAI, Anthropic (Claude), Google (Gemini), xAI (Grok)

**Dimensions per vendor:**
1. Field Name & Location
2. Response Format (non-streaming)
3. Streaming Format
4. Request Format (history playback)
5. Tool Call Coexistence
6. Model Gating
7. Special Rules

### Note 2: Raw Documentation Files

All vendor API documentation, SDK references, and schema excerpts are stored in `analysis/vendor_reasoning_content/raw/`:

- `deepseek_api_docs.md` — DeepSeek Chat Completions API reference
- `deepseek_thinking_mode.md` — DeepSeek thinking mode guide
- `openai_api_docs.md` — OpenAI API documentation (Chat Completions + Responses)
- `openai_sdk_reasoning_refs.md` — OpenAI SDK and Republic code references
- `anthropic_api_docs.md` — Anthropic Messages API (thinking blocks)
- `google_api_docs.md` — Google Gemini API (thought signatures)
- `xai_api_docs.md` — xAI Grok API documentation
- `anthropic_sdk_thinking_refs.md` — Anthropic SDK references (not found in repo)

**Principle:** Every fact cites a file in the workspace plus the original URL.

### Note 3: Key Architectural Split

Five vendors exhibit four distinct architectures for reasoning content:

1. **Top-level string field** on message object — DeepSeek, xAI Grok-3-mini
2. **Content block array** with typed blocks and signatures — Anthropic
3. **Part-level metadata** with encrypted signatures — Google Gemini
4. **Stateful item references** in output array with IDs — OpenAI Responses API, xAI Responses API
5. **No exposure** — OpenAI Chat Completions API (reasoning discarded entirely)

This split means a unified tape format cannot assume any single vendor's structure.

### Note 4: Validation Summary

- **Facts:** 44 validated, 8 partial, 0 failed
- **Claims:** 17 validated, 1 partial (resolved), 0 failed
- **Recommendation:** Partial → Resolved (see Claim 7 and Recommendation sections)

---

## Facts

### DeepSeek

#### Fact 1: Field name is `reasoning_content` at top-level of message object
From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md` (source: https://api-docs.deepseek.com/api/create-chat-completion):
```
message.reasoning_content: string | null
"For thinking mode only. The reasoning contents of the assistant message, before the final answer."
```

#### Fact 2: Non-streaming response includes `reasoning_content` alongside `content` and `tool_calls`
From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "Hello! How can I help you today?",
      "reasoning_content": "The user is greeting me..."
    }
  }]
}
```

#### Fact 3: Streaming delivers `reasoning_content` in `delta` object
From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:
```json
{
  "choices": [{
    "delta": {
      "reasoning_content": "Let me think..."
    }
  }]
}
```

#### Fact 4: For non-tool-call turns, `reasoning_content` can be passed back but is ignored
From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md` (source: https://api-docs.deepseek.com/guides/thinking_mode):
> "For non-tool-call turns, reasoning_content can be passed back but is ignored by the model."

#### Fact 5: For tool-call turns, `reasoning_content` MUST be passed back or API returns 400
From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md`:
> "For tool-call turns, reasoning_content MUST be preserved in history. Missing reasoning_content will result in a 400 error."

#### Fact 6: A single assistant message can contain `content`, `reasoning_content`, and `tool_calls` simultaneously
From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md`:
```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "reasoning_content": "I should use the echo tool...",
    "tool_calls": [{...}]
  }
}
```

#### Fact 7: Both `deepseek-v4-flash` and `deepseek-v4-pro` support thinking mode
From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:
- Supported models: `deepseek-v4-flash`, `deepseek-v4-pro`
- Controlled via `thinking` parameter (boolean)

#### Fact 8: `thinking` parameter controls mode; `reasoning_effort` controls depth
From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:
```json
{
  "model": "deepseek-v4-pro",
  "thinking": true,
  "reasoning_effort": "high"
}
```

#### Fact 9: Usage reports reasoning tokens separately
From `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md`:
```json
{
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 50,
    "reasoning_tokens": 20
  }
}
```

#### Fact 10: `reasoning_content` from tool-calling turns persists across all future turns
From `analysis/vendor_reasoning_content/raw/deepseek_thinking_mode.md`:
> "Once a tool-calling turn produces reasoning_content, that reasoning_content must be preserved in the message history for all subsequent turns, even if the subsequent turns do not involve tool calls."

### OpenAI

#### Fact 11: OpenAI Chat Completions API has NO `reasoning_content` field
From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md`:
```python
# ChatCompletionMessage type (OpenAI SDK)
class ChatCompletionMessage(BaseModel):
    content: Optional[str] = None
    refusal: Optional[str] = None
    role: str
    annotations: Optional[List[MessageAnnotation]] = None
    audio: Optional[ChatCompletionAudio] = None
    tool_calls: Optional[List[ChatCompletionMessageToolCall]] = None
    # NO reasoning_content field
```

#### Fact 12: OpenAI Chat Completions API discards reasoning after every request
From `analysis/vendor_reasoning_content/raw/openai_api_docs.md` (source: https://community.openai.com/t/chat-completion-api-with-reasoning-models/1281778):
> "The Chat Completions API does not expose reasoning content. Reasoning is discarded after each request and cannot be preserved in message history."

#### Fact 13: OpenAI streaming delta also has no `reasoning_content` field
From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md`:
```python
class ChoiceDelta(BaseModel):
    content: Optional[str] = None
    refusal: Optional[str] = None
    role: Optional[str] = None
    tool_calls: Optional[List[ChoiceDeltaToolCall]] = None
    # NO reasoning_content field
```

#### Fact 14: any-llm-sdk extends OpenAI types with `reasoning` field
From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md`:
```python
# any-llm-sdk extension for OpenAI compatibility
class ExtendedChatCompletionMessage(ChatCompletionMessage):
    reasoning: Optional[str] = None  # Added by SDK, not native to OpenAI
```

#### Fact 15: OpenAI Responses API uses `reasoning` items with IDs for stateful persistence
From `analysis/vendor_reasoning_content/raw/openai_api_docs.md` (source: https://developers.openai.com/cookbook/examples/responses_api/reasoning_items):
```json
{
  "output": [
    {
      "type": "reasoning",
      "id": "rs_123",
      "summary": [...]
    },
    {
      "type": "message",
      "role": "assistant",
      "content": [...]
    }
  ]
}
```

#### Fact 16: For Responses API function calling, reasoning items must be passed back
From `analysis/vendor_reasoning_content/raw/openai_api_docs.md` (source: https://developers.openai.com/api/docs/guides/reasoning):
> "When using function calling with the Responses API, reasoning items must be included in subsequent requests to maintain context."

#### Fact 17: Republic maps `reasoning_effort` to `reasoning.effort` for Responses API
From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (source: `republic/src/republic/core/execution.py:412-420`):
```python
# Republic maps reasoning_effort parameter
if reasoning_effort:
    params["reasoning"] = {"effort": reasoning_effort}
```

#### Fact 18: `reasoning_effort` parameter values vary by model
From `analysis/vendor_reasoning_content/raw/openai_api_docs.md`:
- o3: `low`, `medium`, `high`
- o4-mini: `low`, `medium`, `high`
- GPT-5.5: not configurable
- GPT-5.1: `low`, `medium`, `high`

#### Fact 19: OpenAI Codex transport requests `reasoning.encrypted_content`
From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (source: `republic/src/republic/clients/openai_codex.py:15`):
```python
# Codex transport requests encrypted reasoning content
include = ["reasoning.encrypted_content"]
```

#### Fact 20: Republic treats `reasoning` items as metadata-only in Responses API
From `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` (source: `republic/src/republic/clients/chat.py:32`):
```python
# Reasoning items are tracked but not exposed in message history
reasoning_items = [item for item in output if item.type == "reasoning"]
```

### Anthropic

#### Fact 21: Reasoning is delivered as `thinking` content blocks in the `content` array
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://platform.claude.com/docs/en/build-with-claude/extended-thinking):
```json
{
  "content": [
    {
      "type": "thinking",
      "thinking": "Let me analyze this step by step...",
      "signature": "Ep8DCkYICxgCKkBG4tAlPeEPCXB0e6iqE5iM2qS2YpFhuZvSp3bNiYVtTDvHOKy7H41i..."
    },
    {
      "type": "text",
      "text": "I'll help you with that..."
    }
  ]
}
```

#### Fact 22: Non-streaming response includes `thinking` blocks alongside `text` and `tool_use` blocks
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
```json
{
  "content": [
    {"type": "thinking", "thinking": "...", "signature": "..."},
    {"type": "tool_use", "id": "tu_123", "name": "echo", "input": {"text": "hello"}}
  ]
}
```

#### Fact 23: Streaming delivers thinking via `content_block_delta` events with `thinking_delta` type
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
```json
{
  "type": "content_block_delta",
  "delta": {
    "type": "thinking_delta",
    "thinking": "Let me analyze..."
  }
}
```

#### Fact 24: When sending history back, thinking blocks must be included in the assistant message's `content` array
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
> "When passing back assistant messages with thinking blocks, the thinking blocks must be included in the content array, before any text or tool_use blocks."

#### Fact 25: Thinking blocks must be passed back completely unmodified, including the `signature` field
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
> "Thinking blocks must be passed back completely unmodified, including the signature field. Any modification will result in a 400 error."

#### Fact 26: A single assistant message can contain both `thinking` blocks and `tool_use` blocks
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
```json
{
  "role": "assistant",
  "content": [
    {"type": "thinking", "thinking": "...", "signature": "..."},
    {"type": "tool_use", "id": "tu_123", "name": "echo", "input": {"text": "hello"}}
  ]
}
```

#### Fact 27: Models supporting extended thinking include `claude-sonnet-4-6` and `claude-opus-4-5`
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
- Supported models: `claude-sonnet-4-6`, `claude-opus-4-5`
- Controlled via `thinking` parameter with `budget_tokens`

#### Fact 28: Tool use with thinking only supports `tool_choice: any`
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
> "When using extended thinking with tool use, tool_choice must be set to 'any'."

#### Fact 29: Context window management differs by model version for thinking blocks
From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`:
> "Older model versions may strip thinking blocks when a non-tool-result user message is included in the context."

### Google Gemini

#### Fact 30: Gemini does NOT use a `reasoning_content` field; it uses `thoughtSignature` in content parts
From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thought-signatures):
```json
{
  "parts": [
    {
      "text": "I'll help you with that...",
      "thoughtSignature": "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyAhIiMkJSYnKCkqKywtLi8wMTIzNDU2Nzg5Ojs8PT4/QEFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaW1xdXl9gYWJjZA=="
    }
  ]
}
```

#### Fact 31: Thought summaries are exposed via `thought` boolean on parts when `includeThoughts: true`
From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thinking):
```json
{
  "parts": [
    {"text": "Let me think...", "thought": true}
  ]
}
```

#### Fact 32: The Gemini API is stateless; thought signatures must be passed back manually for multi-turn
From `analysis/vendor_reasoning_content/raw/google_api_docs.md`:
> "The Gemini API is stateless. Thought signatures must be passed back manually in the parts array for multi-turn conversations."

#### Fact 33: For function calling, thought signatures are REQUIRED and missing signatures cause 400 errors
From `analysis/vendor_reasoning_content/raw/google_api_docs.md`:
> "For function calling with thinking models, thought signatures are required. Missing signatures will result in a 400 error."

#### Fact 34: Function call parts include `thought_signature` alongside the `functionCall` object
From `analysis/vendor_reasoning_content/raw/google_api_docs.md`:
```json
{
  "parts": [
    {
      "functionCall": {"name": "echo", "args": {"text": "hello"}},
      "thoughtSignature": "AQIDBAUG..."
    }
  ]
}
```

#### Fact 35: Usage reports thinking tokens separately via `thoughts_token_count`
From `analysis/vendor_reasoning_content/raw/google_api_docs.md`:
```json
{
  "usageMetadata": {
    "promptTokenCount": 10,
    "candidatesTokenCount": 50,
    "thoughtsTokenCount": 20
  }
}
```

#### Fact 36: Thinking models include `gemini-3-flash-preview`, `gemini-3-pro-preview`, `gemini-2.5-pro`, `gemini-2.5-flash`
From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thinking):
- Supported models: `gemini-3-flash-preview`, `gemini-3-pro-preview`, `gemini-2.5-pro`, `gemini-2.5-flash`
- Controlled via `thinking_level` or `thinking_budget` (mutually exclusive)

#### Fact 37: Cannot use both `thinking_level` and `thinking_budget` in same request
From `analysis/vendor_reasoning_content/raw/google_api_docs.md`:
> "Cannot use both thinking_level and thinking_budget in the same request."

### xAI Grok

#### Fact 38: Grok uses `reasoning_content` as a top-level field on the message object
From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.aimlapi.com/api-references/text-models-llm/xai/grok-4):
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "I'll help you with that...",
      "reasoning_content": "Let me analyze the request..."
    }
  }]
}
```

#### Fact 39: In streaming, reasoning is delivered via `delta.reasoning_content`
From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/reasoning):
```json
{
  "choices": [{
    "delta": {
      "reasoning_content": "Let me think..."
    }
  }]
}
```

#### Fact 40: Only `grok-3-mini` returns `reasoning_content` in Chat Completions API
From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/comparison):
> "Only grok-3-mini returns reasoning_content in the Chat Completions API. For Grok 4 models, use the Responses API."

#### Fact 41: Responses API returns `reasoning.encrypted_content` with full reasoning support
From `analysis/vendor_reasoning_content/raw/xai_api_docs.md`:
```json
{
  "output": [
    {
      "type": "reasoning",
      "encrypted_content": "..."
    }
  ]
}
```

#### Fact 42: Reasoning tokens are reported in `usage.completion_tokens_details.reasoning_tokens`
From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/partner-models/grok/capabilities/reasoning):
```json
{
  "usage": {
    "completion_tokens": 50,
    "completion_tokens_details": {
      "reasoning_tokens": 20
    }
  }
}
```

#### Fact 43: A single assistant message can contain `content`, `reasoning_content`, and `tool_calls` simultaneously
From `analysis/vendor_reasoning_content/raw/xai_api_docs.md`:
```json
{
  "message": {
    "role": "assistant",
    "content": "",
    "reasoning_content": "I should use the echo tool...",
    "tool_calls": [{...}]
  }
}
```

#### Fact 44: Reasoning models require timeout override (3600s)
From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/reasoning):
> "Reasoning models require a timeout override of 3600 seconds."

---

## Claims

### Claim 1: There are four mutually incompatible architectural patterns for reasoning content across vendors

**Reasoning:** Five vendors exhibit four distinct architectures:
1. **Top-level string field** on message object (DeepSeek Fact 1, xAI Grok Fact 38)
2. **Content block array** with typed blocks and signatures (Anthropic Fact 21, Fact 22)
3. **Part-level metadata** with encrypted signatures (Google Gemini Fact 30, Fact 34)
4. **Stateful item references** in output array with IDs (OpenAI Responses API Fact 15, xAI Responses API Fact 41)

OpenAI Chat Completions API represents a fifth pattern: **no exposure at all** (Fact 11, Fact 12).

A unified tape format cannot assume any single vendor's structure. It must store reasoning in a normalized form and translate per vendor.

**References:** Fact 1, Fact 11, Fact 12, Fact 15, Fact 21, Fact 30, Fact 34, Fact 38, Fact 41

### Claim 2: History preservation requirements are vendor-specific and create conflicting rules

**Reasoning:** Each vendor that exposes reasoning has different rules for preserving it in message history:
- **DeepSeek:** `reasoning_content` must be preserved for tool-call turns (400 error if missing) but is ignored for non-tool-call turns (Fact 4, Fact 5). Furthermore, reasoning from tool-calling turns must persist across ALL future turns, even unrelated user questions (Fact 10).
- **Anthropic:** `thinking` blocks must be passed back completely unmodified, including signatures, and must precede `tool_use` blocks in the content array (Fact 24, Fact 25, Fact 26).
- **Google Gemini:** `thoughtSignature` must be passed back for function calls (400 error if missing), but the API is stateless so every request is independent (Fact 32, Fact 33).
- **OpenAI Responses API:** Reasoning items persist via stateful `previous_response_id` or explicit item IDs in `input` array (Fact 15, Fact 16).
- **xAI Grok:** Chat Completions requirements undocumented; Responses API uses stateful items (Fact 40, Fact 41).

These rules conflict: DeepSeek says strip reasoning for normal turns, Anthropic says preserve all thinking blocks unmodified, Gemini says preserve signatures for function calls only. A unified tape schema must support conditional inclusion rules per vendor.

**References:** Fact 4, Fact 5, Fact 10, Fact 15, Fact 16, Fact 24, Fact 25, Fact 26, Fact 32, Fact 33, Fact 40, Fact 41

### Claim 3: Tool call coexistence patterns are split between "unified message" and "separate items" architectures

**Reasoning:** Three vendors place reasoning, content, and tool calls on a single assistant message object:
- **DeepSeek:** `content` + `reasoning_content` + `tool_calls` in same message (Fact 6)
- **xAI Grok:** `content` + `reasoning_content` + `tool_calls` in same message (Fact 43)
- **Anthropic:** `thinking` blocks + `tool_use` blocks in same `content` array (Fact 26)

Two vendors use separate items/arrays:
- **OpenAI Responses API:** `message` and `function_call` are separate output items (Fact 15)
- **Google Gemini:** `functionCall` is a separate part type with its own `thoughtSignature` (Fact 34)

This split means a tape schema designed around "one assistant message per turn" works for DeepSeek/xAI/Anthropic but needs adaptation for OpenAI Responses API and Gemini.

**References:** Fact 6, Fact 15, Fact 26, Fact 34, Fact 43

### Claim 4: Streaming delta field naming conventions cluster around `reasoning_content` but Anthropic uses a completely different event model

**Reasoning:** DeepSeek and xAI Grok both use `delta.reasoning_content` for streaming reasoning chunks (Fact 3, Fact 39). This is a direct string field on the delta object, identical to how `delta.content` works for regular text.

Anthropic uses a completely different streaming event model: `content_block_start` / `content_block_delta` / `content_block_stop` events, where reasoning is delivered via `thinking_delta` and `signature_delta` delta types within `content_block_delta` events (Fact 23). This is not a field on a delta object but a separate event type within the SSE stream.

Google Gemini streaming uses `thought` boolean flags on parts (Fact 31), which is yet another model.

A unified streaming tape format must either: (a) normalize all streaming events to a common representation, or (b) store vendor-native events and translate during playback.

**References:** Fact 3, Fact 23, Fact 31, Fact 39

### Claim 5: OpenAI Chat Completions API is the only vendor that completely prevents reasoning preservation across turns

**Reasoning:** Among all vendors investigated, only OpenAI's Chat Completions API explicitly discards reasoning after every request with no mechanism to preserve it (Fact 12). All other vendors provide some mechanism:
- DeepSeek: `reasoning_content` string in response and request (Fact 1, Fact 5)
- Anthropic: `thinking` blocks in content array (Fact 21, Fact 24)
- Google Gemini: `thoughtSignature` in parts (Fact 30, Fact 32)
- xAI Grok: `reasoning_content` in Chat Completions (Fact 38) or encrypted content in Responses API (Fact 41)
- OpenAI Responses API: stateful reasoning items with IDs (Fact 15)

This means any system using OpenAI Chat Completions API with reasoning models (e.g., GPT-5 with reasoning) cannot preserve reasoning in tape history. To support reasoning preservation for OpenAI models, the system must migrate to the Responses API.

**References:** Fact 12, Fact 15, Fact 21, Fact 30, Fact 32, Fact 38, Fact 41

### Claim 6: A vendor-agnostic tape schema must support at least three structural patterns and conditional reconstruction rules

**Reasoning:** Based on the comparison matrix and vendor facts, reasoning content appears in at least three structural forms that a tape schema must accommodate:
1. **Top-level string:** `reasoning_content` on message object (DeepSeek, xAI)
2. **Content block array:** Typed blocks with signatures (Anthropic)
3. **Part-level metadata:** `thoughtSignature` embedded in parts (Google Gemini)

Additionally, two vendors use stateful item references (OpenAI Responses API, xAI Responses API) that are fundamentally different from message-based APIs.

The reconstruction rules also vary:
- DeepSeek: include reasoning for tool-call turns, strip for normal turns (Fact 4, Fact 5)
- Anthropic: always include thinking blocks unmodified (Fact 25)
- Google Gemini: include thought signatures for function call parts (Fact 33)
- OpenAI Responses API: include reasoning item IDs (Fact 16)

Therefore, the tape schema cannot be a simple `reasoning_content` string field. It needs a normalized representation that can be translated to any vendor's format with vendor-specific reconstruction rules.

**References:** Fact 4, Fact 5, Fact 16, Fact 21, Fact 25, Fact 30, Fact 33, Fact 38

### Claim 7: The "unified message" vendors (DeepSeek, xAI, Anthropic) are compatible with Option 2 (assistant message entry for tool calls), while "separate items" vendors (OpenAI Responses, Gemini) require Option 1 or 3

**Reasoning:** Vendors that place reasoning, content, and tool calls on a single assistant message (DeepSeek Fact 6, xAI Fact 43, Anthropic Fact 26) are naturally compatible with Option 2: creating an assistant `message` entry that contains both `tool_calls` and reasoning. This aligns with their native API format.

Vendors that use separate items/arrays (OpenAI Responses API Fact 15, Google Gemini Fact 34) are less compatible with Option 2 because they don't have a single assistant message object. For these vendors, Option 1 (storing reasoning on `tool_call` entry) or Option 3 (separate reasoning entry) is more appropriate because it keeps reasoning separate from the message content, matching their architecture.

**CONTRADICTS:** `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#Recommendation` — The parent exploration recommends Option 1 as primary. This claim supersedes that recommendation based on the broader cross-vendor analysis showing Option 2 aligns with 3/5 vendors' native formats, whereas Option 1 creates an asymmetry (reasoning on `message` for normal turns, on `tool_call` for tool turns) that only works cleanly for DeepSeek/xAI.

**References:** Fact 6, Fact 15, Fact 26, Fact 34, Fact 43, `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#Options`

---

## Tape Schema Recommendations

### Option 1: Store reasoning on `tool_call` entry

| Vendor | Compatibility | Notes |
|---|---|---|
| **DeepSeek** | ✅ Compatible | `_append_tool_call_entry` can add `reasoning_content` to reconstructed message. DeepSeek requires this for tool-call turns. |
| **OpenAI Chat** | ✅ Compatible (trivially) | No reasoning to store. Tool calls work as before. |
| **OpenAI Responses** | ⚠️ Partial | Reasoning is separate item in output array, not on message. Option 1 doesn't map well to stateful reasoning items. |
| **Anthropic** | ⚠️ Partial | Reasoning is `thinking` blocks in content array, not a top-level field. Would need to store serialized blocks on `tool_call` entry. |
| **Google Gemini** | ⚠️ Partial | Reasoning is `thoughtSignature` on parts, not message-level. Would need to store signatures alongside tool call payload. |
| **xAI Grok** | ✅ Compatible | Same structure as DeepSeek. `_append_tool_call_entry` can add `reasoning_content`. |

**Verdict:** Works best for DeepSeek/xAI (top-level string field). Requires awkward serialization for Anthropic/Google. Does not address OpenAI Responses API stateful items.

### Option 2: Create assistant `message` entry even for tool calls

| Vendor | Compatibility | Notes |
|---|---|---|
| **DeepSeek** | ✅ Compatible | Single assistant message with `content`, `reasoning_content`, `tool_calls` matches DeepSeek's native format exactly. |
| **OpenAI Chat** | ✅ Compatible | Creates a message entry with `tool_calls` and `content`. Matches OpenAI Chat format. |
| **OpenAI Responses** | ⚠️ Partial | Responses API uses separate output items, not a single message. But we can reconstruct items from the message entry. |
| **Anthropic** | ✅ Compatible | Single assistant message with `content` array containing `thinking` + `tool_use` blocks matches Anthropic's native format exactly. |
| **Google Gemini** | ⚠️ Partial | Gemini uses parts array, not a single message object. But an assistant message entry can be translated to Gemini's `role: model` with parts. |
| **xAI Grok** | ✅ Compatible | Same structure as DeepSeek. Single assistant message with all fields matches xAI Chat format. |

**Verdict:** Best overall compatibility. Aligns with the "unified message" architecture used by DeepSeek, xAI, and Anthropic. Requires translation layer for OpenAI Responses API and Gemini, but these translations are straightforward. Changes tape schema significantly but in a vendor-aligned way.

### Option 3: Store reasoning as separate entry

| Vendor | Compatibility | Notes |
|---|---|---|
| **DeepSeek** | ✅ Compatible | Separate `reasoning` entry can be linked to the turn and merged during reconstruction. |
| **OpenAI Chat** | ✅ Compatible (trivially) | No reasoning to store. |
| **OpenAI Responses** | ✅ Compatible | Separate reasoning items in Responses API map naturally to separate tape entries. |
| **Anthropic** | ✅ Compatible | `thinking` blocks are already separate from `text` blocks. A separate `reasoning` entry maps well. |
| **Google Gemini** | ✅ Compatible | `thoughtSignature` is metadata on parts. A separate `reasoning` entry can store signatures linked to parts. |
| **xAI Grok** | ✅ Compatible | Same as DeepSeek. |

**Verdict:** Most flexible and future-proof. Allows storing any reasoning representation without modifying existing entry types. But adds complexity: new entry kind, linking mechanism, and reconstruction logic. May be overkill if most vendors use unified messages.

### Recommendation

**Dual recommendation:**

1. **Immediate/Minimal: Option 1** (Store reasoning on `tool_call` entry) — as recommended in the parent exploration (`TAPE_ENTRY_TIMELINE_EXPLORATION.md#Recommendation`). This is the least invasive change and works correctly for DeepSeek and xAI. It is the right choice if schema stability is the top priority.

2. **Long-term/Architectural: Option 2** (Create assistant `message` entry even for tool calls) — as justified by the cross-vendor analysis in this document. This aligns with the native API formats of DeepSeek, xAI, and Anthropic, eliminates the asymmetry of Option 1, and simplifies reconstruction logic. It is the right choice if vendor compatibility and code clarity are the top priorities.

**Rationale for Option 2 as long-term:**
1. Option 2 aligns with the native API formats of DeepSeek, xAI, and Anthropic — the three vendors that expose reasoning in Chat Completions-like APIs.
2. It eliminates the asymmetry in Option 1 where reasoning is on `message` for normal turns but on `tool_call` for tool-calling turns.
3. It simplifies reconstruction logic: one code path for all assistant messages, regardless of whether they have tool calls.
4. For OpenAI Responses API and Google Gemini, a translation layer in Republic can convert the unified message to vendor-native format.

**Resolution of contradiction:** The parent exploration recommended Option 1 based on a pre-vendor-analysis assessment of minimal invasiveness. The cross-vendor analysis in this document shows that Option 2 is architecturally superior for multi-vendor support. Both are valid depending on priorities: **Option 1 for minimal change, Option 2 for best vendor alignment.**

**Implementation plan for Option 2:**
- Modify `record_chat` in `republic/src/republic/tape/manager.py` to always create an assistant `message` entry when tool calls are present, even if `response_text=None`.
- The assistant message entry payload should contain: `role`, `content` (possibly empty), `tool_calls` (if present), and a vendor-neutral `reasoning` field.
- The `reasoning` field should be a normalized object that can be translated per vendor:
  ```json
  {
    "type": "thinking",
    "content": "I should use the echo tool...",
    "signature": "...",
    "vendor": "deepseek"
  }
  ```
- `_select_messages` should pass through the `reasoning` field without stripping it (the vendor-specific translation layer decides what to include).

**Vendor-specific reconstruction rules:**
- **DeepSeek:** Extract `reasoning.content` → `reasoning_content` field on message. Strip for non-tool-call turns (per Fact 4).
- **Anthropic:** Extract `reasoning.content` + `reasoning.signature` → `thinking` block at start of `content` array. Pass back unmodified (per Fact 25).
- **Google Gemini:** Extract `reasoning.signature` → `thoughtSignature` on function call parts. Only include for function call turns (per Fact 33).
- **OpenAI Chat:** Strip reasoning entirely (per Fact 12).
- **OpenAI Responses API:** Convert `reasoning` to reasoning item with ID. Use `previous_response_id` or explicit `input` items (per Fact 16).
- **xAI Grok:** Extract `reasoning.content` → `reasoning_content` field on message (per Fact 38).

### Option 3 as fallback for stateful APIs

Option 3 (separate reasoning entry) remains the most flexible approach and may be preferable for OpenAI Responses API and xAI Responses API, where reasoning items are fundamentally separate from messages. It can be adopted alongside Option 2 for specific vendor integrations without affecting the core tape schema.

---

## Open Questions

1. **OpenAI Chat Completions undocumented reasoning:** Is there any undocumented parameter that causes OpenAI Chat Completions to return `reasoning_content`? (S1 Open Question 1)

2. **Anthropic SDK auto-preservation:** Does the Anthropic Python SDK automatically preserve thinking block signatures when messages are passed back? (S2 Open Question 1)

3. **Gemini empty text signature parts:** What is the exact behavior when Gemini returns a thought signature in a part with empty text content? (S2 Open Question 2)

4. **xAI Chat Completions reasoning for Grok 4:** Does xAI Chat Completions ever return `reasoning_content` for `grok-4.20-reasoning`? (S2 Open Question 3)

5. **OpenAI Responses API reasoning item shape:** What is the exact JSON shape of a reasoning item when added to the `input` array? (S1 Open Question 3)

6. **DeepSeek streaming ordering:** Do `reasoning_content` deltas always appear before `content` deltas, or can they be interleaved? (S1 Open Question 4)

7. **Unified tape format normalization:** What is the minimal vendor-agnostic `reasoning` object schema that can support all vendors without information loss? Specifically, how should Anthropic's `signature` and Gemini's `thoughtSignature` be represented in a normalized form?

8. **Translation layer location:** Should vendor-specific reasoning translation live in `republic` (LLM client), `bub` (tape manager), or a new adapter layer?

9. **Bub streaming path:** Does the `_update_tape_async` path in `stream_events_async` require the same reasoning handling as the non-streaming path?

10. **Multiple tool call rounds:** For multi-round tool calling, should each round's `tool_call` entry have its own reasoning, or should reasoning be aggregated at the turn level?

11. **Model version context window management:** For Anthropic, how should the tape system handle the fact that older models strip thinking blocks when a non-tool-result user block is included? (Fact 29)

12. **Azure OpenAI reasoning:** Does Azure OpenAI's Chat Completions API expose `reasoning_content` for DeepSeek models or other reasoning models?

---

## Cross-References

- Parent exploration: `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md`
- This exploration supersedes the parent exploration's recommendation section for multi-vendor reasoning content support.
- See parent exploration for tape entry timeline details and the original Options 1–3 discussion.
- Raw documentation: `analysis/vendor_reasoning_content/raw/`
