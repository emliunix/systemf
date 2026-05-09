# DeepSeek Thinking Mode: Formal State Machine & Validation Plan

## Formal State Machine Definition

Let **M** be the append-only message array. Each message **m** has:
- **role** ∈ {system, user, assistant, tool}
- **reasoning_content** : optional string (only valid when role=assistant)
- **content** : string
- **tool_calls** : optional array (only valid when role=assistant)
- **tool_call_id** : string (only valid when role=tool)

### States

**S₀** = Initial state (empty message array)  
**Sᵤ** = After user message  
**Sₐ** = After assistant message with reasoning + content (finish_reason=stop)  
**Sₜ** = After assistant message with reasoning + tool_calls (finish_reason=tool_calls)  
**Sᵣ** = After tool result message  

### State Transitions

**T1: User Request**
```
S₀ → Sᵤ : append user_msg
Sₐ → Sᵤ : append user_msg  
Sᵣ → Sᵤ : append user_msg
```

**T2: Assistant Text Response**
```
Sᵤ → Sₐ : append assistant_msg
where assistant_msg = {
  role: "assistant",
  reasoning_content: string,
  content: string,
  finish_reason: "stop"
}
```

**T3: Assistant Tool Call Response**
```
Sᵤ → Sₜ : append assistant_msg
where assistant_msg = {
  role: "assistant", 
  reasoning_content: string,
  content: "",
  tool_calls: [...],
  finish_reason: "tool_calls"
}
```

**T4: Tool Result**
```
Sₜ → Sᵣ : append tool_msg
where tool_msg = {
  role: "tool",
  tool_call_id: id,
  content: result
}
```

**T5: Continue After Tool Result**
```
Sᵣ → Sₐ : append assistant_msg (text response)
Sᵣ → Sₜ : append assistant_msg (another tool call)
```

### Invariant (Critical Constraint)

**I1: Reasoning Preservation on Tool-Call Boundary**

For any valid state sequence containing T3 followed by T4:
```
Sᵤ --T3--> Sₜ --T4--> Sᵣ
```

The assistant message created by T3 MUST satisfy:
```
assistant_msg.reasoning_content ≠ null ∧ assistant_msg.reasoning_content ≠ ""
```

When reconstructing M for the API request at state Sᵣ, the message array must be:
```
M = [..., user_msg, assistant_msg(T3), tool_msg(T4)]
```

Where `assistant_msg(T3)` MUST include the `reasoning_content` field.

### Relaxed Constraints

**R1: Non-Tool-Call Turns**

For transitions T2 (assistant text response), reasoning_content is OPTIONAL in subsequent requests:
```
Sᵤ --T2--> Sₐ --T1--> Sᵤ'
```

When constructing M for Sᵤ', the assistant_msg from T2 MAY omit reasoning_content:
```
M = [..., user_msg, assistant_msg(without reasoning_content), user_msg']
```

**R2: Historical Tool-Call Turns**

For multi-turn conversations where a tool-call turn is followed by non-tool-call turns:
```
Sᵤ --T3--> Sₜ --T4--> Sᵣ --T2--> Sₐ --T1--> Sᵤ'
```

When constructing M for Sᵤ', the old assistant_msg from T3 (now buried in history) MAY omit reasoning_content if no new tool_result immediately follows it.

### Invalid State (Should Yield 400)

**Invalid: Missing reasoning_content on tool-call boundary**
```
Sᵤ → Sₜ' → Sᵣ
where Sₜ' assistant_msg lacks reasoning_content
```

This violates invariant I1 and should produce:
```
HTTP 400 Bad Request
error: "Missing required field: reasoning_content on assistant message with tool_calls"
```

---

## Validation Tests

### Test 1: Verify State T2 (Text Response)
**Purpose:** Confirm T2 transition works and returns reasoning_content.

**Initial:** S₀  
**Action:** T1(user: "What is 2+2?") → Sᵤ  
**Expected:** T2 returns assistant_msg with reasoning_content + content  
**Verify:** reasoning_content is present and non-empty

### Test 2: Verify Valid T3→T4 Sequence (Positive)
**Purpose:** Confirm I1 is satisfied.

**Sequence:**
```
S₀ → Sᵤ(user: "Calculate 2+2 with bash") 
    → Sₜ(assistant: reasoning="Let me calculate...", tool_calls=[bash])
    → Sᵣ(tool: result="4")
```

**API Request at Sᵣ:**
```json
[
  {"role": "user", "content": "Calculate 2+2 with bash"},
  {"role": "assistant", "reasoning_content": "Let me calculate...", "content": "", "tool_calls": [{"id": "call_1", ...}]},
  {"role": "tool", "tool_call_id": "call_1", "content": "4"}
]
```

**Expected:** 200 OK, assistant responds with final answer

### Test 3: Verify Invalid T3'→T4 Sequence (Negative)
**Purpose:** Confirm missing reasoning_content violates I1.

**Sequence:**
```
S₀ → Sᵤ(user: "Calculate 2+2 with bash")
    → Sₜ'(assistant: NO reasoning_content, tool_calls=[bash])  ← INVALID
    → Sᵣ(tool: result="4")
```

**API Request at Sᵣ:**
```json
[
  {"role": "user", "content": "Calculate 2+2 with bash"},
  {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", ...}]},
  {"role": "tool", "tool_call_id": "call_1", "content": "4"}
]
```

**Expected:** 400 Bad Request (per DeepSeek docs)

### Test 4: Text Turns Without Reasoning
**Purpose:** Confirm reasoning_content optional for T2→T1 transitions.

**Sequence:**
```
S₀ → Sᵤ(user: "What is Paris?")
    → Sₐ(assistant: reasoning="Paris is...", content="Paris")
    → Sᵤ'(user: "What about Berlin?")
```

**API Request at Sᵤ':**
```json
[
  {"role": "user", "content": "What is Paris?"},
  {"role": "assistant", "content": "Paris"},
  {"role": "user", "content": "What about Berlin?"}
]
```

**Note:** reasoning_content intentionally omitted from Sₐ message.  
**Expected:** 200 OK

### Test 5: Verify R2 (Historical Tool-Call Turn)
**Purpose:** Confirm old tool-call reasoning optional if not on immediate boundary.

**Sequence:**
```
S₀ → Sᵤ(user: "Calc 2+2")
    → Sₜ(assistant: reasoning="...", tool_calls=[bash])
    → Sᵣ(tool: result="4")
    → Sₐ(assistant: content="Answer is 4")
    → Sᵤ'(user: "Now calc 3+3")
```

**API Request at Sᵤ':**
```json
[
  {"role": "user", "content": "Calc 2+2"},
  {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", ...}]},
  {"role": "tool", "tool_call_id": "call_1", "content": "4"},
  {"role": "assistant", "content": "Answer is 4"},
  {"role": "user", "content": "Now calc 3+3"}
]
```

**Note:** reasoning_content omitted from Sₜ message (now historical).  
**Expected:** 200 OK (if R2 holds)

### Test 6: Multi-Turn Tool Chains
**Purpose:** Verify I1 across multiple sequential tool calls.

**Sequence:**
```
S₀ → Sᵤ(user: "List files, then read README")
    → Sₜ1(assistant: reasoning1, tool_calls=[list_files])
    → Sᵣ1(tool: files="README.md")
    → Sₜ2(assistant: reasoning2, tool_calls=[read_file])
    → Sᵣ2(tool: content="# Project...")
    → Sₐ(assistant: content="Here's the README...")
```

**API Request at Sᵣ2:**
```json
[
  {"role": "user", "content": "List files, then read README"},
  {"role": "assistant", "reasoning_content": "Let me list files...", "content": "", "tool_calls": [{"id": "call_1", ...}]},
  {"role": "tool", "tool_call_id": "call_1", "content": "README.md"},
  {"role": "assistant", "reasoning_content": "Now I'll read it...", "content": "", "tool_calls": [{"id": "call_2", ...}]},
  {"role": "tool", "tool_call_id": "call_2", "content": "# Project..."}
]
```

**Negative variant:** Drop reasoning_content from Sₜ2 (the most recent assistant before tool_result).  
**Expected:** 400 (if I1 enforced)

---

## Test Parameters

**Model:** `deepseek-v4-pro`  
**Thinking mode:** Explicitly enabled
```json
{
  "model": "deepseek-v4-pro",
  "thinking": {"type": "enabled"},
  "reasoning_effort": "high"
}
```

**Tools:** Single `bash` tool for consistency.

**Validation criteria:**
- Test 1: Pass (baseline)
- Test 2: 200 OK (positive case)
- Test 3: 400 (negative case - confirms I1)
- Test 4: 200 OK (relaxed constraint)
- Test 5: 200 OK (historical turn)
- Test 6: 200 OK (multi-tool positive), 400 (multi-tool negative)

---

## Test Results

**Run Date:** 2025-05-07  
**Model:** `deepseek-v4-pro`  
**Test File:** `analysis/test_state_machine_validation.py`

| Test | Description | Status | Details |
|------|-------------|--------|---------|
| **1** | T2 Text Response with Reasoning | **PASS** | `reasoning_content` present in response, `finish_reason=stop` |
| **2** | Valid T3→T4 (with reasoning) | **PASS** | 200 OK, assistant provides final answer after tool result |
| **3** | Invalid T3'→T4 (no reasoning) | **PASS** | **400 Error**: "The `reasoning_content` in the thinking mode must be passed back to the API." |
| **4** | Text without reasoning | **PASS** | 200 OK, but reasoning SHOULD be included for ALL assistant messages |
| **5** | Historical assistant (before last user) | **PASS** | 200 OK, historical assistant may drop reasoning |
| **6a** | Multi-tool positive (both with reasoning) | **PASS** | 200 OK, multi-turn tool chains work with all reasoning preserved |
| **6b** | Multi-tool negative (drop recent reasoning) | **PASS** | **400 Error**, confirms I1 enforced on immediate boundary |
| **6c** | Multi-tool mixed (drop old reasoning only) | **FAIL** | **400 Error** — I1 is strictly enforced on ALL assistant messages in active context |

### Key Findings

1. **I1 is STRICTLY enforced**: ALL assistant messages MUST include `reasoning_content`.
2. **Historical optimization**: Assistant messages before the last user message MAY drop reasoning, but this is not guaranteed by the API.
3. **R2 is PARTIAL**: Historical tool-call turns CAN be omitted ONLY if they are not followed by a tool result in the same request. If a historical tool-call message is in the message array, it MUST have `reasoning_content`.
4. **Error message** (consistent across all violations): `"The \`reasoning_content\` in the thinking mode must be passed back to the API."`

### Revised Invariants

**I1 (Strict):** For ALL assistant messages:
```
∀m ∈ M : m.role = "assistant" ⟹ m.reasoning_content ≠ null ∧ m.reasoning_content ≠ ""
```

**R1 (Historical optimization):** Assistant messages before the last user message MAY drop reasoning to save tokens, but this is not guaranteed by the API:
```
m.role = "assistant" ∧ m.before_last_user ⟹ m.reasoning_content optional (optimization)
```

**R2 (Active context):** Assistant messages after the last user message MUST preserve reasoning:
```
m.role = "assistant" ∧ m.after_last_user ⟹ m.reasoning_content required
```
