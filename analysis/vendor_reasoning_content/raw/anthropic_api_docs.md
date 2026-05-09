# Anthropic Extended Thinking API Documentation

**Sources:**
- https://platform.claude.com/docs/en/build-with-claude/extended-thinking
- https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-extended-thinking.html
- https://github.com/anomalyco/opencode/issues/6176
- https://community.vercel.com/t/how-vercel-ai-gateway-handles-claude-thinking-blocks-and-signatures-with-tool-calls/36443

---

## Response Format (Non-Streaming)

When extended thinking is enabled, the API response includes `thinking` content blocks, followed by `text` content blocks.

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

The `thinking` block contains:
- `type`: "thinking"
- `thinking`: string - the reasoning text
- `signature`: string - base64-encoded signature for verification

There is also a `redacted_thinking` block type:
```json
{
  "type": "redacted_thinking",
  "data": "..."
}
```

## Streaming Format

Streaming events for thinking:

```
event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":"","signature":""} }

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"I nee"} }

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"..."} }
```

## Request Format (Sending History Back)

When sending conversation history back, thinking blocks must be included in the assistant message's `content` array.

**Critical rule:** "When thinking is enabled, a final assistant message must start with a thinking block (preceding the lastmost set of tool_use and tool_result blocks). We recommend you include thinking blocks from previous turns."

**Error message when rule is violated:**
```
messages.1.content.0.type: Expected `thinking` or `redacted_thinking`, but found `tool_use`.
When `thinking` is enabled, a final assistant message must start with a thinking block
(preceeding the lastmost set of `tool_use` and `tool_result` blocks).
```

**Requirement:** "You must include the complete, unmodified thinking or redacted_thinking block back to the API."

Example of sending history with thinking and tool_use:
```json
{
  "role": "assistant",
  "content": [
    {
      "type": "thinking",
      "thinking": "Let me analyze this carefully...",
      "signature": "Es4DC...GAE="
    },
    {
      "type": "tool_use",
      "id": "toolu_123",
      "name": "weather",
      "input": {"location": "Paris"}
    }
  ]
}
```

## Tool Call Coexistence

A single assistant message can contain BOTH thinking blocks AND tool_use blocks.

The order matters:
1. Thinking block(s) come first
2. Then text block(s) or tool_use block(s)

Example response with thinking + tool_use:
```python
for block in response.content:
    if block.type == "thinking":
        print(f"Thinking: {block.thinking}")
    elif block.type == "tool_use":
        print(f"Tool: {block.name}")
```

## Model Gating

Extended thinking is supported on:
- `claude-sonnet-4-6` (and earlier `claude-sonnet-4-5`)
- `claude-opus-4-5` and later
- Not supported on Haiku models

Enable with:
```python
thinking={
    "type": "enabled",
    "budget_tokens": 10000
}
```

## Special Rules

1. **Signature preservation:** The `signature` field must be preserved exactly when passing thinking blocks back in message history.

2. **Context window management:** For Opus 4.5+ and Sonnet 4.6+, all previous thinking blocks are kept by default. For earlier models, because a non-tool-result user block was included, all previous thinking blocks are ignored and stripped from context.

3. **Tool choice limitation:** Tool use with thinking only supports `tool_choice: any`. It does not support providing a specific tool, `auto`, or any other values.

4. **Interleaved thinking:** On Claude 4 models, the model can think between tool calls (not just once at the start).

5. **Vercel AI Gateway normalization:** Gateway converts thinking blocks to `reasoning` string field and `reasoning_details` array for OpenAI-compatible API consumers.

## Streaming Event Sequence

For a response with thinking enabled:
```
event: message_start
event: content_block_start (type: thinking)
event: content_block_delta (type: thinking_delta)
... (multiple thinking deltas)
event: content_block_stop
event: content_block_start (type: text)
event: content_block_delta (type: text_delta)
... (multiple text deltas)
event: content_block_stop
event: message_stop
```
