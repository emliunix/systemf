# Tape Entry Timeline Exploration - Consolidated

**Date:** 2026-05-07  
**Status:** ✅ Empirically validated via live API traces

---

## Executive Summary

This document traces the exact sequence of tape entries and API interactions during multi-turn conversations with reasoning and tool calls. All findings are empirically validated through live API captures with DeepSeek (both OpenAI and Anthropic formats) and Zhipu AI.

**Key Finding:** For `deepseek-v4-pro` with thinking mode enabled, `reasoning_content` is **strictly required** for ALL assistant messages. This is the most strict/correct model we follow. Some vendors/models may work with relaxed constraints (see Part 7).

**Architecture Finding:** Republic acts as a bridge between the any-llm SDK (which provides TWO normalized formats — Completion API and Messages API) and the unified tape storage. Transport-dependent decoding and reconstruction is required, but tape entries remain transport-agnostic.

---

## Part 0: Architecture — Three Model Layers

### Current Transport Parser Implementation

Republic has transport-specific parsers in `republic/src/republic/clients/parsing/`:

```python
_PARSERS: dict[TransportKind, BaseTransportParser] = {
    "completion": CompletionTransportParser(),    # OpenAI Chat Completions
    "responses": ResponseTransportParser(),       # OpenAI Responses API
    "messages": CompletionTransportParser(),      # Anthropic Messages API
}
```

**Critical Finding:** The "messages" transport (Anthropic Messages API) currently reuses `CompletionTransportParser`. This means Anthropic responses are parsed using OpenAI Chat Completions logic. A dedicated `MessagesTransportParser` for Anthropic format is needed.

Each parser implements:
- `extract_text()` — Extract content text
- `extract_reasoning()` — Extract reasoning (str for completion, dict for responses)
- `extract_tool_calls()` — Extract tool calls
- `extract_chunk_text()` — Extract streaming text deltas
- `extract_chunk_reasoning()` — Extract streaming reasoning deltas

### Overview

Republic sits between the **any-llm SDK** (which wraps vendor APIs) and the **Tape** (persistent conversation storage). The architecture has three distinct model layers:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Transport (Raw Vendor APIs)                   │
│  • OpenAI Chat Completions                              │
│  • Anthropic Messages API                               │
│  • OpenAI Responses API                                 │
│  • Google Gemini                                        │
│  • xAI Grok                                             │
└─────────────────────────────────────────────────────────┘
                           ↕ Provider adapter in any-llm
┌─────────────────────────────────────────────────────────┐
│  Layer 2: any-llm SDK (Unified list, different content)│
│                                                         │
│  Unified: Both APIs produce `messages: list[dict]`     │
│                                                         │
│  Format A: Completion API (OpenAI-based)                │
│  • Individual message: `{role, content: str, reasoning_content?: str, tool_calls?: [...]}`
│  • Used by: OpenAI, DeepSeek, xAI, Google               │
│                                                         │
│  Format B: Messages API (Anthropic-based)               │
│  • Individual message: `{role, content: [Block]}`       │
│  • Blocks: TextBlock | ToolUseBlock | ThinkingBlock     │
│  • Used by: Anthropic, DeepSeek Anthropic endpoint      │
│                                                         │
│  Republic MUST know which format is active to parse     │
│  and reconstruct individual message content.            │
└─────────────────────────────────────────────────────────┘
                           ↕ Republic parsers & reconstruction
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Republic + Tape (Unified, transport-agnostic) │
│  • Flat entries: message, tool_call, tool_result        │
│  • One semantic unit per entry                          │
│  • Reasoning stored on message entries                  │
│  • tool_call entries are standalone                     │
│  • Must preserve enough info for reconstruction         │
└─────────────────────────────────────────────────────────┘
```

### Core Rule

**Stored tape entries are unified (transport-agnostic), but transport-dependent decoding and reconstruction is necessary.**

any-llm normalizes at the **list level** (both APIs produce `messages: list[dict]`), but individual message **content format** differs:
- Completion API: `content` is a string, `reasoning_content` is a string
- Messages API: `content` is an array of typed blocks

- **On receive (API → Tape):** Republic uses the active transport's parser to extract content, reasoning, and tool calls from the vendor-specific message format, then normalizes into unified tape entries.
- **On send (Tape → API):** Republic reads unified tape entries and reconstructs them into the specific any-llm format (Completion or Messages) that the active transport expects.

### Tape Entry Format Reference

See [`analysis/TAPE_ENTRY_KINDS_EXPLORATION.md`](./TAPE_ENTRY_KINDS_EXPLORATION.md) for the complete tape entry format definition. Key fields:

```python
@dataclass(frozen=True)
class TapeEntry:
    id: int
    kind: str          # "message" | "system" | "anchor" | "tool_call" | "tool_result"
    payload: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)
    date: str = field(default_factory=utc_now)
```

**Assistant message entry with reasoning:**
```json
{
  "kind": "message",
  "payload": {
    "role": "assistant",
    "content": "",
    "reasoning_content": "I should use the bash tool...",
    "tool_calls": [{"id": "call_xxx", "function": {"name": "bash", "arguments": "..."}}]
  }
}
```

**Tool call entry (standalone, no reasoning):**
```json
{
  "kind": "tool_call",
  "payload": {
    "calls": [{"id": "call_xxx", "function": {"name": "bash", "arguments": "..."}}]
  }
}
```

### Why This Matters

The tape entry format is a **CORE MODEL**. It must:
1. Store enough normalized information to reconstruct **both** Completion and Messages formats
2. Support reasoning representation that can become:
   - `reasoning_content` string (DeepSeek / Completion format)
   - `thinking` block (Anthropic / Messages format)
   - `reasoning` item (Responses API)
3. Support tool call representation that can become:
   - `tool_calls` array (Completion format)
   - `tool_use` blocks in content array (Messages format)

**Changes to core models require strict reasoning, review, and approval.**

---

## Part 0.5: Core Rules

The following rules are non-negotiable constraints that govern all work on message and tape models.

### Rule 1: Core Model Immutability

LLM request/response format and tape entry format are **CORE MODELS**. Any change requires:
- Strict reasoning and justification
- Code review and approval
- Backward compatibility analysis

### Rule 2: No Ad-hoc Field Access

Strictly prohibited:
```python
# WRONG - never do this
entry["some_reasoning"] = "xxx"
msg["unknown_field"] = value
```

All field access must go through typed models or well-defined APIs.

### Rule 3: State Machine First

Before any work on messages, **MUST** build understanding from the state machine invariants, NOT by looking at bare list of dicts.

The state machine defines:
- Valid message sequences
- Required fields per state transition
- Reasoning requirements (I1, R1, R2)

### Rule 4: No Code Guessing

Guessing from surrounding code is strictly prohibited. Traces are the golden fact if something can't be determined from the model.

**Process:**
1. Read the model definition
2. Check state machine invariants
3. If ambiguous, check API traces
4. Never infer from "it looks like it should work"

### Rule 5: Split on Save, Combine on Reconstruct

**On save (API → Tape):**
- Assistant message with tool calls → split into:
  - `message` entry (assistant, with reasoning)
  - `tool_call` entry (standalone, no reasoning)

**On reconstruct (Tape → API):**
- `message` (assistant) + `tool_call` → merge into single assistant message
- Include reasoning from `message` entry
- Include tool_calls from `tool_call` entry

---

## Part 1: Code Architecture

### Bub Uses Custom Message Selector

From `bub/src/bub/builtin/context.py:12-16`:
```python
def default_tape_context() -> TapeContext:
    return TapeContext(select=_select_messages)
```

### `_select_messages` Reconstructs Tool Calls

From `bub/src/bub/builtin/context.py:18-33`:
```python
def _select_messages(entries: Iterable[TapeEntry], _context: TapeContext) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    pending_calls: list[dict[str, Any]] = []

    for entry in entries:
        match entry.kind:
            case "anchor":
                _append_anchor_entry(messages, entry)
            case "message":
                _append_message_entry(messages, entry)
            case "tool_call":
                pending_calls = _append_tool_call_entry(messages, entry)
            case "tool_result":
                _append_tool_result_entry(messages, pending_calls, entry)
                pending_calls = []
    return messages
```

### No Assistant Message Entry for Tool-Calling Turns

From `republic/src/republic/tape/manager.py:238-242`:
```python
if response_text is not None:
    await self._tape_store.append(
        tape,
        TapeEntry.message({"role": "assistant", "content": response_text}, **meta),
    )
```

When `_handle_tools_auto_response_async` passes `response_text=None` (tool calls, not text), this block is **SKIPPED**.

### `_append_tool_call_entry` Creates Assistant Message

From `bub/src/bub/builtin/context.py:48-52`:
```python
def _append_tool_call_entry(messages: list[dict[str, Any]], entry: TapeEntry) -> list[dict[str, Any]]:
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    if calls:
        messages.append({"role": "assistant", "content": "", "tool_calls": calls})
    return calls
```

### Known Implementation Issues

**Issue: `MessagesTransportParser` missing** — The `messages` transport (Anthropic) reuses `CompletionTransportParser`. Anthropic format uses typed content blocks (`thinking`, `text`, `tool_use`), not flat string fields. A dedicated parser is needed.

**Resolved: Blind reasoning pruning in `chat.py`** — The `_prepare_messages` / `_prepare_messages_async` methods previously stripped `reasoning_content` / `reasoning` from ALL outgoing messages. Removed; `_default_messages()` is now the single source of truth for reasoning pruning.

See also `INTERLEAVED_STREAMING_EXPLORATION.md` for related streaming format concerns.

---

## Part 2: API State Machine (Empirically Validated)

### State Machine Diagram

```
User Request
    |
    v
[API Call] --> Assistant Response
    |               |
    |               +-- content: "" (when tool_calls)
    |               +-- reasoning_content: "..." (REQUIRED)
    |               +-- tool_calls: [...] (optional)
    |               +-- finish_reason: "tool_calls" | "stop"
    |
    +-- tool_calls? --> Tool Execution
    |                       |
    |                       v
    |               Tool Result
    |                       |
    |                       v
    |               [Next API Call]
    |               (includes full history)
    |
    +-- no tool_calls? --> DONE
```

### State Transitions

| Current State | Input | Next State | Required Fields |
|--------------|-------|-----------|----------------|
| User Request | `{role: "user", content: "..."}` | Tool Call or Text | `role`, `content` |
| Tool Call Response | `{role: "assistant", content: "", reasoning_content: "...", tool_calls: [...]}` | Tool Execution | `role`, `content`, `reasoning_content`, `tool_calls` |
| Text Response | `{role: "assistant", content: "...", reasoning_content: "...", finish_reason: "stop"}` | DONE | `role`, `content`, `reasoning_content` |
| Tool Result | `{role: "tool", tool_call_id: "...", name: "...", content: "..."}` | Next API Call | `role`, `tool_call_id`, `content` |

### Agent Loop Boundary

Reasoning content is scoped to a **single agent loop** — bounded by two consecutive user messages. Each loop starts with a user input, and any assistant messages (with tool_calls or text) before the next user message belong to that loop.

This aligns with the **Historical optimization** rule: assistant messages before the last user message may drop reasoning to save tokens. The loop boundary provides a natural scoping point.

---

## Part 3: Live API Trace Findings

### Trace Files

1. `analysis/api_trace_deepseek_deepseek-reasoner_openai_20260507_161858.txt` (222KB)
   - 8-turn DeepSeek OpenAI format conversation
   - Multiple sequential tool calls

2. `analysis/api_trace_deepseek_deepseek-chat_anthropic_20260507_160537.txt` (26KB)
   - 2-turn DeepSeek Anthropic format conversation

3. `analysis/api_trace_glm_GLM-5.1_openai_20260507_160605.txt` (4KB)
   - Zhipu AI GLM-5.1 partial trace

### DeepSeek OpenAI Format: Multi-Turn Pattern

**Turn 1 Request:**
```json
{
  "model": "deepseek-reasoner",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant..."},
    {"role": "user", "content": "List files, then read README..."}
  ],
  "tools": [...],
  "tool_choice": "auto"
}
```

**Turn 1 Response:**
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "",
      "reasoning_content": "Let me start by listing the files...",
      "tool_calls": [{"id": "call_xxx", "function": {"name": "bash", "arguments": "..."}}]
    },
    "finish_reason": "tool_calls"
  }]
}
```

**Turn 2 Request (accumulated history):**
```json
{
  "messages": [
    {"role": "system", "content": "You are a helpful assistant..."},
    {"role": "user", "content": "List files, then read README..."},
    {
      "role": "assistant",
      "content": "",
      "reasoning_content": "Let me start by listing the files...",
      "tool_calls": [{"id": "call_xxx", ...}]
    },
    {"role": "tool", "tool_call_id": "call_xxx", "name": "bash", "content": "..."}
  ]
}
```

**By Turn 7:** Request payload grew to **16,855 bytes** with accumulated history of all previous turns.

### DeepSeek Anthropic Format Pattern

**Turn 1 Response:**
```json
{
  "content": [
    {
      "type": "thinking",
      "thinking": "The user wants me to list...",
      "signature": "8f17e417-9f1a-4c1a-8047-79377f46eecd"
    },
    {
      "type": "text",
      "text": "Hello! Let me start by listing the current directory."
    },
    {
      "type": "tool_use",
      "id": "call_00_xxx",
      "name": "bash",
      "input": {"command": "ls -la"}
    }
  ],
  "stop_reason": "tool_use"
}
```

---

## Part 4: Empirical Tests (Positive & Negative Cases)

### Test Script Setup

All test scripts are in `analysis/` and target `deepseek-v4-pro` via the OpenAI Chat Completions API with thinking mode enabled (`"thinking": {"type": "enabled"}`). Run with:

```bash
python analysis/test_<name>.py
```

Key scripts:

| Script | Purpose |
|--------|---------|
| `test_state_machine_validation.py` | I1/R1/R2 invariants, multi-turn tool chains |
| `test_reasoning_preservation.py` | `reasoning_content` required vs optional |
| `test_reasoning_multi.py` | Multi-turn reasoning preservation |
| `test_anthropic_signature.py` | Signature handling for Anthropic endpoint |
| `test_anthropic_combinations.py` | Thinking + signature combinations |
| `test_edge_cases.py` | Consecutive users, tool call interruption |
| `test_tool_call_stripping.py` | Strip tool_calls, error results, empty results |
| `test_streaming_chunks.py` | Streaming chunk structure analysis |

### Test 1: `reasoning_content` Preservation

**File:** `analysis/test_reasoning_preservation.py`

| Case | Method | Result |
|------|--------|--------|
| With reasoning on old message | Send history with `reasoning_content` | ✅ 200 OK, works |
| Without reasoning on old message | Send history WITHOUT `reasoning_content` | ✅ 200 OK, works |

**Conclusion:** For `deepseek-reasoner` (older model), `reasoning_content` is optional in history. However, for `deepseek-v4-pro` with thinking mode, it is **strictly required** for all assistant messages (see Test 5).

### Test 2: Multi-Turn `reasoning_content`

**File:** `analysis/test_reasoning_multi.py`

| Case | Turn 2 | Turn 3 |
|------|--------|--------|
| With reasoning preserved | `tool_calls` ✓ | `tool_calls` ✓ |
| Without reasoning on old turns | `tool_calls` ✓ | `tool_calls` ✓ |

**Conclusion:** For `deepseek-reasoner`, even across multiple turns, dropping `reasoning_content` from older assistant messages causes no errors. **TODO:** Retest with `deepseek-v4-pro` to verify if this relaxation still holds.

### Test 3: Anthropic `signature` Handling

**File:** `analysis/test_anthropic_signature.py`

| Case | Result |
|------|--------|
| With signature preserved | ✅ 200 OK |
| Without signature | ✅ 200 OK |
| With modified (fake) signature | ✅ 200 OK |

**Conclusion:** DeepSeek's Anthropic endpoint **does not validate signatures**. They are just message IDs, not cryptographic attestations like Claude requires.

### Test 4: Anthropic Thinking Content vs Signature Combinations

**File:** `analysis/test_anthropic_combinations.py`

| Case | Description | Result |
|------|-------------|--------|
| 1 | Both `thinking` + `signature` | ✅ 200 OK |
| 2 | Only `signature` (no `thinking` content) | ❌ 400 - missing field `thinking` |
| 3 | Only `thinking` content (no `signature`) | ✅ 200 OK |
| 4 | Neither (empty `thinking` block) | ❌ 400 - missing field `thinking` |
| 5 | No `thinking` block at all | ❌ 400 - must pass back thinking |

**Critical Finding:** For DeepSeek's Anthropic endpoint:
- **`thinking` field is REQUIRED** in the `thinking` block when reconstructing history
- **`signature` field is OPTIONAL** (can be safely dropped)
- If thinking mode is enabled, you **MUST** include the `thinking` block with `thinking` content in subsequent requests

This is **different** from the OpenAI endpoint where `reasoning_content` is completely optional!

### Test 5: Consecutive User Messages

**Result:** ✅ **Allowed** — API accepts multiple user messages in a row without an assistant message between them.

```json
[
  {"role": "system", "content": "You are helpful."},
  {"role": "user", "content": "What is 2+2?"},
  {"role": "user", "content": "Also, what is 3+3?"}
]
```

200 OK, assistant responds to both queries.

### Test 6: Tool Call Interrupted by User

**Result:** ❌ **Rejected** — 400 error: "An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'."

Tool calls MUST be followed by corresponding tool results. A user message cannot appear before tool results are provided. This is enforced by the API, not just a convention.

### Test 7: Tool Call Stripped Then User

**Result:** ✅ **Works** — If tool_calls are removed from the assistant message, a user message can follow without error.

The API validates the tool_calls → tool_result pairing by checking for the `tool_calls` field. If absent, the constraint doesn't apply.

### Test 8: Streaming Chunk Mutual Exclusivity

**Result:** ✅ **Confirmed** — Each streaming chunk has either `delta.reasoning_content` OR `delta.content`, never both.

```
reasoning_only: 40
content_only:   1
BOTH in chunk:  0
```

This means the chunk sequence naturally preserves a temporal order (reasoning first, content after), though the Completion API message format only has flat fields.

---

## Part 5: Corrected Understanding

### What We Originally Thought (WRONG)

```python
# INCORRECT - DeepSeek docs say reasoning must be preserved
def _append_message_entry(messages, entry):
    payload = dict(entry.payload)
    if payload.get("role") == "assistant":
        # Normal turn - strip reasoning_content
        payload.pop("reasoning_content", None)
    messages.append(payload)

def _append_tool_call_entry(messages, entry):
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    if calls:
        msg = {"role": "assistant", "content": "", "tool_calls": calls}
        # Tool-call turn - preserve reasoning_content
        reasoning = entry.payload.get("reasoning_content")
        if reasoning:
            msg["reasoning_content"] = reasoning
        messages.append(msg)
    return calls
```

### What We Now Know (CORRECT)

**For `deepseek-v4-pro` with thinking mode, `reasoning_content` is STRICTLY REQUIRED for ALL assistant messages.**

The API enforces this invariant:
```
∀m ∈ M : m.role = "assistant" ⟹ m.reasoning_content ≠ null ∧ m.reasoning_content ≠ ""
```

**Error message:** `"The \`reasoning_content\` in the thinking mode must be passed back to the API."`

This is the **strict model** we follow. Some vendors/models may work with relaxed constraints, but we do not rely on that behavior.

```python
# CORRECT - For deepseek-v4-pro, ALWAYS preserve reasoning_content on ALL assistant messages
def _append_message_entry(messages, entry):
    payload = dict(entry.payload)
    if payload.get("role") == "assistant":
        # For deepseek-v4-pro: reasoning is REQUIRED for all assistant messages
        reasoning = payload.get("reasoning_content", "")
        if reasoning:
            payload["reasoning_content"] = reasoning
    messages.append(payload)
    return messages
```

### Why This Matters

**Tape Schema:**
- Reasoning is stored on `message` (assistant) entries, NOT on `tool_call` entries
- `tool_call` entries only need `calls` array (standalone)
- `message` entries store: `role`, `content`, `reasoning_content` (for assistant)
- **Core Model Rule:** Changes to tape entry format require strict reasoning, review, and approval

**Reasoning Handling:**
- Whether reasoning is required depends on the **user's settings** (e.g., `thinking: true`)
- Since settings usually don't change inside an agent loop (user + tool calls + assistant reply cycle), and `reasoning_content` handling is only valid in this scope, it's safe to check the setting once per loop
- ALL assistant messages MUST include `reasoning_content` when thinking mode is enabled

---

## Part 6: Tape Entry Timeline (Corrected)

### Single Turn with Tool Calls

**Tape entries created (in order):**
```
event     {"name": "loop.start", "data": {"model": "deepseek-v4-pro", "prompt": "..."}}
event     {"name": "loop.step.start", "data": {"step": 1, "prompt": "..."}}
system    {"content": "You are a helpful assistant..."}
message   {"role": "user", "content": "List files and explain"}
message   {"role": "assistant", "content": "", "reasoning_content": "Let me start by listing the files...", "tool_calls": [{"id": "call_xxx", ...}]}  # assistant message with reasoning
tool_call {"calls": [{"id": "call_xxx", "function": {"name": "bash", "arguments": "..."}}]}  # standalone, no reasoning here
tool_result {"results": [{"content": "README.md\nsrc/\n...", "tool_call_id": "call_xxx"}]}
event     {"name": "run", "data": {"status": "ok", "usage": {...}}}
event     {"name": "loop.step", "data": {"step": 1, "status": "continue"}}
```

**Tape Entry Model Definition:**
- `message` (assistant): Stores `role`, `content`, `reasoning_content`, and optionally `tool_calls`
- `tool_call`: Standalone entry with `calls` array only. **NO reasoning stored here.**
- `tool_result`: Standalone entry with `results` array
- **Rule:** Reasoning is ALWAYS stored on `message` (assistant) entries, never on `tool_call` entries
- **Rule:** `tool_call` entries are split from the assistant message during save and merged back during reconstruction

**Tool result format:** Each result in the `results` array is `{"content": "...", "tool_call_id": "..."}`. Error text goes in `content` as a plain string — no special error field. See [`TAPE_ENTRY_KINDS_EXPLORATION.md`](./TAPE_ENTRY_KINDS_EXPLORATION.md) for the full constructor design.

### Multi-Turn Conversation

```
Turn 1:
  user -> assistant(tool_call) -> tool_result
  
Turn 2:
  user -> assistant(tool_call) -> tool_result
  (history includes Turn 1's assistant + tool_result)
  
Turn 3:
  user -> assistant(text)  # final answer
  (history includes Turn 1 and Turn 2)
```

### Messages Reconstructed for API

For Turn 3, `_select_messages` produces:
```python
[
    {"role": "user", "content": "List files and explain"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", ...}]},
    {"role": "tool", "tool_call_id": "call_1", "content": "..."},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "call_2", ...}]},
    {"role": "tool", "tool_call_id": "call_2", "content": "..."},
    {"role": "user", "content": "Continue the task."},
]
```

**No `reasoning_content` needed in reconstructed messages.**

---

## Part 7: Design Decisions

### 1. Streaming Path
**Decision:** Same logic applies. Streaming also uses `_update_tape_async` path. `reasoning_content` is buffered during streaming and stored on the assistant `message` entry.

### 2. Claude Compatibility
**Decision:**
- **DeepSeek Anthropic endpoint:** `thinking` content is **required** in history, `signature` is optional (pass as-is if stored)
- **Native Claude:** Both `thinking` content AND cryptographic `signature` are required (handled by SDK)
- **Rule:** Always pass reasoning content if stored. Pass signature as-is if stored, never fabricate.

### 3. Multiple Tool Call Rounds
**Decision:** Each round adds `tool_call` + `tool_result` entries. The API accumulates them correctly.
- **Strict model (v4-pro):** ALL assistant messages MUST have `reasoning_content`
- **Anthropic format:** `thinking` blocks must be preserved in history

### 4. Provider Differences

**Strict Model (deepseek-v4-pro):**
| Provider | Format | Field | Required in History? | Notes |
|----------|--------|-------|---------------------|-------|
| DeepSeek v4-pro | OpenAI | `reasoning_content` | ✅ Yes | **REQUIRED** for ALL assistant messages |
| DeepSeek v4-pro | Anthropic | `thinking` content | ✅ Yes | Required if thinking enabled |
| DeepSeek | Anthropic | `signature` | ❌ No | Decorative. Pass as-is if stored, skip if not. |
| Claude | Anthropic | `thinking` content | ✅ Yes | Required |
| Claude | Anthropic | `signature` | ✅ Yes | Cryptographic attestation |

**TODO:** Validate if relaxed models (deepseek-reasoner, Zhipu AI) truly allow omitting reasoning_content. Test with v4-pro on both OpenAI and Anthropic endpoints.

---

## Part 8: Recommendations

### For Tape Schema

**Core Model Definition:**

Store `reasoning_content` on `message` (assistant) entries:

```json
{
  "kind": "message",
  "payload": {
    "role": "assistant",
    "content": "",
    "reasoning_content": "...",  // REQUIRED for tool-call turns (v4-pro)
    "tool_calls": [...]
  }
}
```

Store `tool_call` as standalone entry:

```json
{
  "kind": "tool_call",
  "payload": {
    "calls": [...]  // NO reasoning stored here
  }
}
```

**Rules:**
- Reasoning is ALWAYS on `message` (assistant) entries
- `tool_call` entries are standalone with `calls` only
- During reconstruction, merge `tool_call` into preceding assistant `message`

### For Message Reconstruction

**Transport-Dependent Reconstruction:**

When reconstructing messages for the API, Republic must apply transport-specific rules:

**For Completion API (OpenAI-based) transport:**
- Extract `reasoning_content` from assistant `message` entries
- Include in ALL assistant messages (v4-pro strict model)
- Optional for text-only assistant messages

**For Messages API (Anthropic-based) transport:**
- Extract `thinking` content from assistant `message` entries
- Convert to `thinking` block in `content` array
- Include `signature` if stored, pass as-is (do NOT fabricate)
- Place `thinking` blocks BEFORE `tool_use` blocks in content array

**Signature Handling Rule:**
- If signature is stored in tape, pass it as-is
- If signature is not stored, do NOT fabricate one
- Reasoning content MUST always be passed if available

**OpenAI Format:**
```python
def _append_tool_call_entry(messages, entry):
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    if calls:
        # Minimal required fields for API correctness
        messages.append({"role": "assistant", "content": "", "tool_calls": calls})
    return calls
```

**Anthropic Format:**
```python
def _append_tool_call_entry(messages, entry):
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    if calls:
        # Must include thinking content if it was in the response
        content_blocks = []
        reasoning = entry.payload.get("reasoning_content")
        if reasoning:
            content_blocks.append({
                "type": "thinking",
                "thinking": reasoning,
                # "signature": "..."  # Optional - can be dropped
            })
        content_blocks.append({
            "type": "tool_use",
            "id": calls[0]["id"],
            "name": calls[0]["function"]["name"],
            "input": json.loads(calls[0]["function"]["arguments"])
        })
        messages.append({"role": "assistant", "content": content_blocks})
    return calls
```

### For Display/UI

When showing conversation history to users, include `reasoning_content`:
```python
def show_reasoning(entry):
    if entry.kind == "tool_call":
        return entry.payload.get("reasoning_content", "")
    elif entry.kind == "message" and entry.payload.get("role") == "assistant":
        return entry.payload.get("reasoning_content", "")
```

---

## Test 5: Formal State Machine Validation (deepseek-v4-pro)

**Test file:** `analysis/test_state_machine_validation.py`

### Results Summary

| Test | Description | Status |
|------|-------------|--------|
| **1** | T2 Text Response with Reasoning | **PASS** |
| **2** | Valid T3→T4 (tool call WITH reasoning) | **PASS** |
| **3** | Invalid T3'→T4 (tool call WITHOUT reasoning) | **PASS** (400 error) |
| **4** | Text without reasoning in history | **PASS** |
| **5** | Historical assistant (before last user) without reasoning | **PASS** |
| **6a** | Multi-tool positive (all with reasoning) | **PASS** |
| **6b** | Multi-tool negative (drop recent reasoning) | **PASS** (400 error) |
| **6c** | Multi-tool mixed (drop old reasoning only) | **FAIL** (400 error) |

### Critical Discovery: I1 is Strictly Enforced on ALL Assistant Messages

For `deepseek-v4-pro` with thinking mode, the API validates **every** assistant message in the request:

```
∀m ∈ M : m.role = "assistant" ⟹ m.reasoning_content ≠ null ∧ m.reasoning_content ≠ ""
```

**Error message:** `"The \`reasoning_content\` in the thinking mode must be passed back to the API."`

### Rules (Confirmed for deepseek-v4-pro)

1. **I1 (Invariant):** `reasoning_content` is **REQUIRED** for ALL assistant messages
2. **R1 (Historical):** Assistant messages before the last user message MAY drop reasoning (optimization), but this is not guaranteed by the API
3. **R2 (Active context):** Assistant messages after the last user message MUST preserve reasoning — Test 6c confirms dropping old reasoning in active context fails with 400 error

### Implications for Tape Reconstruction

When building message arrays from tape entries:

```python
def _append_tool_call_entry(messages, entry):
    calls = _normalize_tool_calls(entry.payload.get("calls"))
    reasoning = entry.payload.get("reasoning_content", "")
    if calls:
        # For deepseek-v4-pro with thinking mode: reasoning is REQUIRED
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": calls,
        }
        # Always include reasoning if available — never drop for v4-pro
        if reasoning:
            msg["reasoning_content"] = reasoning
        messages.append(msg)
    return calls
```

**Strict Model:** Always preserve `reasoning_content` on ALL assistant messages. Never drop it.

> **Note:** In practice, we usually follow the **Historical optimization** (drop reasoning from messages before the last user) to save tokens, since Test 5 confirms this is safe. The strict model is the conservative fallback if historical optimization causes issues.

---

## Appendix: Open Questions

### Q1: Interleaved Reasoning/Content in Streaming

The current tape format stores reasoning and content as flat strings:
```json
{
  "reasoning_content": "...",
  "content": "..."
}
```

This loses temporal ordering information. In streaming, chunks may arrive as:
```
[reasoning] → [content] → [reasoning] → [content]
```

**Impact:**
- OpenAI/DeepSeek format: Flat strings are sufficient (parallel fields)
- Anthropic format: Requires ordered blocks (`thinking`, `text`, `tool_use`)
- DeepSeek interleaved thinking: Model produces reasoning AFTER tool results

**See:** [`INTERLEAVED_STREAMING_EXPLORATION.md`](./INTERLEAVED_STREAMING_EXPLORATION.md) for full research.

**Status:** 🔍 Research phase — needs decision before MessagesTransportParser implementation.

---

## Appendix: Raw Trace Files

- `analysis/api_trace_deepseek_deepseek-reasoner_openai_20260507_161858.txt`
- `analysis/api_trace_deepseek_deepseek-chat_anthropic_20260507_160537.txt`
- `analysis/api_trace_glm_GLM-5.1_openai_20260507_160605.txt`
- `analysis/test_reasoning_preservation.py`
- `analysis/test_reasoning_multi.py`
- `analysis/test_anthropic_signature.py`
- `analysis/test_anthropic_combinations.py`
- `analysis/test_state_machine_validation.py`
- `analysis/api_trace_capture.py`
