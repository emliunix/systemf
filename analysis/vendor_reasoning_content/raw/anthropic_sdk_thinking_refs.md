# Anthropic SDK Thinking Block References

**Local SDK Status:** Anthropic SDK is NOT installed in the local `.venv`. No local SDK files were found.

**Source:** Findings compiled from web research and Tavily search results.

---

## SDK Thinking Block Types

From the Anthropic Python SDK documentation and community sources:

### Thinking Block
```python
{
    "type": "thinking",
    "thinking": "Let me analyze this step by step...",
    "signature": "WaUjzkypQ2mUEVM36O2TxuC06KN8xyfbJwyem2dw3URve/op91XWHOEBLLqIOMfFG/UvLEczmEsUjavL...."
}
```

### Redacted Thinking Block
```python
{
    "type": "redacted_thinking",
    "data": "..."
}
```

## SDK Usage Example

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=16000,
    thinking={
        "type": "enabled",
        "budget_tokens": 10000
    },
    messages=[
        {
            "role": "user",
            "content": "Are there an infinite number of prime numbers such that n mod 4 == 3?",
        }
    ],
)

# The response contains summarized thinking blocks and text blocks
for block in response.content:
    if block.type == "thinking":
        print(f"\nThinking summary: {block.thinking}")
        if hasattr(block, 'signature') and block.signature:
            print(f"[Signature available: True]")
    elif block.type == "redacted_thinking":
        print(f"\nRedacted thinking block")
        if hasattr(block, 'data'):
            print(f"[Data length: {len(block.data)}]")
    elif block.type == "text":
        print(f"\nResponse: {block.text}")
```

## Streaming SDK Usage

```python
with client.messages.stream(
    model="claude-sonnet-4-6",
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 10000},
    messages=[{"role": "user", "content": "What is the greatest common divisor of 1071 and 462?"}],
) as stream:
    thinking_started = False
    response_started = False
    
    for event in stream:
        if event.type == "content_block_start":
            print(f"\nStarting {event.content_block.type} block...")
        elif event.type == "content_block_delta":
            if event.delta.type == "thinking_delta":
                if not thinking_started:
                    print("Thinking: ", end="", flush=True)
                    thinking_started = True
                print(event.delta.thinking, end="", flush=True)
            elif event.delta.type == "signature_delta":
                # Signature arrives as a delta event
                pass
            elif event.delta.type == "text_delta":
                if not response_started:
                    print("\nResponse: ", end="", flush=True)
                    response_started = True
                print(event.delta.text, end="", flush=True)
```

## Tool Use with Thinking

```python
# First request - Claude thinks once before all tool calls
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 10000},
    tools=[calculator_tool, database_tool],
    messages=[{
        "role": "user",
        "content": "What's the total revenue if we sold 150 units..."
    }]
)

# Response includes thinking followed by tool uses
print("First response:")
for block in response.content:
    if block.type == "thinking":
        print(f"Thinking (summarized): {block.thinking}")
    elif block.type == "tool_use":
        print(f"Tool use: {block.name}")

# Continue with tool result - include thinking block
continuation = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 10000},
    tools=[weather_tool],
    messages=[
        {"role": "user", "content": "What's the weather in Paris?"},
        {"role": "assistant", "content": [thinking_block, tool_use_block]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_block.id, "content": "22°C, sunny"}
        ]},
    ],
)
```

## Key SDK Behaviors

1. **Signature field:** The SDK exposes `signature` as an attribute on thinking blocks
2. **Redacted thinking:** Triggered by special test string or content policy - returns `redacted_thinking` blocks with `data` field instead of `thinking` text
3. **Content array:** Thinking blocks are part of the `content` array, not a separate top-level field
4. **Tool use coexistence:** Assistant message content array contains thinking blocks followed by tool_use blocks
