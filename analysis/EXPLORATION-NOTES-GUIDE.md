# Exploration Notes Guide

This guide defines the standard for maintaining exploration notes when researching GHC's codebase.

## Core Entities

### Topic
A coherent area of investigation with a specific focus question. Examples:
- "How does GHCi resolve names in the REPL?"
- "How does the Home Package Table store compiled modules?"
- "How do TyCon and DataCon reference each other?"

A topic has:
- **Central question** - What we're trying to understand
- **Scope boundaries** - What's in/out of scope
- **Key files** - Primary source locations to examine

### Claim
Any assertion about how the system works. Every claim must be:
- **Atomic** - One specific fact, not compound
- **Verifiable** - Can be confirmed by reading source code
- **Attributed** - Linked to specific source location

**Claim Format:**
```markdown
**Claim:** Brief statement of fact
**Source:** `compiler/GHC/Module/File.hs:line-range`
**Evidence:**
```haskell
-- Exact code snippet supporting the claim
```
```

### Evidence
Source code that proves the claim. Requirements:
- **Minimal** - Just enough context to understand
- **Exact** - Copy-pasted from source, not paraphrased
- **Located** - File path and line numbers
- **Stable** - Prefer core API over implementation details

**Evidence Types:**
1. **Definition** - Where a type/function is defined
2. **Usage** - Where it's called/used
3. **Documentation** - Comments explaining design intent

## File Naming Convention

Exploration notes are stored in `/home/liu/Documents/bub/upstream/ghc/analysis/`

**Format:** `{TOPIC_KEYWORD}_EXPLORATION.md`

Examples:
- `INTERACTIVE_CONTEXT_EXPLORATION.md`
- `NAME_RESOLUTION_EXPLORATION.md`
- `HPT_MODULE_STORAGE_EXPLORATION.md`

## Document Structure

Each exploration note file follows this template:

```markdown
# [Topic Title]

**Status:** {In Progress | Validated | Archived}
**Last Updated:** YYYY-MM-DD
**Central Question:** [What we're investigating]

## Summary

Brief overview of findings (2-3 paragraphs max).

## Claims

### Claim 1: [Brief Title]
**Statement:** [Specific assertion]
**Source:** `compiler/GHC/Module/File.hs:line-range`
**Evidence:**
```haskell
[Code snippet]
```
**Implications:** [What this means for the larger system]

### Claim 2: [Brief Title]
...

## Open Questions

- [ ] Unresolved question 1
- [ ] Unresolved question 2

## Related Topics

- [LINK_TO_OTHER_EXPLORATION.md]
```

## Subagent Exploration Workflow

When a topic is too complex for single-session exploration, use the multi-stage workflow.

### The Single Channel Principle

**CRITICAL:** The subagent tool call is the **only** communication channel. Once spawned, the subagent cannot ask clarifying questions or request additional context. All information required for the task must be provided in the initial prompt.

**Principle:** Communicate as if writing a letter to someone who knows nothing about the project. The subagent receives:
- No prior context from your session
- No access to files you haven't explicitly listed
- No knowledge of previous subagent work unless you include it

**Consequence of insufficient context:** The subagent will either:
- Waste time exploring unrelated areas
- Make incorrect assumptions
- Return incomplete or incorrect findings
- Require spawning another subagent (inefficient)

### Three-Stage Process

```
Stage 1: EXPLORE
    Create temporary output file
    Spawn exploration subagent
    Write findings to temporary file

Stage 2: VALIDATE
    Spawn validation subagent
    Check evidence and claims
    Verify against source code

Stage 3: MERGE
    Spawn merge subagent
    Integrate validated findings
    Update master exploration file
```

### Subagent Content Checklists

Each stage requires specific content to be passed via the subagent tool call. Use these checklists to ensure completeness.

#### Stage 1: Exploration Subagent Checklist

**MUST INCLUDE in prompt:**

- [ ] **Role Definition**
  - "You are an exploration subagent..."
  - Clear statement of purpose

- [ ] **Input Files (Absolute Paths)**
  - Master exploration file: `/home/liu/Documents/bub/upstream/ghc/analysis/MASTER_FILE.md`
  - Related exploration files (if applicable)
  - Explicit: "READ-ONLY - do not modify"

- [ ] **Output File (Absolute Path)**
  - Temp file: `/home/liu/Documents/bub/upstream/ghc/analysis/MASTER_YYYY-MM-DD_X_TEMP.md`
  - Explicit: "WRITE TO THIS FILE"
  - Template or format specification

- [ ] **Topic Definition**
  - Specific aspect being explored
  - Central question to answer
  - Why this matters (context)

- [ ] **Entry Point Specification**
  - File path: `compiler/GHC/Module/File.hs`
  - Function/type name
  - Line number range (approximate is OK)
  - How to find it (search terms, patterns)

- [ ] **Scope Boundaries**
  - IN: Explicit list of what to cover
  - OUT: Explicit list of what to ignore
  - Time/depth limits (e.g., "trace 2-3 levels deep")

- [ ] **Deliverable Requirements**
  - Claim format template
  - Required sections in output
  - Metadata to include (date, session ID, focus)

- [ ] **Working Directory**
  - Base path: `/home/liu/Documents/bub/upstream/ghc/`
  - Where to look for source files

#### Stage 2: Validation Subagent Checklist

**MUST INCLUDE in prompt:**

- [ ] **Role Definition**
  - "You are a validation subagent..."
  - Purpose: verify evidence and logic

- [ ] **Target File (Absolute Path)**
  - Draft file: `/home/liu/Documents/bub/upstream/ghc/analysis/MASTER_YYYY-MM-DD_X_TEMP.md`
  - Explicit: "READ AND ANNOTATE THIS FILE"

- [ ] **Validation Criteria**
  - Evidence verification requirements
  - Logic check criteria
  - Confidence assessment rubric

- [ ] **Annotation Requirements**
  - Per-claim validation fields to add
  - Summary section format
  - Recommendation categories

- [ ] **Source Access**
  - Working directory: `/home/liu/Documents/bub/upstream/ghc/`
  - How to verify source locations

- [ ] **Output Specification**
  - Update the same temp file
  - Add validation annotations
  - Do not create new files

#### Stage 3: Merge Subagent Checklist

**MUST INCLUDE in prompt:**

- [ ] **Role Definition**
  - "You are a merge subagent..."
  - Purpose: integrate validated findings

- [ ] **Source File (Absolute Path)**
  - Validated draft: `/home/liu/Documents/bub/upstream/ghc/analysis/MASTER_YYYY-MM-DD_X_TEMP.md`
  - Explicit: "READ THIS FILE for source material"

- [ ] **Target File (Absolute Path)**
  - Master file: `/home/liu/Documents/bub/upstream/ghc/analysis/MASTER_EXPLORATION.md`
  - Explicit: "UPDATE THIS FILE"
  - "This is the primary deliverable"

- [ ] **Validation Summary**
  - Which claims passed validation
  - Which claims failed (and why)
  - Recommended actions per claim

- [ ] **Merge Rules**
  - How to handle validated claims
  - How to handle failed claims
  - How to handle contradictions
  - Deduplication requirements

- [ ] **Metadata Updates Required**
  - Last Updated date
  - Status field
  - Cross-reference updates

- [ ] **Post-Merge Actions**
  - What to do with temp file (archive/delete)
  - Any notifications needed

### Stage 1: Exploration

**Create Temporary Output File**

```bash
# Naming convention: {MASTER_FILE_BASE}_{DATE}_{SESSION_ID}_TEMP.md
# Example: INTERACTIVE_CONTEXT_2024-03-28_A_TEMP.md
```

**Spawn Exploration Subagent**

```
You are an exploration subagent researching a specific GHC topic.

**Input Files (READ-ONLY):**
- Master: /home/liu/Documents/bub/upstream/ghc/analysis/INTERACTIVE_CONTEXT_EXPLORATION.md
- Related: [Other relevant exploration files]

**Output File (WRITE TO THIS):**
/home/liu/Documents/bub/upstream/ghc/analysis/INTERACTIVE_CONTEXT_2024-03-28_A_TEMP.md

**Topic:** [Specific aspect to explore]
**Central Question:** [What we need to answer]

**Entry Point:**
- File: `compiler/GHC/Runtime/Context.hs`
- Function: [Name] around line [N]

**Instructions:**
1. Read input files to understand current state
2. Explore the specific topic thoroughly
3. Write findings to the output file following claim format:
   - One claim per finding
   - Source location + exact code snippet for each
   - Note any contradictions with input files
4. Include "Exploration Session" metadata:
   - Date: 2024-03-28
   - Focus: [Brief description]
   - Status: Draft (pending validation)

**Scope:**
- IN: [Specific areas]
- OUT: [Areas to ignore]
```

**Output File Template:**
```markdown
# Exploration Session: [Topic Focus]

**Date:** 2024-03-28
**Session ID:** A
**Focus:** [Specific aspect]
**Status:** Draft
**Based on:** INTERACTIVE_CONTEXT_EXPLORATION.md

## Findings

### Finding 1: [Title]
**Claim:** [Specific assertion]
**Source:** `compiler/GHC/Module/File.hs:line-range`
**Evidence:**
```haskell
[Exact code snippet]
```
**Confidence:** High/Medium/Low

## Contradictions
[List any conflicts with input files]

## Open Questions
[Unresolved items]
```

### Stage 2: Validation

**Spawn Validation Subagent**

```
You are a validation subagent. Your job is to verify evidence and check 
claims against actual source code.

**Files to Validate:**
- Draft: /home/liu/Documents/bub/upstream/ghc/analysis/INTERACTIVE_CONTEXT_2024-03-28_A_TEMP.md

**Task:**
For each claim in the draft file:
1. Read the cited source location
2. Verify the code snippet matches actual source
3. Check if the claim logically follows from the evidence
4. Assess confidence level

**Output:**
Update the draft file with validation annotations:

For each claim, add:
- **VALIDATED:** [Yes/No/Partial]
- **Source Check:** [Verified/Mismatch at line X]
- **Logic Check:** [Sound/Questionable - explain]
- **Notes:** [Any issues or concerns]

Also create a summary section at the end:

## Validation Summary
- Claims validated: N
- Claims with issues: N
- Source mismatches: [List]
- Recommended actions: [Keep/Revise/Reject for each claim]
```

**Validation Focus Areas:**

1. **Evidence Verification**
   - Does the code snippet exist at the cited location?
   - Is the snippet complete enough to support the claim?
   - Are line numbers accurate (±5 lines acceptable)?

2. **Model Checking**
   - Does the claim align with known GHC architecture?
   - Are there contradictions with established facts?
   - Is the inference chain logical?

3. **Confidence Assessment**
   - High: Direct evidence, clear documentation
   - Medium: Evidence present but interpretation needed
   - Low: Circumstantial evidence, inference chain long

### Stage 3: Merge

**Spawn Merge Subagent**

```
You are a merge subagent. Integrate validated findings into the master file.

**Source (Validated Draft):**
/home/liu/Documents/bub/upstream/ghc/analysis/INTERACTIVE_CONTEXT_2024-03-28_A_TEMP.md

**Target (Master File - UPDATE THIS):**
/home/liu/Documents/bub/upstream/ghc/analysis/INTERACTIVE_CONTEXT_EXPLORATION.md

**Validation Results:**
[Summary of what passed validation]

**Instructions:**
1. Read both files
2. For each validated claim:
   - Add to master file in appropriate section
   - Update cross-references
   - Mark with merge date
3. For claims that failed validation:
   - Add to "Unconfirmed Hypotheses" section
   - Note why they failed
4. Update master file metadata:
   - Last Updated: 2024-03-28
   - Status: In Progress
5. Remove any claims that are now obsolete
6. Ensure no duplicate claims exist

**Merge Rules:**
- Never lose information (move to appropriate section if not main claims)
- Maintain chronological order within sections
- Update all cross-references
- Keep the "Open Questions" section current
```

**After Merge:**

```bash
# Keep or archive the temporary file
mv *_TEMP.md archive/
# OR
rm *_TEMP.md
```

### Tool Call Content Verification

Before clicking "Spawn Subagent", verify your prompt contains:

**For ALL stages:**
- [ ] Absolute file paths (no relative paths)
- [ ] Role definition sentence
- [ ] Working directory specified
- [ ] Explicit file operation (READ vs WRITE)

**Stage 1 only:**
- [ ] Input file list with (READ-ONLY) labels
- [ ] Output temp file path with (WRITE TO THIS) label
- [ ] Entry point: file + function + approximate line
- [ ] IN/OUT scope boundaries

**Stage 2 only:**
- [ ] Single target file to validate
- [ ] Validation criteria checklist
- [ ] Annotation format specification
- [ ] Source verification instructions

**Stage 3 only:**
- [ ] Source temp file (validated draft)
- [ ] Target master file (UPDATE THIS)
- [ ] Validation summary provided
- [ ] Merge rules enumerated
- [ ] Metadata update list

### Example: Complete Workflow

**Master File:** `INTERACTIVE_CONTEXT_EXPLORATION.md`

**Stage 1 - Exploration:**
```
You are an exploration subagent...

Input: INTERACTIVE_CONTEXT_EXPLORATION.md (read-only)
Output: INTERACTIVE_CONTEXT_2024-03-28_A_TEMP.md (write)
Topic: How ic_gre_cache handles shadowing
```
→ Subagent creates temp file with new findings

**Stage 2 - Validation:**
```
You are a validation subagent...

Validate: INTERACTIVE_CONTEXT_2024-03-28_A_TEMP.md
Focus: Check source locations, verify code snippets, assess logic
```
→ Subagent adds validation annotations

**Stage 3 - Merge:**
```
You are a merge subagent...

Source: INTERACTIVE_CONTEXT_2024-03-28_A_TEMP.md (validated)
Target: INTERACTIVE_CONTEXT_EXPLORATION.md (update)
```
→ Subagent integrates findings into master file

### Example Subagent Spawn

**Topic:** Understanding how `ic_gre_cache` works in InteractiveContext

**Exploration File:** `/home/liu/Documents/bub/upstream/ghc/analysis/INTERACTIVE_CONTEXT_GRE_CACHE_EXPLORATION.md`

**Prompt to Subagent:**
```
You are a research subagent exploring GHC's InteractiveContext gre_cache.

**Context File:**
/home/liu/Documents/bub/upstream/ghc/analysis/INTERACTIVE_CONTEXT_GRE_CACHE_EXPLORATION.md

**Current State:**
The file contains initial exploration of InteractiveContext fields but the 
ic_gre_cache mechanism is not yet understood. We know it's a cache of the 
GlobalRdrEnv but not how it's maintained or updated.

**Your Task:**
Explore how ic_gre_cache works to answer: "How does GHCi maintain the cached
GlobalRdrEnv and when does it get updated?"

**Entry Point:**
Start in `compiler/GHC/Runtime/Context.hs`, look for:
- InteractiveContext definition (around line 100-200)
- ic_gre_cache field
- Any functions that update or use ic_gre_cache

Then trace to `compiler/GHC/Runtime/Eval/Types.hs` for IcGlobalRdrEnv.

**Scope:**
- Focus on: ic_gre_cache purpose, when it's updated, what triggers updates
- Do NOT explore: general InteractiveContext fields, unrelated GHCi state

**Deliverable:**
Add findings to the exploration file following claim format:
- Claims about ic_gre_cache mechanism
- Source locations for each claim
- Code snippets as evidence
- Update "Status" to "In Progress" and set "Last Updated" to today

Read the file first, then append your findings to the "Claims" section.
```

## Validation Workflow

Before marking an exploration as "Validated":

1. **Source Check**: Can every claim be verified by reading the cited source?
2. **Completeness**: Does it answer the central question?
3. **Consistency**: Are there contradictions between claims?
4. **Cross-Reference**: Do related topics link to each other?

Use subagent validation:
```
Validate the claims in [EXPLORATION_FILE.md] by:
1. Reading each source location cited
2. Confirming the code snippet matches the claim
3. Reporting any discrepancies
4. Suggesting fixes for any issues found
```

## Maintenance Rules

1. **Atomic Commits**: Each exploration session appends new claims
2. **No Deletion**: Don't remove claims, mark as deprecated instead
3. **Date Everything**: Every claim gets discovered/updated date
4. **Link Liberally**: Cross-reference related explorations
5. **Validate Periodically**: Run validation subagent when status changes

## Example: Good vs Bad Claims

### Good Claim
```markdown
**Claim:** The `runTcInteractive` function bridges InteractiveContext to 
type-checking by copying `icReaderEnv icxt` to `tcg_rdr_env`.

**Source:** `compiler/GHC/Tc/Module.hs:2675-2685`

**Evidence:**
```haskell
runTcInteractive :: HscEnv -> InteractiveContext -> TcM a -> IO (Messages, Maybe a)
runTcInteractive hsc_env icxt thing_inside = do
    initTcWithGbl hsc_env gbl_env emptyVarEnv thing_inside
  where
    gbl_env = updInteractiveContext env (icReaderEnv icxt) env
    -- ...
```

**Discovered:** 2024-03-28
```

### Bad Claim
```markdown
InteractiveContext connects to the type checker somehow.
```

**Why Bad:**
- Not atomic ("somehow" is vague)
- No source location
- No evidence
- Not verifiable

## Quick Reference

| Entity | Required | Format |
|--------|----------|--------|
| Topic | Central question, scope | Markdown H1 |
| Claim | Statement + source + snippet | Markdown section |
| Evidence | Exact code, line numbers | Fenced code block |

| Subagent Context | Must Include |
|------------------|--------------|
| File path | Absolute path to exploration file |
| Topic | Specific focus question |
| Entry point | Source file + function/line |
| Update instruction | Explicit directive to modify file |
