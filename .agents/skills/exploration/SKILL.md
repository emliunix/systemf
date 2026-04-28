---
name: exploration
description: Systematic codebase investigation with evidence-based claims. Use when (1) researching unknown systems, (2) tracing code paths, (3) documenting architecture discoveries.
---

# Exploration: Structured Codebase Research

## Core Concepts

- **Topic** — Investigation area with central question and scope boundaries
- **Claim** — Atomic, verifiable assertion with source attribution
- **Evidence** — Exact code snippets with `file:lines` references
- **Validated Notes** — Exploration files marked Validated; citable as secondary sources

## Document Structure

**Master file:** `{TOPIC_KEYWORD}_EXPLORATION.md`
**Session file:** `{TOPIC}_{DATE}_{ID}_TEMP.md` (extends existing master; merges back in Phase 3)

```markdown
# [Topic Title]

**Status:** In Progress | Validated | Archived
**Last Updated:** YYYY-MM-DD
**Central Question:** [What we're investigating]
**Topics:** [tag1, tag2, tag3]

## Planning

**Scopes:** [What this exploration covers and what is excluded]

**Entry Points:**
- `path/to/file:line` — [description]

**Assumptions:**
- [ ] [Assumption 1]
- [ ] [Assumption 2]

## Summary
Brief overview (2-3 paragraphs).

## Claims

### Claim N: [Title]
**Statement:** [Atomic assertion]
**Source:** `path/file:lines`
**Evidence:**
[Exact code snippet]
**Status:** Draft | Validated | Needs Revision
**Confidence:** High | Medium | Low
**Notes:** [Any issues or contradictions]

## Open Questions
- [ ] Unresolved item

## Related Topics
- [LINK_TO_OTHER.md]

## Unconfirmed Hypotheses
### Hypothesis N: [Title]
**Reason:** [Why it could not be validated]
**Source:** `path/file:lines` (if applicable)
```

Session files should flag any claims copied from the master file with **Copied:** Yes.

## Workflow

### Pre-Workflow: Create Todo Items (Mandatory)

Before any phase, create todo items to track progress. These are phase-tracking todos that maintain master control over the exploration:

- [ ] Explore: [topic] - [central questions, expand into multiple todo items]
- [ ] (**subagent**) Validate **mandatory**: verify claims
- [ ] (**subagent**) Merge: integrate into master file (**mandatory** if session file)

Update these as you progress. Mark completed immediately when done. Add sub-items if scope expands.

### Phase 1: Explore

#### Step 0: Master File Decision

| Condition | Action |
|---|---|
| No master file exists for topic | Create NEW master file, write directly |
| Master exists but topic is unrelated | Create NEW master file, write directly |
| Master exists and topic is related | Create SESSION file (TEMP), master stays as reference |

**Rules:**
- New master files skip Phase 3 (no merge needed)
- Session files always merge back to master in Phase 3

#### Step 1: Determine Work Strategy

**Case A — Prior work exists in current session:**
1. Structure findings into claim/evidence format
2. Write to appropriate file (master or session)
3. Proceed to Phase 2

**Case B — New exploration needed:**

**Step 1:** Create exploration file with:
- Central Question
- Scopes
- Entry Points (files, functions, line numbers)
- Assumptions
- Claims (Draft claims serve as detailed, focused assumptions to validate)

**Step 2:** Choose path:
- Plan is detailed enough → write findings directly (becomes Case A)
- Exploration required → spawn subagent

**Subagent template (Phase 1):**
```
You are an exploration subagent.
Working directory: [absolute path]

Input (READ-ONLY): [plan file path] + [related exploration files]
Output (WRITE TO): [target file path]

Scopes: [what to cover and what to ignore]
Entry points: [file:line references]

Deliverable: Populate Claims section using claim format (statement + source + evidence + confidence).
```

#### Termination Criteria

Stop exploring when:
- Central question is answered with evidence
- 3+ dead-ends (scope too broad — refine question)
- Recursion depth > 5 (circular dependencies)
- Claims become speculative (no source evidence)

If stuck: return partial findings + specific blockers. Don't guess.

### Phase 2: Validate (subagent required)

Verify claims against source code. Pass `REFERENCE.md` to the validation subagent.

**Subagent template:**
```
You are a validation subagent.
Working directory: [absolute path]

Target: [exploration file path]
Reference: [path to REFERENCE.md — read for claim quality standards and contradiction handling]

For each claim, verify:
1. Evidence exists at cited location
2. Claim logically follows from evidence
3. Consistent with other validated claims

Annotate each claim with:
- VALIDATED: Yes | No | Partial
- Source Check: Verified | Mismatch at line X
- Logic Check: Sound | Questionable
- Notes: [issues found]
```

> **Note:** If validation reveals incorrect claims, fix the claims and regenerate the todo items to re-validate before proceeding.

### Phase 3: Merge (subagent required, session files only)

Skip this phase for new master files. Only for session files extending an existing master.

**Subagent template:**
```
You are a merge subagent.
Working directory: [absolute path]

Source: [validated session file path]
Target: [master exploration file path — UPDATE THIS]

Merge rules:
- Validated claims → add to master Claims section
- Failed claims → add to "Unconfirmed Hypotheses" with reason
- Deduplicate against existing claims
- Mark obsolete claims as deprecated
- Update cross-references

Update metadata: Last Updated date, Status.
```

Post-merge: archive or delete the temp session file.
