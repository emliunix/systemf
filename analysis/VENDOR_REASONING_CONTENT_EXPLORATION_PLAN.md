# Project Plan: Vendor Reasoning Content Field Behavior Exploration

## Overview

**Parent Exploration:** `TAPE_ENTRY_TIMELINE_EXPLORATION.md`  
**Topic:** How major LLM vendors define the behavior, format, and lifecycle of reasoning content fields in their chat completion APIs.  
**Goal:** Produce vendor-specific facts and cross-vendor claims that inform how Bub/Republic should store and reconstruct reasoning content in tape entries.

---

## Principles

1. **Every finding must be stored in a file.** Raw API documentation, schema excerpts, SDK code snippets, and verbatim quotes from vendor docs must be saved as individual files under `analysis/vendor_reasoning_content/raw/`. The exploration markdown references these files; it does not inline them.
2. **Facts cite files, not URLs.** Every fact in the exploration must cite a file in the workspace (e.g., `analysis/vendor_reasoning_content/raw/openai_reasoning_schema.json`) plus the original URL. URLs rot; files persist.
3. **No hand-wavy claims.** Claims must reference ≥2 facts or prior claims. If a vendor behavior is unclear, record it as an open question, not a claim.

---

## Scope

### Vendors to Investigate (Priority Order)

| Priority | Vendor | Rationale |
|---|---|---|
| P0 | DeepSeek | Already referenced in parent; explicit `reasoning_content` field |
| P0 | OpenAI | o1/o3 series has `reasoning` field; de facto standard |
| P0 | Anthropic (Claude) | Uses `thinking` content blocks; different shape entirely |
| P1 | Google (Gemini) | `thinking` / `thought` fields in some models |
| P1 | xAI (Grok) | May have reasoning fields |
| P2 | Mistral / Cohere / etc. | If time permits |

### Dimensions to Investigate Per Vendor

For each vendor, extract facts across these dimensions:

1. **Field Name & Location** — What is the field called? Top-level on message object? Nested in content array? Delta field in streaming?
2. **Response Format** — Exact JSON shape in non-streaming chat completion response.
3. **Streaming Format** — How is reasoning delivered in SSE chunks? Separate `reasoning_content` delta? Part of `content` delta?
4. **Request Format** — When sending conversation history back, must reasoning content be included? Stripped? Sent as-is?
5. **Tool Call Coexistence** — Can a single assistant message contain BOTH reasoning content AND tool_calls? What is the exact shape?
6. **Model Gating** — Which models support reasoning? Is the field always present or model-dependent?
7. **Special Rules** — Any vendor-specific stripping, concatenation, or ordering rules.

---

## Phases

### Phase 1: Explore (Days 1–2)

**Step 1.1 — Vendor API Documentation Mining**

- [ ] Fetch DeepSeek chat completion API docs (official docs + any API reference)
- [ ] Fetch OpenAI chat completion API docs for o1/o3 reasoning models
- [ ] Fetch Anthropic Messages API docs for `thinking` / `redacted_thinking` blocks
- [ ] Fetch Google Gemini API docs for thinking/reasoning fields
- [ ] Fetch xAI Grok API docs if available

**Step 1.2 — Code & SDK Fact Extraction**

- [ ] Search OpenAI Python SDK for `reasoning` / `reasoning_content` field handling
- [ ] Search Anthropic Python SDK for `thinking` block handling
- [ ] Search any vendor SDKs for streaming delta parsing of reasoning fields
- [ ] Record exact JSON schemas from official API reference pages

**Step 1.3 — Cross-Vendor Comparison Matrix Draft**

- [ ] Create comparison table: Vendor × Dimension
- [ ] Identify contradictions or incompatibilities between vendors
- [ ] Note which vendors support reasoning+tool_calls in same message

**Deliverable:** `analysis/VENDOR_REASONING_CONTENT_{DATE}_{ID}_TEMP.md`  
Structure: Notes → Facts → Claims per `exploration/FORMAT.md`

### Phase 2: Validate (Day 3)

**Step 2.1 — Fact Verification**

- [ ] Verify every fact cites an exact URL or SDK file:line
- [ ] Re-fetch any docs that seem ambiguous; capture verbatim quotes
- [ ] Check for API version differences (beta vs v1 vs v2)

**Step 2.2 — Claim Verification**

- [ ] Ensure cross-vendor claims are backed by ≥2 vendor facts
- [ ] Verify no speculation in claims; all must trace to facts
- [ ] Check consistency with parent exploration (`TAPE_ENTRY_TIMELINE_EXPLORATION.md`)

**Step 2.3 — Review Against Parent Exploration Questions**

Validate specifically:
- [ ] DeepSeek: Does `reasoning_content` coexist with `tool_calls`? (Relates to parent Claim "DeepSeek Compatibility")
- [ ] OpenAI: Is reasoning stripped from history? (Relates to parent "Options" discussion)
- [ ] Anthropic: How do `thinking` blocks interact with `tool_use` blocks? (Relates to parent "Claude compatibility" open question)
- [ ] All vendors: Can reasoning content be preserved in tape and reconstructed faithfully?

### Phase 3: Synthesize & Merge (Day 4)

**Step 3.1 — Cross-Vendor Claims**

Draft claims such as:
- Claim X: "No vendor requires reasoning content to be sent back in history; all either ignore it or error if included." (or refute)
- Claim Y: "DeepSeek and OpenAI place reasoning content at the message level, while Anthropic uses content blocks."
- Claim Z: "Tool calls and reasoning can coexist on the same assistant message in [vendor list]."

**Step 3.2 — Recommendations for Tape Schema**

- [ ] Map vendor behaviors to the 3 options in parent exploration (store on tool_call, create assistant message, separate entry)
- [ ] Identify which option(s) are compatible with ALL investigated vendors
- [ ] Document any vendor-specific reconstruction rules needed in `_select_messages`

**Step 3.3 — Merge into Master**

- [ ] Merge validated session file into `analysis/VENDOR_REASONING_CONTENT_EXPLORATION.md`
- [ ] Archive temp file
- [ ] Update parent exploration with cross-references to new facts/claims

---

## Review Checkpoints

| Checkpoint | Reviewer | Criteria |
|---|---|---|
| After Phase 1 | Self / LLM | ≥2 facts per vendor; all facts have citations; no reasoning in facts section |
| After Phase 2 | Subagent (per `exploration/WORKFLOW.md`) | All claims validated VALIDATED Yes/No/Partial; no contradictions with parent exploration |
| After Phase 3 | User | Recommendations are actionable and map cleanly to parent exploration options |

---

## Dependencies

- **Input:** `analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md` (parent exploration, specifically Claims "DeepSeek Compatibility", "Claude compatibility", and Options 1–3)
- **Skill:** `exploration` skill loaded; `FORMAT.md` and `WORKFLOW.md` understood
- **Tools:** `webfetch`, `websearch`, `grep` (for SDK code), `read` (for existing docs)

## Open Questions to Answer

1. Does DeepSeek's `reasoning_content` appear in the same message object as `tool_calls`?
2. Does OpenAI's `reasoning` field appear in non-o1 models? Is it stripped when sending history?
3. Can Anthropic's `thinking` block and `tool_use` block appear in the same `content` array?
4. Do any vendors error if reasoning content is included in the request message history?
5. What is the SSE delta field name for reasoning in each vendor's streaming API?

---

## Subagent Schedule

Each phase is executed by a dedicated subagent. The supervisor (you) coordinates hand-offs.

### Subagent 1: DeepSeek + OpenAI Explorer
**Task:** Gather all facts for DeepSeek and OpenAI.  
**Working directory:** `/home/liu/Documents/systemf`  
**Read:** `analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md` + `.agents/skills/exploration/FORMAT.md`  
**Write:**
- `analysis/vendor_reasoning_content/raw/deepseek_api_docs.md` — fetched docs
- `analysis/vendor_reasoning_content/raw/openai_api_docs.md` — fetched docs
- `analysis/vendor_reasoning_content/raw/openai_sdk_reasoning_refs.md` — SDK grep results
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S1_TEMP.md` — Notes + Facts for DeepSeek + OpenAI

**Scope:**
- IN: `reasoning_content` field name, response format, streaming delta format, request/history handling, tool_call coexistence, model gating
- OUT: Implementation decisions, claims about other vendors

**Stop when:** 8+ facts per vendor with file citations, or 2+ dead-ends.

---

### Subagent 2: Anthropic + Google + xAI Explorer
**Task:** Gather all facts for Anthropic, Google, and xAI.  
**Working directory:** `/home/liu/Documents/systemf`  
**Read:** `analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md` + `.agents/skills/exploration/FORMAT.md` + output from Subagent 1 (for comparison context)  
**Write:**
- `analysis/vendor_reasoning_content/raw/anthropic_api_docs.md`
- `analysis/vendor_reasoning_content/raw/google_api_docs.md`
- `analysis/vendor_reasoning_content/raw/xai_api_docs.md`
- `analysis/vendor_reasoning_content/raw/anthropic_sdk_thinking_refs.md`
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S2_TEMP.md` — Notes + Facts for Anthropic + Google + xAI

**Scope:** Same dimensions as Subagent 1. Cross-reference any vendor interactions noted in Subagent 1 output.

**Stop when:** 6+ facts per vendor with file citations, or 2+ dead-ends.

---

### Subagent 3: Cross-Vendor Synthesizer
**Task:** Read all session files from Subagents 1 and 2, draft cross-vendor claims and tape-schema recommendations.  
**Working directory:** `/home/liu/Documents/systemf`  
**Read:**
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S1_TEMP.md`
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S2_TEMP.md`
- `.agents/skills/exploration/FORMAT.md`

**Write:**
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S3_TEMP.md` — Claims + Recommendations

**Deliverables:**
- Comparison matrix (Vendor × Dimension)
- Cross-vendor claims (≥3) with explicit references
- Tape schema recommendation mapping to parent exploration Options 1–3
- Open questions list (anything still ambiguous)

---

### Subagent 4: Validator
**Task:** Validate all facts and claims from Subagents 1–3.  
**Working directory:** `/home/liu/Documents/systemf`  
**Read:**
- `.agents/skills/exploration/REFERENCE.md` (must read first)
- All raw doc files in `analysis/vendor_reasoning_content/raw/`
- All session files (`S1`, `S2`, `S3`)

**Write:**
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_VALIDATION.md` — validation report per claim

**For each fact:**
- Verify the cited file exists and contains the quoted content
- Verify the original URL is recorded

**For each claim:**
- Annotate `VALIDATED Yes / No / Partial`
- Note any contradictions with parent exploration
- If any fact is wrong or claim is unsupported, flag for rework

**Stop when:** All claims have a validation annotation. If any claim fails, flag for return to Subagent 3 (or relevant explorer) for rework.

---

### Supervisor (You): Merge & Finalize
**Task:** Merge validated session files into master.  
**Read:**
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S1_TEMP.md`
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S2_TEMP.md`
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_S3_TEMP.md`
- `analysis/VENDOR_REASONING_CONTENT_{DATE}_VALIDATION.md`

**Write:**
- `analysis/VENDOR_REASONING_CONTENT_EXPLORATION.md` — merged master file
- Update `analysis/TAPE_ENTRY_TIMELINE_EXPLORATION.md` with cross-references

**Rules:**
- Validated claims → add to master
- Failed claims → mark as unconfirmed or drop
- Deduplicate facts across sessions
- Archive all `_TEMP.md` files after merge
