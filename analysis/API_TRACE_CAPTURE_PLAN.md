# API Trace Capture Plan

## Goal
Capture detailed request/response traces for LLM APIs to understand how reasoning content and tool calls are formatted in both OpenAI Chat Completions and Anthropic Messages API formats.

## Concrete Scenario
User says: "Hello, please list the current directory and explain what you see."

Expected LLM behavior:
1. Think about what to do
2. Call tool: `bash` with command `ls .`
3. Think about the results
4. Generate final reply with explanation

This requires a **two-turn** conversation:
- **Turn 1**: User prompt → LLM returns reasoning + tool_call
- **Turn 2**: User prompt + tool_result → LLM returns reasoning + final_text

## API Targets

### 1. OpenAI Chat Completions Format (via anyllm)
- Endpoint: Provider's OpenAI-compatible endpoint
- Format: `ChatCompletion` with `reasoning_content` extension
- Key fields to capture:
  - Request: `messages`, `tools`, `tool_choice`
  - Response: `choices[].message.content`, `choices[].message.reasoning`, `choices[].message.tool_calls`

### 2. DeepSeek OpenAI-Compatible Endpoint
- Base URL: `https://api.deepseek.com`
- Model: `deepseek-reasoner` or `deepseek-chat`
- Special behavior: DeepSeek includes `reasoning_content` in response but **should not** include it in subsequent request history for non-tool-calling turns

### 3. DeepSeek Anthropic Endpoint
- Base URL: `https://api.deepseek.com/anthropic`
- Format: Anthropic Messages API
- Key fields to capture:
  - Request: `messages`, `tools`, `thinking` parameter
  - Response: `content` blocks with `type: thinking`, `type: tool_use`, `type: text`

## Trace Capture Program Design

The program will:
1. Initialize anyllm client with detailed HTTP logging
2. Define a `bash` tool that runs `ls .`
3. **Turn 1**: Send user message, capture response (reasoning + tool_call)
4. Execute tool call, capture result
5. **Turn 2**: Send message history + tool_result, capture response (reasoning + final_text)
6. Log full request/response payloads for each turn

## Files to Create
- `analysis/api_trace_capture.py` - The trace capture program
- `analysis/API_TRACE_RESULTS.md` - Recorded traces and analysis

## Credentials Required
- DeepSeek API key for traces 2 and 3
- Current workspace has Zhipu AI (GLM) key only
- Need to obtain DeepSeek key or use mock data for format documentation

## Notes
- anyllm normalizes responses across providers, so we need to capture at the HTTP level or use provider-specific debug modes
- Alternative: Use raw `httpx`/`requests` to capture exact payloads
- For Anthropic format, use `anthropic` SDK directly or anyllm's Messages API
