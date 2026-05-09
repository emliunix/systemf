# Thinking Mode | DeepSeek API Docs

URL: https://api-docs.deepseek.com/guides/thinking_mode

## Thinking Mode Toggle and Effort Control

Control Parameter (OpenAI Format): `{"thinking": {"type": "enabled/disabled"}}`
Thinking Effort Control: `{"reasoning_effort": "high/max"}` or `{"output_config": {"effort": "high/max"}}`

- The thinking toggle defaults to `enabled`
- In thinking mode, the default effort is `high` for regular requests; for some complex agent requests (such as Claude Code, OpenCode), effort is automatically set to `max`
- In thinking mode, for compatibility, `low` and `medium` are mapped to `high`, and `xhigh` is mapped to `max`

When using the OpenAI SDK, you need to pass the `thinking` parameter within `extra_body`:
```python
response = client.chat.completions.create(
  model="deepseek-v4-pro",
  reasoning_effort="high",
  extra_body={"thinking": {"type": "enabled"}}
)
```

## Input and Output Parameters

Thinking mode does not support the `temperature`, `top_p`, `presence_penalty`, or `frequency_penalty` parameters. Setting these parameters will not trigger an error but will also have no effect.

In thinking mode, the chain-of-thought content is returned via the `reasoning_content` parameter, at the same level as `content`.

When concatenating subsequent turns, you can selectively return `reasoning_content` to the API:

- Between two `user` messages, if the model **did not perform a tool call**, the intermediate assistant's `reasoning_content` does not need to participate in the context concatenation. If passed to the API in subsequent turns, it will be ignored.
- Between two `user` messages, if the model **performed a tool call**, the intermediate assistant's `reasoning_content` must participate in the context concatenation and must be **passed back to the API** in all subsequent user interaction turns.

## Multi-turn Conversation

In each turn of the conversation, the model outputs the CoT (`reasoning_content`) and the final answer (`content`). If there is no tool call, the CoT content from previous turns will not be concatenated into the context in the next turn.

### Sample Code (Non-streaming)

```python
from openai import OpenAI
client = OpenAI(api_key="<DeepSeek API Key>", base_url="https://api.deepseek.com")

# Turn 1
messages = [{"role": "user", "content": "9.11 and 9.8, which is greater?"}]
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=messages,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
)
reasoning_content = response.choices[0].message.reasoning_content
content = response.choices[0].message.content

# Turn 2
# The reasoning_content will be ignored by the API
messages.append(response.choices[0].message)
messages.append({'role': 'user', 'content': "How many Rs are there in the word 'strawberry'?"})
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=messages,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
)
```

### Sample Code (Streaming)

```python
from openai import OpenAI
client = OpenAI(api_key="<DeepSeek API Key>", base_url="https://api.deepseek.com")

# Turn 1
messages = [{"role": "user", "content": "9.11 and 9.8, which is greater?"}]
response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=messages,
    stream=True,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
)
reasoning_content = ""
content = ""
for chunk in response:
    if chunk.choices[0].delta.reasoning_content:
        reasoning_content += chunk.choices[0].delta.reasoning_content
    else:
        content += chunk.choices[0].delta.content

# Turn 2
# The reasoning_content will be ignored by the API
messages.append({"role": "assistant", "reasoning_content": reasoning_content, "content": content})
messages.append({'role': 'user', 'content': "How many Rs are there in the word 'strawberry'?"})
```

## Tool Calls

The DeepSeek model's thinking mode supports tool calls. Before outputting the final answer, the model can perform multiple turns of reasoning and tool calls to improve the quality of the response.

Unlike turns in thinking mode that do not involve tool calls, for turns that do perform tool calls, the `reasoning_content` must be fully passed back to the API in all subsequent requests.

If your code does not correctly pass back `reasoning_content`, the API will return a 400 error.

### Sample Code for Tool Calls in Thinking Mode

```python
import os
import json
from openai import OpenAI
from datetime import datetime

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_date",
            "description": "Get the current date",
            "parameters": { "type": "object", "properties": {} },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather of a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": { "type": "string", "description": "The city name" },
                    "date": { "type": "string", "description": "The date in format YYYY-mm-dd" },
                },
                "required": ["location", "date"]
            },
        }
    },
]

def run_turn(turn, messages):
    sub_turn = 1
    while True:
        response = client.chat.completions.create(
            model='deepseek-v4-pro',
            messages=messages,
            tools=tools,
            reasoning_effort="high",
            extra_body={ "thinking": { "type": "enabled" } },
        )
        messages.append(response.choices[0].message)
        reasoning_content = response.choices[0].message.reasoning_content
        content = response.choices[0].message.content
        tool_calls = response.choices[0].message.tool_calls
        print(f"Turn {turn}.{sub_turn}\n{reasoning_content=}\n{content=}\n{tool_calls=}")
        
        if tool_calls is None:
            break
        
        for tool in tool_calls:
            # ... execute tool ...
            messages.append({
                "role": "tool",
                "tool_call_id": tool.id,
                "content": tool_result,
            })
        sub_turn += 1
```

Note: `response.choices[0].message` contains all necessary fields for the assistant message, including `content`, `reasoning_content`, and `tool_calls`.

This is equivalent to:
```python
messages.append({
    'role': 'assistant',
    'content': response.choices[0].message.content,
    'reasoning_content': response.choices[0].message.reasoning_content,
    'tool_calls': response.choices[0].message.tool_calls,
})
```

In Turn 2 request, we still pass the `reasoning_content` generated in Turn 1 to the API.

## Sample Output

```
Turn 1.1
reasoning_content="The user is asking about the weather in Hangzhou tomorrow. I need to get tomorrow's date first, then call the weather function."
content="Let me check tomorrow's weather in Hangzhou for you. First, let me get tomorrow's date."
tool_calls=[ChatCompletionMessageFunctionToolCall(id='call_00_kw66qNnNto11bSfJVIdlV5Oo', function=Function(arguments='{}', name='get_date'), type='function', index=0)]

Turn 1.2
reasoning_content="Today is 2026-04-19, so tomorrow is 2026-04-20. Now I'll call the weather function for Hangzhou."
content=''
tool_calls=[ChatCompletionMessageFunctionToolCall(id='call_00_H2SCW6136vWJGq9SQlBuhVt4', function=Function(arguments='{"location": "Hangzhou", "date": "2026-04-20"}', name='get_weather'), type='function', index=0)]

Turn 1.3
reasoning_content='The weather result is in. Let me share this with the user.'
content="Here's the weather forecast for **Hangzhou tomorrow..."
tool_calls=None
```

## Key Rules

1. **No tool calls**: `reasoning_content` is returned but can be ignored when sending history back. It will be ignored by the API.
2. **With tool calls**: `reasoning_content` MUST be passed back in all subsequent requests. Omitting it causes a 400 error.
3. **Tool call + reasoning coexistence**: A single assistant message can contain `content`, `reasoning_content`, and `tool_calls` simultaneously.
4. **Multi-turn persistence**: `reasoning_content` from tool-calling turns must persist across all future turns, even new user questions.
