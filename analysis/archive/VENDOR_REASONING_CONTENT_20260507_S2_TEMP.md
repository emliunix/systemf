# Vendor Reasoning Content Field Behavior

**Date:** 2026-05-07
**Subagent:** S2 — Anthropic + Google + xAI Explorer
**Parent:** `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md`
**Cross-reference:** `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md` (DeepSeek + OpenAI findings)

---

## Notes

### Note 1: Scope and Dimensions

This exploration investigates how Anthropic (Claude), Google (Gemini), and xAI (Grok) define the behavior of reasoning content fields in their chat completion APIs across 7 dimensions:

1. Field Name & Location
2. Response Format (non-streaming)
3. Streaming Format
4. Request Format (history playback)
5. Tool Call Coexistence
6. Model Gating
7. Special Rules

### Note 2: Critical Differences Between Vendors

The three vendors in this exploration have fundamentally different approaches to reasoning content:

- **Anthropic** uses a `content` block array with `thinking` and `redacted_thinking` block types, each with a `signature` field. This is structurally different from all other vendors.
- **Google Gemini** uses `thoughtSignature` fields embedded within content `parts`, plus `thought` boolean flags for thought summaries. It also uses encrypted signatures for multi-turn context preservation.
- **xAI Grok** uses a top-level `reasoning_content` string field on the message object, similar to DeepSeek but with important limitations on which models support it in Chat Completions.

### Note 3: Anthropic Docs Access Issue

Direct fetching of Anthropic documentation (https://docs.anthropic.com) was blocked due to regional restrictions ("App unavailable in region"). All Anthropic facts are derived from Tavily search results, AWS Bedrock documentation, GitHub issues, and community posts. The information is consistent across multiple independent sources.

### Note 4: Open Questions

1. For Anthropic, does the SDK automatically preserve and reattach signatures when messages are passed back, or is this the caller's responsibility?
2. For Google Gemini, what is the exact JSON shape of a `thoughtSignature` when it appears in a non-functionCall text part with empty text content?
3. For xAI Grok, does the Chat Completions API for `grok-4.20-reasoning` ever return `reasoning_content`, or is it exclusively available through the Responses API?
4. For all three vendors, what are the exact rules for stripping vs preserving reasoning content when constructing message history for non-reasoning models?

---

## Facts

### Anthropic

#### Fact 1: Reasoning is delivered as `thinking` content blocks in the `content` array

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://platform.claude.com/docs/en/build-with-claude/extended-thinking):

```json
{
  "content": [
    {
      "type": "thinking",
      "thinking": "Let me analyze this step by step...",
      "signature": "WaUjzkypQ2mUEVM36O2TxuC06KN8xyfbJwyem2dw3URve/op91XWHOEBLLqIOMfFG/UvLEczmEsUjavL...."
    },
    {
      "type": "text",
      "text": "Based on my analysis..."
    }
  ]
}
```

Unlike DeepSeek which uses a top-level `reasoning_content` string, Anthropic embeds reasoning within the `content` array as typed blocks.

#### Fact 2: Non-streaming response shape includes `thinking` blocks alongside `text` and `tool_use` blocks

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-extended-thinking.html):

The response `content` array can contain blocks in this order:
1. `thinking` blocks (with `thinking` text and `signature`)
2. `text` blocks OR `tool_use` blocks

#### Fact 3: Streaming delivers thinking via `content_block_delta` events with `thinking_delta` type

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://github.com/anomalyco/opencode/issues/6176):

```
event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":"","signature":""} }

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"I nee"} }

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"..."} }
```

#### Fact 4: When sending history back, thinking blocks must be included in the assistant message's `content` array

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://meta.discourse.org/t/error-using-claude-3-7-sonnet-with-discourse-ai-plugin/354624):

Error when thinking blocks are missing:
```
messages.1.content.0.type: Expected `thinking` or `redacted_thinking`, but found `tool_use`.
When `thinking` is enabled, a final assistant message must start with a thinking block
(preceeding the lastmost set of `tool_use` and `tool_result` blocks).
```

#### Fact 5: Thinking blocks must be passed back completely unmodified, including the `signature` field

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://github.com/vercel/ai/issues/11602):

> "You must include the complete, unmodified thinking or redacted_thinking block back to the API."

#### Fact 6: A single assistant message can contain both `thinking` blocks and `tool_use` blocks

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://cobusgreyling.substack.com/p/building-with-claude-extended-thinking):

```python
# Response includes thinking followed by tool uses
for block in response.content:
    if block.type == "thinking":
        print(f"Thinking (summarized): {block.thinking}")
    elif block.type == "tool_use":
        print(f"Tool use: {block.name}")
```

The assistant message `content` array contains: `[thinking_block, tool_use_block, ...]`

#### Fact 7: Models supporting extended thinking include `claude-sonnet-4-6` and `claude-opus-4-5`

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://platform.claude.com/docs/en/build-with-claude/extended-thinking):

Enable with:
```python
thinking={"type": "enabled", "budget_tokens": 10000}
```

Models:
- `claude-sonnet-4-6` (and `claude-sonnet-4-5`)
- `claude-opus-4-5` and later
- NOT supported on Haiku models

#### Fact 8: Tool use with thinking only supports `tool_choice: any`

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-extended-thinking.html):

> "Tool choice limitation: Tool use with thinking only supports `tool_choice: any`. It does not support providing a specific tool, `auto`, or any other values."

#### Fact 9: Context window management differs by model version for thinking blocks

From `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md` (source: https://platform.claude.com/docs/en/build-with-claude/extended-thinking):

> "For Opus 4.5+ and Sonnet 4.6+, all previous thinking blocks are kept by default. For earlier Opus/Sonnet models and all Haiku models, because a non-tool-result user block was included, all previous thinking blocks are ignored and stripped from context."

---

### Google Gemini

#### Fact 10: Gemini does NOT use a `reasoning_content` field; it uses `thoughtSignature` in content parts

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thought-signatures):

```json
{
  "role": "model",
  "parts": [
    {
      "text": "I need to calculate the risk. Let me think step-by-step...",
      "thought_signature": "<Signature_C>"
    }
  ]
}
```

Unlike DeepSeek and xAI which use top-level string fields, Gemini embeds reasoning metadata within individual content parts.

#### Fact 11: Thought summaries are exposed via `thought: true` boolean on parts when `includeThoughts: true`

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thinking):

```go
for chunk := range resp {
  for _, part := range chunk.Candidates.Content.Parts {
    if part.Thought {
      fmt.Printf("Thought: %s\n", part.Text)
    } else {
      fmt.Printf("Answer: %s\n", part.Text)
    }
  }
}
```

#### Fact 12: The Gemini API is stateless; thought signatures must be passed back manually for multi-turn

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thinking):

> "The Gemini API is stateless, so the model treats every API request independently and doesn't have access to thought context from previous turns in multi-turn interactions."

> "In order to enable maintaining thought context across multi-turn interactions, Gemini returns thought signatures, which are encrypted representations of the model's internal thought process."

#### Fact 13: For function calling, thought signatures are REQUIRED and missing signatures cause 400 errors

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://community.n8n.io/t/gemini-pro-3-thought-signature-error/223349):

```
[400 Bad Request] Function call is missing a thought_signature in functionCall parts.
This is required for tools to work correctly, and missing thought_signature may lead to degraded model performance.
```

#### Fact 14: Function call parts include `thought_signature` alongside the `functionCall` object

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thought-signatures):

```json
{
  "role": "model",
  "parts": [
    {
      "functionCall": {
        "name": "Get_Projects_List",
        "args": {}
      },
      "thought_signature": "<Signature_A>"
    }
  ]
}
```

#### Fact 15: Usage reports thinking tokens separately via `thoughts_token_count`

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/tokens):

```json
{
  "usageMetadata": {
    "promptTokenCount": 58,
    "candidatesTokenCount": 820,
    "thoughtsTokenCount": 1477,
    "totalTokenCount": 2355
  }
}
```

#### Fact 16: Thinking models include `gemini-3-flash-preview`, `gemini-3-pro-preview`, `gemini-2.5-pro`, `gemini-2.5-flash`

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/thinking):

Models with thinking support:
- `gemini-3-flash-preview`
- `gemini-3-pro-preview`
- `gemini-3.1-pro-preview`
- `gemini-3.1-flash-lite`
- `gemini-2.5-pro`
- `gemini-2.5-flash`

#### Fact 17: Cannot use both `thinking_level` and `thinking_budget` in same request

From `analysis/vendor_reasoning_content/raw/google_api_docs.md` (source: https://ai.google.dev/gemini-api/docs/gemini-3):

> "Important: You cannot use both `thinking_level` and the legacy `thinking_budget` parameter in the same request. Doing so will return a 400 error."

---

### xAI Grok

#### Fact 18: Grok uses `reasoning_content` as a top-level field on the message object

From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.aimlapi.com/api-references/text-models-llm/xai/grok-4):

```json
{
  "message": {
    "role": "assistant",
    "content": "Hello! I'm Grok, built by xAI...",
    "reasoning_content": "Thinking... Thinking... "
  }
}
```

This is the same field name and location as DeepSeek's `reasoning_content`.

#### Fact 19: In streaming, reasoning is delivered via `delta.reasoning_content`

From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/reasoning):

```python
for response, chunk in chat.stream():
    if chunk.reasoning_content:
        print(chunk.reasoning_content, end="", flush=True)
```

#### Fact 20: Only `grok-3-mini` returns `reasoning_content` in Chat Completions API

From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/comparison):

> "Reasoning Models: Full support with encrypted reasoning content [Responses API]. Limited - only `grok-3-mini` returns `reasoning_content` [Chat Completions API]."

This is a critical limitation: `grok-4.20-reasoning` and `grok-4-fast-reasoning` do NOT return `reasoning_content` in the legacy Chat Completions endpoint.

#### Fact 21: Responses API returns `reasoning.encrypted_content` with full reasoning support

From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/comparison):

Parameter mapping:
| Chat Completions | Responses API | Notes |
| --- | --- | --- |
| `messages` | `input` | Array of message objects |
| — | `include` | Request additional data like `reasoning.encrypted_content` |

#### Fact 22: Reasoning tokens are reported in `usage.completion_tokens_details.reasoning_tokens`

From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/partner-models/grok/capabilities/reasoning):

```json
{
  "usage": {
    "completion_tokens": 50,
    "completion_tokens_details": {
      "reasoning_tokens": 124
    }
  }
}
```

#### Fact 23: A single assistant message can contain `content`, `reasoning_content`, and `tool_calls` simultaneously

From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/structured-outputs):

```javascript
const completion = await client.chat.completions.create({
    model: "grok-4.20-reasoning",
    messages,
    tools,
});

const message = completion.choices[0].message;
// message.content, message.tool_calls, and potentially message.reasoning_content
```

The cookbook example explicitly accesses both:
```python
return response.choices[0].message.content, response.choices[0].message.reasoning_content
```

#### Fact 24: Reasoning models require timeout override (3600s)

From `analysis/vendor_reasoning_content/raw/xai_api_docs.md` (source: https://docs.x.ai/developers/model-capabilities/text/reasoning):

```python
client = Client(
    api_key=os.getenv("XAI_API_KEY"),
    timeout=3600,  # Override default timeout with longer timeout for reasoning models
)
```

---

## Claims

### Claim 1: Anthropic, Google, and xAI use three mutually incompatible reasoning content representations

**Reasoning:** 
- Anthropic uses typed content blocks (`thinking`, `redacted_thinking`) within the `content` array, each with a `signature` field (Fact 1, Fact 2). This requires array manipulation and signature preservation.
- Google Gemini uses `thoughtSignature` embedded within individual content `parts`, plus `thought` boolean flags for summaries (Fact 10, Fact 11). This requires part-level metadata handling.
- xAI Grok uses a top-level string field `reasoning_content` on the message object (Fact 18), identical in structure to DeepSeek but with model-dependent availability (Fact 20).

This means a unified tape format cannot simply store a `reasoning_content` string and expect it to work across all vendors. The representation must be vendor-agnostic at the tape level and translated per vendor.

**References:** Fact 1, Fact 10, Fact 18, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 1`

### Claim 2: Anthropic has the strictest requirements for reasoning preservation in message history

**Reasoning:**
- Anthropic requires thinking blocks to be passed back completely unmodified, including the `signature` field (Fact 5). Missing or modified signatures cause 400 errors.
- The assistant message must start with a thinking block before any `tool_use` blocks (Fact 4).
- Tool use with thinking only supports `tool_choice: any`, not `auto` or specific tools (Fact 8).
- Context window management for thinking blocks varies by model version (Fact 9).

In comparison:
- DeepSeek requires `reasoning_content` for tool-call turns but ignores it for non-tool-call turns (S1 Fact 4, S1 Fact 5).
- Google Gemini requires `thought_signature` for function calling but the API is stateless (Fact 12, Fact 13).
- xAI Grok's requirements for passing back `reasoning_content` are less strict (no documented 400 errors for missing reasoning).

**References:** Fact 4, Fact 5, Fact 8, Fact 9, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 4`, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 5`

### Claim 3: Google Gemini's stateless API with thought signatures creates a unique multi-turn reasoning challenge

**Reasoning:**
- The Gemini API is stateless, meaning every request is independent (Fact 12).
- To maintain reasoning context, Gemini returns `thoughtSignature` fields that must be passed back in subsequent requests (Fact 12).
- For function calling, missing `thought_signature` causes 400 errors (Fact 13).
- For non-functionCall text parts, thought signatures may be returned in parts with empty text content (Fact 10).
- This is fundamentally different from DeepSeek (stateless but uses `reasoning_content` string) and OpenAI Responses API (stateful with `previous_response_id`).

The implication for tape design: Gemini requires storing `thoughtSignature` metadata on individual content parts, not just at the message level.

**References:** Fact 10, Fact 12, Fact 13, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 15`

### Claim 4: xAI Grok's Chat Completions API has limited reasoning support compared to its Responses API

**Reasoning:**
- xAI has two APIs: legacy Chat Completions and modern Responses API (Fact 21).
- Only `grok-3-mini` returns `reasoning_content` in Chat Completions (Fact 20).
- `grok-4.20-reasoning` and `grok-4-fast-reasoning` require the Responses API for full reasoning access via `reasoning.encrypted_content` (Fact 20, Fact 21).
- This means any system using xAI's Chat Completions endpoint (like the OpenAI-compatible SDK) will NOT get reasoning content for Grok 4 reasoning models.

This is a critical architectural decision point: supporting xAI reasoning may require migrating from Chat Completions to Responses API.

**References:** Fact 18, Fact 20, Fact 21

### Claim 5: Tool call coexistence with reasoning varies significantly across all five vendors (DeepSeek, OpenAI, Anthropic, Google, xAI)

**Reasoning:**
- **DeepSeek:** Single assistant message can contain `content`, `reasoning_content`, and `tool_calls` simultaneously (S1 Fact 6).
- **OpenAI Chat Completions:** No reasoning exposure at all (S1 Fact 11, S1 Fact 12).
- **OpenAI Responses API:** Separate `message` and `function_call` output items in an output array (S1 Fact 15, S1 Claim 4).
- **Anthropic:** Assistant message `content` array contains `thinking` blocks followed by `text` or `tool_use` blocks (Fact 2, Fact 6).
- **Google Gemini:** Function call parts include `thought_signature` alongside the `functionCall` object (Fact 14).
- **xAI Grok:** `reasoning_content` top-level field can coexist with `content` and `tool_calls` (Fact 23).

This diversity means any unified tape format must support multiple coexistence patterns and translate them per vendor.

**References:** Fact 2, Fact 6, Fact 14, Fact 23, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 6`, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 11`, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 15`

### Claim 6: A unified reasoning content storage format must be vendor-agnostic and support at least three structural patterns

**Reasoning:**
Based on the facts across both S1 and S2 explorations, reasoning content appears in at least three structural forms:

1. **Top-level string field:** `reasoning_content` string on message object (DeepSeek, xAI Grok-3-mini)
2. **Content block array:** Typed blocks (`thinking`, `redacted_thinking`) with signatures within `content` array (Anthropic)
3. **Part-level metadata:** `thoughtSignature` and `thought` boolean embedded in individual content parts (Google Gemini)
4. **Stateful item references:** Reasoning items with IDs in a stateful output array (OpenAI Responses API)

A unified tape format should store reasoning in a normalized form that can be translated to any of these vendor-specific representations. The tape entry should not assume any single vendor's format.

**References:** `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 1`, `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md#Fact 15`, Fact 1, Fact 10, Fact 18

---

## Open Questions

1. **Anthropic SDK auto-preservation:** Does the Anthropic Python SDK automatically preserve and reattach thinking block signatures when messages are passed back, or is this entirely the caller's responsibility?

2. **Gemini empty text signature parts:** What is the exact behavior when Gemini returns a thought signature in a part with empty text content during streaming? Is this a carrier chunk that should be merged with the next part?

3. **xAI Chat Completions reasoning for Grok 4:** Does the xAI Chat Completions API ever return `reasoning_content` for `grok-4.20-reasoning` under any circumstances, or is it strictly limited to the Responses API?

4. **Unified tape format design:** Given the 5+ different reasoning representations across vendors, what is the minimal vendor-agnostic tape schema that can support all of them without information loss?

5. **Bub/Republic translation layer:** Where should the vendor-specific translation logic live? In `republic` (the LLM client layer), in `bub` (the tape manager), or in a new adapter layer?
