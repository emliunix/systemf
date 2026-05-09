# OpenAI SDK Reasoning References

## any-llm-sdk Extension for Reasoning

Source: `/home/liu/Documents/systemf/.venv/lib/python3.14/site-packages/any_llm/types/completion.py`

### Extension of ChatCompletionMessage

```python
# Line 28-36
# OpenAI Completion API doesn't include reasoning information, so we need to extend the openai type

class Reasoning(BaseModel):
    content: str

class ChatCompletionMessage(OpenAIChatCompletionMessage):
    reasoning: Reasoning | None = None
    annotations: list[dict[str, Any]] | None = None
```

This shows that the any-llm-sdk explicitly adds a `reasoning` field to OpenAI's `ChatCompletionMessage` because the official SDK type does NOT include reasoning content.

### Extension of ChoiceDelta for streaming

```python
# Line 63-64
class ChoiceDelta(OpenAIChoiceDelta):
    reasoning: Reasoning | None = None
```

Similarly, the streaming delta type is extended with a `reasoning` field.

### ReasoningEffort type

```python
# Line 99
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "auto"]
```

### CompletionParams

```python
# Line 182
reasoning_effort: ReasoningEffort | None = "auto"
"""Reasoning effort level for models that support it. "auto" will map to each provider's default."""
```

## Republic Code References

Source: `/home/liu/Documents/systemf/republic/src/republic/core/execution.py`

### Mapping reasoning_effort to Responses API

```python
# Lines 412-420
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

This maps `reasoning_effort` (Chat Completions API parameter) to `reasoning.effort` (Responses API parameter).

Source: `/home/liu/Documents/systemf/republic/src/republic/clients/chat.py`

### Splitting reasoning_effort from kwargs

```python
# Lines 510-515
@staticmethod
def _split_reasoning_effort(kwargs: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
    if "reasoning_effort" not in kwargs:
        return None, kwargs
    request_kwargs = dict(kwargs)
    reasoning_effort = request_kwargs.pop("reasoning_effort", None)
    return reasoning_effort, request_kwargs
```

This extracts `reasoning_effort` from user-provided kwargs before passing to the core execution layer.

### Metadata-only item types in Responses API

```python
# Line 32
RESPONSES_METADATA_ONLY_ITEM_TYPES = frozenset({"reasoning", "compaction"})
```

In Republic's Responses API handling, `reasoning` items are treated as metadata-only (not displayed as output text).

## OpenAI Codex Transport

Source: `/home/liu/Documents/systemf/republic/src/republic/clients/openai_codex.py`

```python
# Line 15
DEFAULT_CODEX_INCLUDE = ("reasoning.encrypted_content",)
```

The Codex transport explicitly requests `reasoning.encrypted_content` to be included in responses.

## Test References

Source: `/home/liu/Documents/systemf/republic/tests/fakes.py`

```python
# Lines 238-251
def make_responses_reasoning_response(
    id="resp_reasoning_1",
    output=[SimpleNamespace(type="reasoning", id="rs_1", summary=[], content=None, status=None)],
    ...
)
```

Test fakes model Responses API reasoning items with `type="reasoning"`, `id`, `summary`, `content` fields.

Source: `/home/liu/Documents/systemf/republic/tests/test_responses_handling.py`

```python
# Lines 552-562
def test_chat_reasoning_effort_for_responses_is_mapped(fake_anyllm) -> None:
    llm.chat("Reply with ready", reasoning_effort="low")
    call = client.chat_completions.calls[0]
    assert call.get("reasoning") == {"effort": "low"}
    assert "reasoning_effort" not in call
```

This test verifies that `reasoning_effort="low"` is mapped to `reasoning={"effort": "low"}` for the Responses API.

## Summary

The OpenAI Python SDK and the any-llm-sdk both confirm:
1. OpenAI Chat Completions API does NOT natively expose reasoning content
2. The any-llm-sdk extends OpenAI types with a `reasoning` field for compatibility with providers that do expose reasoning (like DeepSeek)
3. Republic maps `reasoning_effort` to the appropriate format for each API (Chat Completions vs Responses)
4. The Responses API uses `reasoning` items with IDs that can be passed back for context preservation
