# xAI Grok Reasoning API Documentation

**Sources:**
- https://docs.x.ai/developers/model-capabilities/text/reasoning
- https://docs.x.ai/developers/model-capabilities/legacy/chat-completions
- https://docs.x.ai/developers/model-capabilities/text/comparison
- https://docs.x.ai/developers/model-capabilities/text/streaming
- https://docs.aimlapi.com/api-references/text-models-llm/xai/grok-4
- https://github.com/langchain-ai/langchain/issues/34706

---

## Field Name & Location

xAI Grok uses **`reasoning_content`** as a top-level field on the message object in Chat Completions API responses.

This is similar to DeepSeek's approach but differs from Anthropic's content block array approach.

## Response Format (Non-Streaming)

### Chat Completions API:

```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1762343744,
  "model": "grok-4-fast-reasoning",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! I'm Grok, built by xAI...",
        "reasoning_content": "Thinking... Thinking... "
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 14,
    "completion_tokens_details": {
      "reasoning_tokens": 310
    },
    "total_tokens": 837
  }
}
```

The `message` object contains:
- `role`: "assistant"
- `content`: string - the final response text
- `reasoning_content`: string - the reasoning/thinking content

## Streaming Format

In streaming mode, reasoning content is delivered via `delta.reasoning_content`:

```python
for response, chunk in chat.stream():
    if chunk.reasoning_content:
        print(chunk.reasoning_content, end="", flush=True)
```

SSE chunks:
```
data: {"choices": [{"delta": {"reasoning_content": "Let me think...", "role": "assistant"}, ...}]}
```

Using the xAI SDK:
```python
for response, chunk in chat.stream():
    if chunk.reasoning_content:
        print(chunk.reasoning_content, end="", flush=True)
    if chunk.content:
        print(chunk.content, end="", flush=True)
```

## Request Format (Sending History Back)

When sending conversation history back, the assistant message can include `reasoning_content`.

Unlike DeepSeek, xAI does not seem to strictly require reasoning_content to be passed back (based on Vercel AI Gateway testing).

Example:
```json
{
  "messages": [
    {"role": "user", "content": "What is 2+2?"},
    {
      "role": "assistant",
      "content": "The answer is 4.",
      "reasoning_content": "The user is asking for a simple arithmetic operation..."
    },
    {"role": "user", "content": "Now multiply by 3"}
  ]
}
```

## Tool Call Coexistence

A single assistant message can contain BOTH `content` and `tool_calls`, and the `reasoning_content` field can coexist with both.

Example from xAI structured outputs docs:
```javascript
const completion = await client.chat.completions.create({
    model: "grok-4.20-reasoning",
    messages,
    tools,
});

const message = completion.choices[0].message;
// message can have both content and tool_calls
```

The cookbook example shows:
```python
return response.choices[0].message.content, response.choices[0].message.reasoning_content
```

This implies `reasoning_content` is available alongside `content` even when `tool_calls` are present.

## Model Gating

Reasoning models:
- `grok-4.20-reasoning`
- `grok-4-fast-reasoning`
- `grok-3-mini`

**Important limitation:** According to xAI's API comparison table:
> "Reasoning Models: Full support with encrypted reasoning content [in Responses API]. Limited - only `grok-3-mini` returns `reasoning_content` [in Chat Completions API]."

This means:
- `grok-3-mini`: Returns `reasoning_content` in Chat Completions
- `grok-4.20-reasoning`, `grok-4-fast-reasoning`: Use Responses API for full reasoning access; Chat Completions may not return `reasoning_content`

## Special Rules

1. **Timeout override:** Reasoning models require longer timeouts:
   ```python
   client = Client(
       api_key=os.getenv("XAI_API_KEY"),
       timeout=3600,  # Override default timeout
   )
   ```

2. **Responses API vs Chat Completions:** xAI has two APIs:
   - **Chat Completions (legacy):** Returns `reasoning_content` only for `grok-3-mini`
   - **Responses API:** Returns `reasoning.encrypted_content` with full support for all reasoning models

3. **Usage reporting:** Reasoning tokens are reported separately:
   ```json
   {
     "usage": {
       "completion_tokens": 14,
       "completion_tokens_details": {
         "reasoning_tokens": 310
       }
     }
   }
   ```

4. **LangChain compatibility issue:** There was a known issue where `reasoning_content` was dropped by ChatOpenAI wrapper in LangChain (fixed in PR #34705).

5. **Stateful conversations:** Responses API supports `previous_response_id` for stateful conversations; Chat Completions is stateless.
