# Vendor Reasoning Content Field Behavior

**Date:** 2026-05-07
**Subagent:** S3 — Cross-Vendor Synthesizer
**Parent:** `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md`
**Cross-references:**
- S1: `./analysis/VENDOR_REASONING_CONTENT_20260507_S1_TEMP.md` (DeepSeek + OpenAI)
- S2: `./analysis/VENDOR_REASONING_CONTENT_20260507_S2_TEMP.md` (Anthropic + Google + xAI)

---

## Notes

### Note 1: Synthesis Scope

This document synthesizes findings from S1 (DeepSeek + OpenAI) and S2 (Anthropic + Google + xAI) to produce cross-vendor comparison, tape-schema recommendations, and implementation guidance for Bub/Republic.

### Note 2: Architectural Split

Two fundamentally different architectures for reasoning content exist:
1. **Top-level message field:** DeepSeek, xAI Grok-3-mini — `reasoning_content` string on message object
2. **Content block array:** Anthropic — typed `thinking` blocks within `content` array
3. **Part-level metadata:** Google Gemini — `thoughtSignature` embedded in content parts
4. **Stateful item references:** OpenAI Responses API, xAI Responses API — reasoning items with IDs in output array
5. **No exposure:** OpenAI Chat Completions API — reasoning is discarded entirely

### Note 3: Tape Schema Constraints

Bub's current tape schema uses separate `message` and `tool_call` entries. The assistant message for tool-calling turns is reconstructed from `tool_call` entries by `_select_messages` (`bub/src/bub/builtin/context.py`). Reasoning content must fit into this existing schema or require schema changes.

---

## Facts

No new facts gathered in this synthesis. All facts are imported from S1 and S2.

---

## Comparison Matrix

| Dimension | DeepSeek | OpenAI (Chat) | OpenAI (Responses) | Anthropic | Google Gemini | xAI Grok |
|---|---|---|---|---|---|---|
| **Field Name & Location** | `message.reasoning_content` string | None (discarded) | `reasoning` items in output array with IDs | `content[]` blocks: `thinking`/`redacted_thinking` with `signature` | `parts[].thoughtSignature` + `thought` boolean | `message.reasoning_content` string (Chat); `reasoning.encrypted_content` (Responses) |
| **Response Format** | JSON object with `reasoning_content` alongside `content` and `tool_calls` | No reasoning field | Output array with `reasoning` items | `content` array with `thinking` blocks before `text`/`tool_use` | `parts` array with `thoughtSignature` metadata | JSON object with `reasoning_content` (Chat); encrypted content (Responses) |
| **Streaming Format** | `delta.reasoning_content` string chunks | No reasoning field | Output array events | `content_block_delta` with `thinking_delta` + `signature_delta` | `thought` boolean on streaming parts | `delta.reasoning_content` (Chat); encrypted streams (Responses) |
| **Request Format (history)** | Must pass back for tool-call turns (400 if missing); ignored for non-tool-call turns | N/A (not exposed) | Include reasoning item IDs via `previous_response_id` or explicit `input` items | Must pass back `thinking` blocks unmodified, including `signature`, before `tool_use` blocks | Must pass back `thoughtSignature` in parts for function calls (400 if missing) | Undocumented for Chat; Responses API uses item IDs |
| **Tool Call Coexistence** | `content` + `reasoning_content` + `tool_calls` in same message | `content` OR `tool_calls` | Separate `message` and `function_call` output items | `thinking` blocks + `tool_use` blocks in same `content` array | `thoughtSignature` alongside `functionCall` in parts | `content` + `reasoning_content` + `tool_calls` in same message (Chat) |
| **Model Gating** | `deepseek-v4-flash`, `deepseek-v4-pro`; `thinking` param | `reasoning_effort` param (varies by model) | `reasoning.effort` in Responses API | `claude-sonnet-4-6`, `claude-opus-4-5`; `thinking` param with `budget_tokens` | `gemini-3-flash-preview`, `gemini-3-pro-preview`, etc.; `thinking_level` or `thinking_budget` | `grok-3-mini` (Chat); `grok-4.20-reasoning` (Responses) |
| **Special Rules** | `reasoning_content` from tool-calling turns persists across ALL future turns; `reasoning_effort` mapped for compatibility | Responses API only; encrypted reasoning content available via `reasoning.encrypted_content` | Requires `store=true` for stateful persistence; Codex transport requests `reasoning.encrypted_content` | Thinking blocks must be first in content array; tool_choice only supports `any` with thinking; model-version-dependent context window management | Cannot use both `thinking_level` and `thinking_budget`; stateless API requires manual signature passing | Chat Completions API limited to `grok-3-mini` for reasoning; Responses API preferred; requires 3600s timeout |

---

## Cross-Vendor Claims

### Claim 1: There are four mutually incompatible architectural patterns for reasoning content across vendors

**Reasoning:** Five vendors exhibit four distinct architectures:
1. **Top-level string field** on message object (DeepSeek S1 Fact 1, xAI Grok S2 Fact 18)
2. **Content block array** with typed blocks and signatures (Anthropic S2 Fact 1, S2 Fact 2)
3. **Part-level metadata** with encrypted signatures (Google Gemini S2 Fact 10, S2 Fact 14)
4. **Stateful item references** in output array with IDs (OpenAI Responses API S1 Fact 15, xAI Responses API S2 Fact 21)

OpenAI Chat Completions API represents a fifth pattern: **no exposure at all** (S1 Fact 11, S1 Fact 12).

A unified tape format cannot assume any single vendor's structure. It must store reasoning in a normalized form and translate per vendor.

**References:** S1 Fact 1, S1 Fact 11, S1 Fact 12, S1 Fact 15, S2 Fact 1, S2 Fact 10, S2 Fact 14, S2 Fact 18, S2 Fact 21

### Claim 2: History preservation requirements are vendor-specific and create conflicting rules

**Reasoning:** Each vendor that exposes reasoning has different rules for preserving it in message history:
- **DeepSeek:** `reasoning_content` must be preserved for tool-call turns (400 error if missing) but is ignored for non-tool-call turns (S1 Fact 4, S1 Fact 5). Furthermore, reasoning from tool-calling turns must persist across ALL future turns, even unrelated user questions (S1 Fact 10).
- **Anthropic:** `thinking` blocks must be passed back completely unmodified, including signatures, and must precede `tool_use` blocks in the content array (S2 Fact 4, S2 Fact 5, S2 Fact 6).
- **Google Gemini:** `thoughtSignature` must be passed back for function calls (400 error if missing), but the API is stateless so every request is independent (S2 Fact 12, S2 Fact 13).
- **OpenAI Responses API:** Reasoning items persist via stateful `previous_response_id` or explicit item IDs in `input` array (S1 Fact 15, S1 Fact 16).
- **xAI Grok:** Chat Completions requirements undocumented; Responses API uses stateful items (S2 Fact 20, S2 Fact 21).

These rules conflict: DeepSeek says strip reasoning for normal turns, Anthropic says preserve all thinking blocks unmodified, Gemini says preserve signatures for function calls only. A unified tape schema must support conditional inclusion rules per vendor.

**References:** S1 Fact 4, S1 Fact 5, S1 Fact 10, S1 Fact 15, S1 Fact 16, S2 Fact 4, S2 Fact 5, S2 Fact 6, S2 Fact 12, S2 Fact 13, S2 Fact 20, S2 Fact 21

### Claim 3: Tool call coexistence patterns are split between "unified message" and "separate items" architectures

**Reasoning:** Three vendors place reasoning, content, and tool calls on a single assistant message object:
- **DeepSeek:** `content` + `reasoning_content` + `tool_calls` in same message (S1 Fact 6)
- **xAI Grok:** `content` + `reasoning_content` + `tool_calls` in same message (S2 Fact 23)
- **Anthropic:** `thinking` blocks + `tool_use` blocks in same `content` array (S2 Fact 6)

Two vendors use separate items/arrays:
- **OpenAI Responses API:** `message` and `function_call` are separate output items (S1 Fact 15)
- **Google Gemini:** `functionCall` is a separate part type with its own `thoughtSignature` (S2 Fact 14)

This split means a tape schema designed around "one assistant message per turn" works for DeepSeek/xAI/Anthropic but needs adaptation for OpenAI Responses API and Gemini.

**References:** S1 Fact 6, S1 Fact 15, S2 Fact 6, S2 Fact 14, S2 Fact 23

### Claim 4: Streaming delta field naming conventions cluster around `reasoning_content` but Anthropic uses a completely different event model

**Reasoning:** DeepSeek and xAI Grok both use `delta.reasoning_content` for streaming reasoning chunks (S1 Fact 3, S2 Fact 19). This is a direct string field on the delta object, identical to how `delta.content` works for regular text.

Anthropic uses a completely different streaming event model: `content_block_start` / `content_block_delta` / `content_block_stop` events, where reasoning is delivered via `thinking_delta` and `signature_delta` delta types within `content_block_delta` events (S2 Fact 3). This is not a field on a delta object but a separate event type within the SSE stream.

Google Gemini streaming uses `thought` boolean flags on parts (S2 Fact 11), which is yet another model.

A unified streaming tape format must either: (a) normalize all streaming events to a common representation, or (b) store vendor-native events and translate during playback.

**References:** S1 Fact 3, S2 Fact 3, S2 Fact 11, S2 Fact 19

### Claim 5: OpenAI Chat Completions API is the only vendor that completely prevents reasoning preservation across turns

**Reasoning:** Among all vendors investigated, only OpenAI's Chat Completions API explicitly discards reasoning after every request with no mechanism to preserve it (S1 Fact 12). All other vendors provide some mechanism:
- DeepSeek: `reasoning_content` string in response and request (S1 Fact 1, S1 Fact 5)
- Anthropic: `thinking` blocks in content array (S2 Fact 1, S2 Fact 4)
- Google Gemini: `thoughtSignature` in parts (S2 Fact 10, S2 Fact 12)
- xAI Grok: `reasoning_content` in Chat Completions (S2 Fact 18) or encrypted content in Responses API (S2 Fact 21)
- OpenAI Responses API: stateful reasoning items with IDs (S1 Fact 15)

This means any system using OpenAI Chat Completions API with reasoning models (e.g., GPT-5 with reasoning) cannot preserve reasoning in tape history. To support reasoning preservation for OpenAI models, the system must migrate to the Responses API.

**References:** S1 Fact 12, S1 Fact 15, S2 Fact 1, S2 Fact 10, S2 Fact 12, S2 Fact 18, S2 Fact 21

### Claim 6: A vendor-agnostic tape schema must support at least three structural patterns and conditional reconstruction rules

**Reasoning:** Based on the comparison matrix and vendor facts, reasoning content appears in at least three structural forms that a tape schema must accommodate:
1. **Top-level string:** `reasoning_content` on message object (DeepSeek, xAI)
2. **Content block array:** Typed blocks with signatures (Anthropic)
3. **Part-level metadata:** `thoughtSignature` embedded in parts (Google Gemini)

Additionally, two vendors use stateful item references (OpenAI Responses API, xAI Responses API) that are fundamentally different from message-based APIs.

The reconstruction rules also vary:
- DeepSeek: include reasoning for tool-call turns, strip for normal turns (S1 Fact 4, S1 Fact 5)
- Anthropic: always include thinking blocks unmodified (S2 Fact 5)
- Google Gemini: include thought signatures for function call parts (S2 Fact 13)
- OpenAI Responses API: include reasoning item IDs (S1 Fact 15)

Therefore, the tape schema cannot be a simple `reasoning_content` string field. It needs a normalized representation that can be translated to any vendor's format with vendor-specific reconstruction rules.

**References:** S1 Fact 4, S1 Fact 5, S1 Fact 15, S2 Fact 1, S2 Fact 5, S2 Fact 10, S2 Fact 13, S2 Fact 18

### Claim 7: The "unified message" vendors (DeepSeek, xAI, Anthropic) are compatible with Option 2 (assistant message entry for tool calls), while "separate items" vendors (OpenAI Responses, Gemini) require Option 1 or 3

**Reasoning:** Vendors that place reasoning, content, and tool calls on a single assistant message (DeepSeek S1 Fact 6, xAI S2 Fact 23, Anthropic S2 Fact 6) are naturally compatible with Option 2: creating an assistant `message` entry that contains both `tool_calls` and reasoning. This aligns with their native API format.

Vendors that use separate items/arrays (OpenAI Responses API S1 Fact 15, Google Gemini S2 Fact 14) are less compatible with Option 2 because they don't have a single assistant message object. For these vendors, Option 1 (storing reasoning on `tool_call` entry) or Option 3 (separate reasoning entry) is more appropriate because it keeps reasoning separate from the message content, matching their architecture.

**CONTRADICTS:** `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#Recommendation` — The parent exploration recommends Option 1 as primary. This claim supersedes that recommendation based on the broader cross-vendor analysis showing Option 2 aligns with 3/5 vendors' native formats, whereas Option 1 creates an asymmetry (reasoning on `message` for normal turns, on `tool_call` for tool turns) that only works cleanly for DeepSeek/xAI.

**References:** S1 Fact 6, S1 Fact 15, S2 Fact 6, S2 Fact 14, S2 Fact 23, `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md#Options`

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
- **DeepSeek:** Extract `reasoning.content` → `reasoning_content` field on message. Strip for non-tool-call turns (per S1 Fact 4).
- **Anthropic:** Extract `reasoning.content` + `reasoning.signature` → `thinking` block at start of `content` array. Pass back unmodified (per S2 Fact 5).
- **Google Gemini:** Extract `reasoning.signature` → `thoughtSignature` on function call parts. Only include for function call turns (per S2 Fact 13).
- **OpenAI Chat:** Strip reasoning entirely (per S1 Fact 12).
- **OpenAI Responses API:** Convert `reasoning` to reasoning item with ID. Use `previous_response_id` or explicit `input` items (per S1 Fact 15).
- **xAI Grok:** Extract `reasoning.content` → `reasoning_content` field on message (per S2 Fact 18).

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

8. **Translation layer location:** Should vendor-specific reasoning translation live in `republic` (LLM client), `bub` (tape manager), or a new adapter layer? (S2 Open Question 5)

9. **Bub streaming path:** Does the `_update_tape_async` path in `stream_events_async` require the same reasoning handling as the non-streaming path? (Parent exploration Open Question 1)

10. **Multiple tool call rounds:** For multi-round tool calling, should each round's `tool_call` entry have its own reasoning, or should reasoning be aggregated at the turn level? (Parent exploration Note 3)

11. **Model version context window management:** For Anthropic, how should the tape system handle the fact that older models strip thinking blocks when a non-tool-result user block is included? (S2 Fact 9)

12. **Azure OpenAI reasoning:** Does Azure OpenAI's Chat Completions API expose `reasoning_content` for DeepSeek models or other reasoning models? (S1 Open Question 5)

---

*End of synthesis. Return to parent: `./analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md`*
