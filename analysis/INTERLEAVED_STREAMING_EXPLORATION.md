# Interleaved Reasoning/Content Streaming Exploration

**Date:** 2026-05-08  
**Status:** 🔍 Open Question — Research Phase  
**Related:** [`TAPE_ENTRY_TIMELINE_EXPLORATION.md`](./TAPE_ENTRY_TIMELINE_EXPLORATION.md)

---

## Note 1: Context

From the DeepSeek v4-pro testing, we discovered that the current tape format stores reasoning and content as **flat strings**:

```json
{
  "kind": "message",
  "payload": {
    "role": "assistant",
    "content": "Hello world",
    "reasoning_content": "Let me think about this"
  }
}
```

This loses **temporal ordering** information. In streaming, we accumulate:
```python
reasoning_parts: list[str] = []  # from delta.reasoning_content
parts: list[str] = []            # from delta.content
```

But the actual stream might interleave:
```
[chunk 1] reasoning: "Let me think"
[chunk 2] content: "Hello"
[chunk 3] reasoning: " about this"
[chunk 4] content: " world"
```

Current result: `{"reasoning_content": "Let me think about this", "content": "Hello world"}`

**Lost information:** The ordering of reasoning vs content chunks.

---

## Note 2: Why This Matters

### For OpenAI/DeepSeek Format (Completion API)

Reasoning and content are **parallel fields** at the message level:
```json
{
  "role": "assistant",
  "content": "Hello world",
  "reasoning_content": "Let me think about this",
  "tool_calls": [...]
}
```

Flat strings are **sufficient** — the API doesn't preserve ordering between reasoning and content.

### For Anthropic Format (Messages API)

Reasoning and content are **sequential blocks** in a content array:
```json
{
  "role": "assistant",
  "content": [
    {"type": "thinking", "thinking": "Let me think"},
    {"type": "text", "text": "Hello"},
    {"type": "thinking", "thinking": " about this"},
    {"type": "text", "text": " world"}
  ]
}
```

**Order matters.** Flat strings lose the ability to reconstruct this format accurately.

### For Interleaved Thinking (DeepSeek V3.2+, GLM-4.7)

The model can produce reasoning **after tool results** within the same turn:
```
User message
  → Assistant: reasoning + content + tool_calls
  → Tool execution
  → Assistant: MORE reasoning + content (continuation)
```

This creates multiple "steps" within a single turn that need to be preserved.

---

## Note 3: Research Findings

### Fact 1: DeepSeek Streaming Format

From [DeepSeek API Docs](https://api-docs.deepseek.com/guides/reasoning_model):

```python
for chunk in response:
    if chunk.choices[0].delta.reasoning_content:
        reasoning_content += chunk.choices[0].delta.reasoning_content
    else:
        content += chunk.choices[0].delta.content
```

**Observation:** DeepSeek uses separate delta fields. A chunk has EITHER `reasoning_content` OR `content`, not both. Simple accumulation works.

### Fact 2: SiliconFlow Interleaved Thinking

From [SiliconFlow Docs](https://docs.siliconflow.com/en/userguide/guides/interleaved-thinking):

> With Interleaved Thinking, a model can:
> 1. Decide whether it needs to call a tool
> 2. Call a tool
> 3. Receive tool results
> 4. Continue from intermediate outputs
> 5. Decide the next step

> The model may produce reasoning:
> - before any tool call,
> - between multiple tool calls,
> - **and after receiving tool results**

> You must preserve and replay **all** such `reasoning_content` exactly as generated.

### Fact 3: Anthropic Streaming Format

From [AWS Bedrock Docs](https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-extended-thinking.html):

```
event: content_block_start
data: {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Let me solve..."}}

event: content_block_stop
data: {"type": "content_block_stop", "index": 0}

event: content_block_start
data: {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "27 * 453 = 12,231"}}
```

**Observation:** Anthropic uses indexed content blocks. Each block has a type (`thinking`, `text`, `tool_use`). Streaming preserves block boundaries and ordering.

### Fact 4: Claude Tool Use with Thinking

From AWS Bedrock Docs (tool use example):

```json
{
  "role": "assistant",
  "content": [
    {"type": "thinking", "thinking": "The user wants weather..."},
    {"type": "text", "text": "I can help you get..."},
    {"type": "tool_use", "id": "toolu_01...", "name": "get_weather", "input": {"location": "Paris"}}
  ]
}
```

**Observation:** Within a single assistant message, thinking blocks come BEFORE text blocks, which come BEFORE tool_use blocks.

### Fact 5: Current Republic Streaming Code

From `republic/src/republic/clients/chat.py` (current changes):

```python
# Streaming accumulation
parts: list[str] = []
reasoning_parts: list[str] = []

for chunk in response:
    text = self._extract_chunk_text(chunk)
    if text:
        parts.append(text)
    reasoning_delta = self._extract_chunk_reasoning(chunk)
    if reasoning_delta:
        reasoning_parts.append(reasoning_delta)

# Final merge
text = "".join(parts)
reasoning = "".join(reasoning_parts)
```

**Observation:** Current code accumulates text and reasoning separately, losing ordering.

---

## Note 4: Open Questions

### Q1: Do reasoning and content actually interleave at chunk level?

**For DeepSeek/OpenAI:** No — each chunk has EITHER `delta.reasoning_content` OR `delta.content`.

**For Anthropic:** Yes — `thinking_delta` and `text_delta` can alternate within the same message.

### Q2: Does ordering matter for DeepSeek API?

Unknown. The API accepts flat `reasoning_content` + `content` fields. But for tool-calling with interleaved thinking, the model produces reasoning in multiple phases:
1. Before tool calls
2. After tool results

Each phase is a separate API response, so ordering within a single response may not matter.

### Q3: Should tape store ordered blocks or flat strings?

**Option A: Flat strings (current)**
- Pros: Simple, works for OpenAI/DeepSeek
- Cons: Loses ordering for Anthropic

**Option B: Ordered blocks**
- Pros: Preserves ordering, supports Anthropic
- Cons: Core model change, more complex

**Option C: Hybrid — store blocks when needed**
- Pros: Backward compatible
- Cons: Complex logic, hard to maintain

### Q4: How do other frameworks handle this?

**LiteLLM:** Appears to normalize to OpenAI format (flat strings)
**Vercel AI SDK:** Uses content parts array
**LangChain:** Uses message types with content blocks

---

## Claim 1: Flat Strings Are Insufficient for Anthropic Format

**Reasoning:** Anthropic's Messages API requires ordered content blocks (`thinking`, `text`, `tool_use`). Flat strings lose the ordering between these block types. While we can approximate the order (thinking before text before tool_use), this may not match the actual model output.

**References:** Fact 3, Fact 4

## Claim 2: DeepSeek Interleaved Thinking Does Not Require Ordered Blocks

**Reasoning:** DeepSeek's Completion API uses parallel fields (`reasoning_content`, `content`). Even with interleaved thinking (reasoning after tool results), each phase is a separate API response with its own flat fields. The ordering between reasoning and content within a single response is not preserved by the API itself.

**References:** Fact 1, Fact 2

## Claim 3: We Need a Decision Before Implementing MessagesTransportParser

**Reasoning:** The choice between flat strings vs ordered blocks affects the tape entry format (core model). If we choose ordered blocks, we need to update the format before implementing Anthropic parsing. If we choose flat strings, the MessagesTransportParser must reconstruct approximate ordering.

**References:** Claim 1, Claim 2, Note 3

---

## Next Steps

1. **Test DeepSeek v4-pro streaming** — verify if reasoning/content chunks actually alternate
2. **Check any-llm normalization** — does any-llm preserve block ordering for Anthropic?
3. **Decision needed** — core model change requires approval per Rule 1

---

## Appendix: Related Code

- `republic/src/republic/clients/chat.py` — Streaming accumulation logic
- `republic/src/republic/clients/parsing/types.py` — Parser interface
- `republic/src/republic/tape/entries.py` — Tape entry format
- `republic/src/republic/tape/context.py` — Message reconstruction
