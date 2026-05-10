# Plan: Provider-specific Reasoning Strategy Settings

## Background

`TapeContext` now has a `reasoning_strategy` field that controls how `reasoning_content` is pruned from assistant messages before sending to the LLM. The strategies are:
- `FULL` — keep all reasoning
- `PRUNE` — strip all reasoning (default)
- `LAST_TURN_ONLY` — keep only the last assistant turn's reasoning
- `TOOLCALLS_ONLY` — keep reasoning only for turns that involved tool calls

The user wants this configurable via Bub settings, provider-specific, alongside existing provider-specific settings like `api_key` and `api_base`.

## Already Done

1. ✅ Added `reasoning_strategy: str | dict[str, str] | None` to `AgentSettings` with `provider_specific("reasoning_strategy")` default factory
2. ✅ Added `Agent._resolve_reasoning_strategy(provider)` method
3. ✅ Wired it into `Agent._prepare_turn()` to update `session._context` per turn

## Remaining Work

### Task 1: Add unit tests for `_resolve_reasoning_strategy`

**File:** `bub/tests/test_builtin_agent.py`

Test cases needed:
- Global string setting → returns that strategy
- Dict setting with matching provider → returns provider-specific strategy
- Dict setting with no matching provider, no default → returns PRUNE
- Dict setting with no matching provider, has "default" key → returns default strategy
- Invalid strategy string → returns PRUNE (graceful fallback)
- None setting → returns PRUNE

### Task 2: Integration test — verify context is updated per turn

**File:** `bub/tests/test_builtin_agent.py`

Add a test that verifies `_prepare_turn` updates `session._context.reasoning_strategy` based on the resolved provider.

### Task 3: Documentation

**File:** `bub/docs/` or inline docstrings

Add a brief note in `AgentSettings` docstring or a settings documentation page explaining the `reasoning_strategy` option and its valid values.

## Implementation Details

### Test Strategy

```python
def test_resolve_reasoning_strategy(self) -> None:
    # Test with string
    agent.settings = AgentSettings.model_construct(reasoning_strategy="full")
    assert agent._resolve_reasoning_strategy("openai") == ReasoningStrategy.FULL
    
    # Test with dict, matching provider
    agent.settings = AgentSettings.model_construct(
        reasoning_strategy={"openai": "full", "anthropic": "last_turn_only"}
    )
    assert agent._resolve_reasoning_strategy("openai") == ReasoningStrategy.FULL
    assert agent._resolve_reasoning_strategy("anthropic") == ReasoningStrategy.LAST_TURN_ONLY
    
    # Test with dict, no match → PRUNE
    assert agent._resolve_reasoning_strategy("deepseek") == ReasoningStrategy.PRUNE
    
    # Test with dict, has default key
    agent.settings = AgentSettings.model_construct(
        reasoning_strategy={"default": "tool_calls_only", "openai": "full"}
    )
    assert agent._resolve_reasoning_strategy("deepseek") == ReasoningStrategy.TOOLCALLS_ONLY
    
    # Test invalid → PRUNE
    agent.settings = AgentSettings.model_construct(reasoning_strategy="invalid")
    assert agent._resolve_reasoning_strategy("openai") == ReasoningStrategy.PRUNE
    
    # Test None → PRUNE
    agent.settings = AgentSettings.model_construct(reasoning_strategy=None)
    assert agent._resolve_reasoning_strategy("openai") == ReasoningStrategy.PRUNE
```

### Context Update Verification

The `_prepare_turn` method already updates `session._context`. We just need to verify this happens in a test by checking `session._context.reasoning_strategy` after `_prepare_turn` returns.

## Risk Assessment

- **Low risk** — the feature is additive, existing behavior (PRUNE default) is preserved
- The `_resolve_reasoning_strategy` method has graceful fallback to PRUNE for invalid values
- No breaking changes to existing APIs

## Dependencies

- None — all republic changes are already committed
- This is purely a bub-side feature
