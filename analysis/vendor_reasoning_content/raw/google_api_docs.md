# Google Gemini Thinking / Reasoning API Documentation

**Sources:**
- https://ai.google.dev/gemini-api/docs/thinking
- https://ai.google.dev/gemini-api/docs/thought-signatures
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking
- https://github.com/google-gemini/gemini-cli/issues/25808
- https://discuss.ai.google.dev/t/thinking-with-multi-turn-conversation/89803

---

## Field Name & Location

Google Gemini does NOT use a single `reasoning_content` field. Instead, reasoning is exposed through multiple mechanisms:

1. **Thought signatures:** `thoughtSignature` field within content `parts` (e.g., `text` or `functionCall` parts)
2. **Thought summaries:** Parts with `thought: true` boolean when `includeThoughts: true` is set
3. **Usage metadata:** `thoughts_token_count` in `usageMetadata`

## Response Format (Non-Streaming)

### With thought summaries enabled:

```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "text": "I need to calculate the risk. Let me think step-by-step...",
            "thought": true,
            "thought_signature": "<Signature_C>"
          },
          {
            "text": "The answer is 42.",
            "thought": false
          }
        ],
        "role": "model"
      },
      "finishReason": "STOP"
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 11,
    "candidatesTokenCount": 9,
    "thoughtsTokenCount": 1477,
    "totalTokenCount": 20
  }
}
```

### With function calling and thought signatures:

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

### Thought signature in text parts (no validation):

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

## Streaming Format

When streaming with `includeThoughts: true`:

```go
for chunk := range resp {
  for _, part := range chunk.Candidates.Content.Parts {
    if len(part.Text) == 0 {
      continue
    }
    if part.Thought {
      fmt.Printf("Thought: %s\n", part.Text)
    } else {
      fmt.Printf("Answer: %s\n", part.Text)
    }
  }
}
```

During streaming, thought signatures may be returned in a part with empty text content:
```json
{
  "text": "",
  "thoughtSignature": "<signature>"
}
```

## Request Format (Sending History Back)

The Gemini API is **stateless**, so thought context must be passed manually.

**For function calling:** You must return thought signatures from previous responses in subsequent requests.

Example request with thought signature:
```json
{
  "contents": [
    {
      "role": "user",
      "parts": [{"text": "Get my projects"}]
    },
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
    },
    {
      "role": "user",
      "parts": [
        {
          "functionResponse": {
            "name": "Get_Projects_List",
            "response": {"projects": []}
          }
        }
      ]
    }
  ]
}
```

**Starting a new conversation with thinking:**
Set `thought_signature: "INCLUDE_THOUGHTS_NEW_CONVERSATION"`

**Error when missing thought signature:**
```
[400 Bad Request] Function call is missing a thought_signature in functionCall parts.
This is required for tools to work correctly, and missing thought_signature may lead to degraded model performance.
```

## Tool Call Coexistence

A single model response can contain both thought parts and functionCall parts.

The thought context is maintained across multi-step function calls via thought signatures:

| Turn | Step | User Request | Model Response | FunctionResponse |
|------|------|--------------|----------------|------------------|
| 1 | 1 | request1 | FC1 + signature | FR1 |
| 1 | 2 | request1 + (FC1 + signature) + FR1 | FC2 + signature | FR2 |
| 1 | 3 | request2 + (FC2 + signature) + FR2 | text_output | None |

## Model Gating

Thinking models include:
- `gemini-3-flash-preview`
- `gemini-3-pro-preview`
- `gemini-3.1-pro-preview`
- `gemini-3.1-flash-lite`
- `gemini-2.5-pro`
- `gemini-2.5-flash`

Configuration via `thinkingConfig`:
```json
{
  "generationConfig": {
    "thinkingConfig": {
      "thinkingLevel": "HIGH",
      "includeThoughts": true
    }
  }
}
```

Levels:
- `MINIMAL`: Minimal thinking
- `LOW`: Fewer tokens for thinking (high-throughput tasks)
- `MEDIUM`: Balanced approach (Gemini 3 Flash, Gemini 3.1 Pro, Gemini 3.1 Flash-Lite only)
- `HIGH`: More tokens for thinking (default for Gemini 3 Pro and Gemini 3 Flash)

**Important:** Cannot use both `thinking_level` and legacy `thinking_budget` in same request (returns 400).

## Special Rules

1. **Statelessness:** The Gemini API is stateless, so the model treats every API request independently and doesn't have access to thought context from previous turns.

2. **Thought signatures for tool use:** Thought signatures are REQUIRED for function calling with thinking models. Missing signatures cause 400 errors.

3. **Thought summaries vs raw thoughts:** `includeThoughts` returns summarized versions of raw thoughts. Thinking levels and budgets apply to raw thoughts, not summaries.

4. **Non-functionCall parts:** Gemini may return `thought_signatures` in the final part of the response even in non-function-call parts.

5. **SDK handling:** Official Google Gen AI SDK handles thought signatures automatically when using standard chat history features.

6. **Gemini CLI bug:** There was a known issue where `thoughtSignature` was silently dropped from chat history in non-functionCall parts (fixed in later versions).
