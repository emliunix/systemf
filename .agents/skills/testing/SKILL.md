---
name: testing
description: Test and debug scripts for MiniMax API, Bub integration, and bus connectivity testing
---

# Testing Scripts

Located in `scripts/` directory for testing specific integrations.

## MiniMax API Testing

### test_minimax_tools.py
Direct OpenAI SDK tests for MiniMax tool calling.

**Tests**: basic chat, tool calls, tool results with OpenAI format

```bash
uv run python scripts/test_minimax_tools.py
```

### test_minimax_format.py
Check MiniMax response format details.

**Purpose**: Dumps complete API response structure

```bash
uv run python scripts/test_minimax_format.py [API_KEY]
```

### test_republic_minimax.py
Test MiniMax through Republic client.

**Validates**: tool_calls() and raw response parsing

```bash
uv run python scripts/test_republic_minimax.py
```

## Bub Integration Testing

### test_bub_minimax_flow.py
Test Bub's LLM configuration flow.

**Tests**: settings loading, tape store, LLM client setup

```bash
uv run python scripts/test_bub_minimax_flow.py
```

### test_tape_tool_calls.py
Debug tape recording of tool calls.

**Checks**: What's actually stored on tape after tool calls

```bash
uv run python scripts/test_tape_tool_calls.py
```

## Bus Testing

### test_bus_client.py
WebSocket bus test client.

**Purpose**: Simulates Telegram messages via WebSocket

```bash
uv run python scripts/test_bus_client.py [message]
```

## Environment Setup

All test scripts automatically load `.env` file and configure paths. Ensure required API keys are set in `.env`:

```bash
# For MiniMax tests
BUB_AGENT_API_KEY=your_key_here
# or
MINIMAX_API_KEY=your_key_here

# For Telegram-related tests
BUB_BUS_TELEGRAM_TOKEN=your_token_here
```
