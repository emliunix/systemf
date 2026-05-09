# OpenAI API Reasoning Documentation

Sources:
- https://community.openai.com/t/chat-completion-api-with-reasoning-models/1281778
- https://developers.openai.com/api/docs/guides/reasoning
- https://developers.openai.com/api/docs/guides/migrate-to-responses
- https://developers.openai.com/cookbook/examples/responses_api/reasoning_items
- OpenAI Python SDK (installed in .venv)

## Chat Completions API

### No reasoning_content field

The official OpenAI Chat Completions API does NOT expose reasoning content in responses.

From OpenAI community forum (confirmed by OpenAI staff):
> "In the Chat Completions API, the model's reasoning is discarded after every API request. It is only possible to retain reasoning items in context using the stateful Responses API, with the `store` parameter set to `true`."

From any-llm-sdk (`any_llm/types/completion.py:28`):
> "OpenAI Completion API doesn't include reasoning information, so we need to extend the openai type"

### ChatCompletionMessage fields (OpenAI SDK)

From `/home/liu/Documents/systemf/.venv/lib/python3.14/site-packages/openai/types/chat/chat_completion_message.py`:
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

**NO `reasoning_content` field exists.**

### ChoiceDelta fields (OpenAI SDK, streaming)

From `/home/liu/Documents/systemf/.venv/lib/python3.14/site-packages/openai/types/chat/chat_completion_chunk.py`:
```python
class ChoiceDelta(BaseModel):
    content: Optional[str] = None
    function_call: Optional[ChoiceDeltaFunctionCall] = None
    refusal: Optional[str] = None
    role: Optional[Literal["developer", "system", "user", "assistant", "tool"]] = None
    tool_calls: Optional[List[ChoiceDeltaToolCall]] = None
```

**NO `reasoning_content` field in streaming deltas either.**

### reasoning_effort parameter

From `/home/liu/Documents/systemf/.venv/lib/python3.14/site-packages/openai/types/shared_params/reasoning.py`:
```python
class Reasoning(TypedDict, total=False):
    effort: Optional[ReasoningEffort]
    generate_summary: Optional[Literal["auto", "concise", "detailed"]]
    summary: Optional[Literal["auto", "concise", "detailed"]]
```

Supported values: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`

- `gpt-5.1` defaults to `none`
- Models before `gpt-5.1` default to `medium`
- `gpt-5-pro` defaults to `high`

### Request format for conversation history

When sending messages back to the Chat Completions API, you send standard assistant messages:
```json
{"role": "assistant", "content": "...", "tool_calls": [...]}
```

There is NO `reasoning_content` to include because the API never returns it.

## Responses API

### Reasoning items

From OpenAI docs:
> "Reasoning models like GPT-5.5 use internal reasoning tokens before producing a response. Reasoning models work better with the Responses API."

> "When doing function calling with a reasoning model in the Responses API, we highly recommend you pass back any reasoning items returned with the last function call (in addition to the output of your function)."

### Including reasoning content

From OpenAI migration guide:
> "add `[\"reasoning.encrypted_content\"]` to the include field."

### Stateful reasoning

From OpenAI cookbook:
> "Because the Responses API is stateful, these reasoning tokens persist: just include their IDs in subsequent messages to give future responses access to the same reasoning items."

> "If a turn includes a function call (which may require an extra round trip outside the API), you do need to include the reasoning items—either via `previous_response_id` or by explicitly adding the reasoning item to `input`."

### Streaming in Responses API

Event types for reasoning:
- `response.reasoning_text.delta` — Streaming reasoning text

## Models

Reasoning models: o3, o4-mini, GPT-5.5, GPT-5.1 (configurable), GPT-5-pro

Note: GPT-5.1 defaults to `none` reasoning effort, meaning no reasoning by default.

## Tool Calls Coexistence

In Chat Completions API, an assistant message can contain `tool_calls` and optionally `content`. The `content` is typically null when `tool_calls` are present.

In Responses API, the output can contain both `message` and `function_call` items. The `message` may contain reasoning about the tool call.
