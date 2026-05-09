# API Trace Analysis: Reasoning + Tool Calls in OpenAI and Anthropic Formats

**Date:** 2026-05-07
**Status:** No live API credentials available for DeepSeek. GLM API returned 429 (insufficient balance). Document based on official API documentation and any_llm source code analysis.

## Overview

This document traces the exact request/response formats for a two-turn conversation where:
1. **Turn 1**: User asks "Hello, please list the current directory and explain what you see." → LLM thinks, then calls `bash` tool
2. **Turn 2**: Tool result is returned → LLM thinks again, then generates final explanation

We analyze both **OpenAI Chat Completions** format and **Anthropic Messages API** format.

---

## Format 1: OpenAI Chat Completions (with reasoning extensions)

### Provider Support
- **OpenAI**: Native `gpt-4o`, `o1`, `o3` models with `reasoning_effort` parameter
- **DeepSeek**: `deepseek-reasoner` returns `reasoning_content` field
- **any_llm extension**: Adds `reasoning` field to `ChatCompletionMessage`

### Turn 1: User Input → Reasoning + Tool Call

#### Request

```json
{
  "model": "deepseek-reasoner",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant. Think step by step. Use the bash tool when you need to explore the filesystem."
    },
    {
      "role": "user",
      "content": "Hello, please list the current directory and explain what you see."
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
          "type": "object",
          "properties": {
            "command": {
              "type": "string",
              "description": "The bash command to execute"
            }
          },
          "required": ["command"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "max_tokens": 4096
}
```

#### Response (DeepSeek OpenAI-compatible)

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1715100000,
  "model": "deepseek-reasoner",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "",
        "reasoning_content": "The user wants me to list the current directory and explain what I see. I should use the bash tool to run `ls .` to get the directory listing first.",
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "bash",
              "arguments": "{\"command\":\"ls .\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 45,
    "completion_tokens": 128,
    "total_tokens": 173
  }
}
```

**Key fields:**
- `choices[0].message.content`: `""` (empty when tool calls are present)
- `choices[0].message.reasoning_content`: The model's reasoning process
- `choices[0].message.tool_calls`: Array of tool calls
- `finish_reason`: `"tool_calls"`

#### Tool Execution

```bash
$ ls .
```

**Result:**
```
README.md
src/
analysis/
.gitignore
```

---

### Turn 2: Tool Result → Reasoning + Final Reply

#### Request (with full history including reasoning)

```json
{
  "model": "deepseek-reasoner",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant. Think step by step. Use the bash tool when you need to explore the filesystem."
    },
    {
      "role": "user",
      "content": "Hello, please list the current directory and explain what you see."
    },
    {
      "role": "assistant",
      "content": "",
      "reasoning_content": "The user wants me to list the current directory and explain what I see. I should use the bash tool to run `ls .` to get the directory listing first.",
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "bash",
            "arguments": "{\"command\":\"ls .\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "name": "bash",
      "content": "README.md\nsrc/\nanalysis/\n.gitignore"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
          "type": "object",
          "properties": {
            "command": {
              "type": "string"
            }
          },
          "required": ["command"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "max_tokens": 4096
}
```

**Critical observation:** The `reasoning_content` from Turn 1 is included in the assistant message when there were tool calls. This is required for DeepSeek to maintain context.

#### Response

```json
{
  "id": "chatcmpl-yyy",
  "object": "chat.completion",
  "created": 1715100005,
  "model": "deepseek-reasoner",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The current directory contains:\n\n- **README.md** - Project documentation\n- **src/** - Source code directory\n- **analysis/** - Analysis files directory\n- **.gitignore** - Git ignore rules\n\nThis appears to be a software project with documentation, source code, and analysis folders.",
        "reasoning_content": "Now I have the directory listing. Let me analyze what each item is and provide a helpful explanation to the user.",
        "tool_calls": []
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 198,
    "completion_tokens": 95,
    "total_tokens": 293
  }
}
```

---

## DeepSeek-Specific Rules for OpenAI Format

From DeepSeek API documentation:

1. **For all assistant messages**: `reasoning_content` MUST be preserved in history when passing back assistant messages
2. **For non-tool-calling turns**: `reasoning_content` should NOT be included in subsequent request history
3. **any_llm handling**: The `reasoning` field is added to `ChatCompletionMessage` as an extension

---

## Format 2: Anthropic Messages API

### Provider Support
- **Anthropic**: Native Claude models with `thinking` parameter
- **DeepSeek**: Anthropic-compatible endpoint at `https://api.deepseek.com/anthropic`

### Turn 1: User Input → Thinking + Tool Use

#### Request

```json
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 4096,
  "system": "You are a helpful assistant. Think step by step. Use the bash tool when you need to explore the filesystem.",
  "messages": [
    {
      "role": "user",
      "content": "Hello, please list the current directory and explain what you see."
    }
  ],
  "tools": [
    {
      "name": "bash",
      "description": "Execute a bash command",
      "input_schema": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string",
            "description": "The bash command to execute"
          }
        },
        "required": ["command"]
      }
    }
  ],
  "thinking": {
    "type": "enabled",
    "budget_tokens": 1024
  }
}
```

#### Response

```json
{
  "id": "msg_01xxx",
  "type": "message",
  "role": "assistant",
  "model": "claude-sonnet-4-20250514",
  "content": [
    {
      "type": "thinking",
      "thinking": "The user wants me to list the current directory and explain what I see. I should use the bash tool to run `ls .` to get the directory listing first.",
      "signature": "Ep8DCkYICxgCKkC+WPygThZq0H4GdhmD+KxG3R..."
    },
    {
      "type": "tool_use",
      "id": "toolu_01abc",
      "name": "bash",
      "input": {
        "command": "ls ."
      }
    }
  ],
  "stop_reason": "tool_use",
  "usage": {
    "input_tokens": 45,
    "output_tokens": 128
  }
}
```

**Key fields:**
- `content`: Array of content blocks
- `content[0].type`: `"thinking"` - reasoning content
- `content[0].thinking`: The actual reasoning text
- `content[0].signature`: Required for Claude thinking blocks (must be preserved)
- `content[1].type`: `"tool_use"` - tool call
- `stop_reason`: `"tool_use"`

---

### Turn 2: Tool Result → Thinking + Final Reply

#### Request (with full history)

```json
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 4096,
  "system": "You are a helpful assistant. Think step by step. Use the bash tool when you need to explore the filesystem.",
  "messages": [
    {
      "role": "user",
      "content": "Hello, please list the current directory and explain what you see."
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "thinking",
          "thinking": "The user wants me to list the current directory and explain what I see. I should use the bash tool to run `ls .` to get the directory listing first.",
          "signature": "Ep8DCkYICxgCKkC+WPygThZq0H4GdhmD+KxG3R..."
        },
        {
          "type": "tool_use",
          "id": "toolu_01abc",
          "name": "bash",
          "input": {
            "command": "ls ."
          }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_01abc",
          "content": "README.md\nsrc/\nanalysis/\n.gitignore"
        }
      ]
    }
  ],
  "tools": [
    {
      "name": "bash",
      "description": "Execute a bash command",
      "input_schema": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string"
          }
        },
        "required": ["command"]
      }
    }
  ],
  "thinking": {
    "type": "enabled",
    "budget_tokens": 1024
  }
}
```

**Critical observation:** The entire `content` array from the assistant's previous turn must be included, including both `thinking` and `tool_use` blocks. The `signature` on thinking blocks must be preserved.

#### Response

```json
{
  "id": "msg_02yyy",
  "type": "message",
  "role": "assistant",
  "model": "claude-sonnet-4-20250514",
  "content": [
    {
      "type": "thinking",
      "thinking": "Now I have the directory listing. Let me analyze what each item is and provide a helpful explanation to the user.",
      "signature": "Fq9ECkYJDxgDKkD+XPygThZq0H4GdhmD+KxG3S..."
    },
    {
      "type": "text",
      "text": "The current directory contains:\n\n- **README.md** - Project documentation\n- **src/** - Source code directory\n- **analysis/** - Analysis files directory\n- **.gitignore** - Git ignore rules\n\nThis appears to be a software project with documentation, source code, and analysis folders."
    }
  ],
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 198,
    "output_tokens": 95
  }
}
```

---

## DeepSeek Anthropic Endpoint Specifics

From DeepSeek API documentation (`https://api-docs.deepseek.com/guides/anthropic_api`):

- Base URL: `https://api.deepseek.com/anthropic`
- Supports `thinking` content blocks
- When thinking is enabled, response includes `type: "thinking"` blocks
- **Notable**: DeepSeek's Anthropic endpoint maps unsupported models to `deepseek-chat`

---

## Comparison: OpenAI vs Anthropic Formats

| Aspect | OpenAI Chat Completions | Anthropic Messages |
|--------|------------------------|-------------------|
| **Reasoning field** | `reasoning_content` (string) | `thinking` block (object with `thinking` + `signature`) |
| **Tool calls** | `tool_calls` array on message | `tool_use` blocks in `content` array |
| **Tool results** | `role: "tool"` message with `tool_call_id` | `tool_result` block in user `content` array |
| **Message structure** | Single `content` string + `tool_calls` array | `content` is array of typed blocks |
| **History preservation** | Include `reasoning_content` in assistant message | Include full `content` array with `thinking` + `tool_use` |
| **System prompt** | `messages[0]` with `role: "system"` | Top-level `system` parameter |

---

## Implications for Tape Entry Design

### Current Tape Schema Issues

As documented in `TAPE_ENTRY_TIMELINE_EXPLORATION.md`:

1. **Tool-calling turns have no assistant `message` entry** - The assistant message is reconstructed from `tool_call` entry
2. **Reasoning storage is asymmetric**:
   - Normal turns: `reasoning_content` on `message` entry
   - Tool-call turns: Would need `reasoning_content` on `tool_call` entry

### Required Tape Entry Changes

For full API format fidelity, tape entries need to capture:

**OpenAI format:**
```json
{
  "kind": "tool_call",
  "payload": {
    "calls": [...],
    "reasoning_content": "..."
  }
}
```

**Anthropic format:**
```json
{
  "kind": "tool_call",
  "payload": {
    "content_blocks": [
      {"type": "thinking", "thinking": "...", "signature": "..."},
      {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
    ]
  }
}
```

### Recommendation

Store the **normalized any_llm format** in tape entries rather than provider-specific formats:
- `reasoning_content` field for reasoning (string)
- `tool_calls` array for tool calls
- Let `_select_messages` handle conversion to provider-specific formats

---

## Program for Live Trace Capture

See `analysis/api_trace_capture.py` for the trace capture program.

Usage:
```bash
# DeepSeek OpenAI format
export DEEPSEEK_API_KEY=...
python analysis/api_trace_capture.py --provider deepseek --format openai --model deepseek-reasoner

# DeepSeek Anthropic format
python analysis/api_trace_capture.py --provider deepseek --format anthropic --model deepseek-chat

# Anthropic native
export ANTHROPIC_API_KEY=...
python analysis/api_trace_capture.py --provider anthropic --format anthropic --model claude-sonnet-4-20250514
```

---

## Next Steps

1. Obtain DeepSeek API key to capture live traces
2. Verify actual response formats match documentation
3. Test edge cases:
   - Multiple tool calls in one turn
   - Streaming responses with reasoning
   - Error responses
4. Update tape schema to support reasoning_content on tool_call entries
