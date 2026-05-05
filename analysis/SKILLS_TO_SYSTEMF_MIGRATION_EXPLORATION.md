# Skills → System F Migration Exploration

**Date:** 2026-05-04
**Central Question:** Which `.agents/skills/` can be migrated to System F programs, and what System F language features are needed to support them?

---

## Notes

### Note 1: Scope
Explore all skills in `.agents/skills/` (excluding `workflow`, per user request). For each skill, assess:
1. What the skill does (its core logic)
2. Whether System F can express that logic today
3. What gaps exist if it cannot

### Note 2: System F Current Capabilities
From reading source files (`builtins.sf`, `demo.sf`, `bub.sf`, test files):

| Feature | Status |
|---------|--------|
| Algebraic data types | ✅ `data Either a b = Left a \| Right b` |
| Pattern matching | ✅ `case x of ...` with nested patterns |
| Polymorphism | ✅ `forall a. ...` |
| Higher-order functions | ✅ `map`, `foldr`, `compose` |
| Recursive functions | ✅ `factorial`, `treeSize`, mutual `even`/`odd` |
| LLM-annotated prim_ops | ✅ `{-# LLM #-} prim_op ...` |
| String/Int/Bool literals | ✅ |
| List syntax sugar | ✅ `[1, 2, 3]`, `x:xs` |
| Ref cells (mutation) | ✅ `mk_ref`, `set_ref`, `get_ref` |
| Monadic LLM type | ✅ `LLM a` in `bub.sf` |
| Tape type | ✅ `Tape`, `current_tape`, `fork_tape` |
| Module imports | ✅ `import bub` |
| File I/O | ❌ Not observed |
| Shell execution | ❌ Not observed |
| HTTP/WebSocket | ❌ Not observed |
| Effect system / IO monad | ❌ Only `LLM a` and `Ref` seen |
| Type classes | ❌ Not observed |
| Record types | ❌ Not observed |
| String interpolation | ❌ Not observed |
| Exception handling | ❌ Only `error` prim_op |

### Note 3: Skill Categories by Nature
Skills fall into several categories:
- **Prompt-only skills** — skills whose content is entirely instructions for the LLM (no tool calls beyond text generation)
- **Workflow/orchestration skills** — skills that define multi-step processes with state transitions
- **Reference/documentation skills** — skills that are lookup tables for conventions
- **Tool-integration skills** — skills that depend on external tools (shell, filesystem, HTTP)

### Note 4: Migration Analysis Framework
For each skill, I'll classify along two axes:
- **Logic complexity**: Simple (prompt template) → Complex (state machine with branching)
- **Tool dependency**: None (pure text) → Heavy (shell, filesystem, network)

Skills with **low tool dependency** and **moderate logic** are the best candidates for System F migration.

---

## Facts

### Fact 1: topic-thinking Skill Content
`.agents/skills/topic-thinking/SKILL.md`
- Defines 4 thinking modes: Analysis, Design, Validation, Implementation
- Each mode has: trigger, mental model, key questions, must-do, must-not-do
- Contains a mandatory "Echo Protocol" for mode switches
- Includes a cross-cutting "Tiered Analysis Framework"
- **No tool calls** — purely instructional content for the LLM
- Core logic: given a signal (user phrase), activate the appropriate mode and its behavioral constraints

### Fact 2: exploration Skill Content
`.agents/skills/exploration/SKILL.md`, `FORMAT.md`, `WORKFLOW.md`
- Three-phase workflow: Explore → Validate → Merge
- Output format: Notes → Facts → Claims (dependency-ordered)
- Cross-referencing system between facts and claims
- **No tool calls in the skill itself** — the skill instructs the LLM how to structure its investigation
- Core logic: structured document production with validation gates

### Fact 3: journal Skill Content
`.agents/skills/journal/SKILL.md`
- Convention: append-only entries in `journal/YYYY-MM-DD-topic.md`
- Rules: same day + same topic → append; same day + new topic → new file
- Very simple logic: file naming convention and append-vs-create decision
- **No tool calls** — purely a convention guide

### Fact 4: python-ut Skill Content
`.agents/skills/python-ut/SKILL.md`
- Testing style guide with patterns and anti-patterns
- Structural equality rules, forbidden assertions, named constants
- Example patterns: construct-then-compare, field extraction, helper functions
- **No tool calls** — purely a reference document
- Core logic: a set of rules (assertion patterns) to check against

### Fact 5: code-reading-assistant Skill Content
`.agents/skills/code-reading-assistant/SKILL.md`
- Workflow: Read `docs/architecture.md` first → search code → answer
- Decision tree for routing questions
- Constraints: CAN explain, CANNOT edit
- **No tool calls** — but references file reading, which is implicit in agent's capabilities
- Core logic: a decision tree for how to answer codebase questions

### Fact 6: change-plan Skill Content
`.agents/skills/change-plan/SKILL.md`
- Workflow: Create tracking → Write change file → Get review → Implement
- Change file format: Facts, Design, Why it works, Files
- Append-only rule for change files
- Checklists: authoring checklist, review checklist
- **No direct tool calls** — but references `todowrite` and file creation
- Core logic: a state machine (init → plan → review → implement) with validation gates

### Fact 7: skill-management Skill Content
`.agents/skills/skill-management/SKILL.md`
- Skill location registry (system vs project)
- Skill-first workflow: identify domain → check manifest → read skill → proceed
- Relevance criteria table
- **Lists shell commands** (`ls`, `cat`) for skill discovery, but these are informational references, not core logic
- Core logic is a lookup table mapping tasks to skill files
- Core logic: a lookup table mapping tasks to skill files

### Fact 8: scripts-docs Skill Content
`.agents/skills/scripts-docs/SKILL.md`
- Documentation maintenance for `scripts/` folder
- Format: purpose, last-modified date, usage
- Audit procedure using `git log`
- **Tool dependency: shell commands** (`git log`, file reading)
- Core logic: date comparison and documentation update trigger

### Fact 9: bus-cli Skill Content
`.agents/skills/bus-cli/SKILL.md`
- CLI commands for WebSocket message bus
- Commands: `bub bus serve`, `bub bus send`, `bub bus recv`
- Architecture: JSON-RPC 2.0 over WebSocket
- **Tool dependency: shell execution** (bub CLI commands)
- Core logic: command reference and architecture overview

### Fact 10: deployment Skill Content
`.agents/skills/deployment/SKILL.md`
- Systemd user service management
- Commands: start/stop/logs/status for bus, agent, tape, telegram-bridge
- Auto-restart, rate limiting configuration
- **Tool dependency: shell execution** (`deploy-production.sh`, `systemctl`)
- Core logic: command reference and operational procedures

### Fact 11: docs Skill Content
`.agents/skills/docs/SKILL.md`
- MkDocs configuration and writing guidelines
- Mermaid validation script usage
- File naming and structure conventions
- **Tool dependency: shell** (`docs-server.sh`, `validate_mermaid.py`)
- Core logic: reference + operational commands

### Fact 12: testing Skill Content
`.agents/skills/testing/SKILL.md`
- Test script catalog with run commands
- Environment setup for API keys
- **Tool dependency: shell** (`uv run python scripts/...`)
- Core logic: test script reference

### Fact 13: System F LLM Integration Pattern
From `main.sf` and `bub.sf`:
```
-- LLM monad for sequenced LLM operations
prim_type LLM a

-- LLM-annotated prim_ops act as prompt templates
{-# LLM #-}
prim_op user_intent :: String -> String

-- Composition: chain LLM operations
checked_run :: Tape -> String -> String -> LLM ()
```
- LLM prim_ops generate prompts from their doc strings and parameter docs
- The `LLM a` type sequences these operations
- `Tape` provides context persistence

### Fact 14: System F Module System
From observed usage:
- `import bub` brings in `LLM`, `Tape`, `current_tape`, `fork_tape`
- `import builtins` brings in standard library
- `:browse <mod>` lists exports
- Modules are files (e.g., `bub.sf` → module `bub`)

---

## Claims

### Claim 1: Three Skills Are Strong Migration Candidates for System F
**Reasoning:** Skills that are primarily instructional (no significant tool calls beyond informational shell references) with moderate decision logic can be expressed as LLM prim_ops and data types. These are the strongest candidates but "immediately migratable" overstates ease — there's still design work to map skill content into types and prim_op signatures.

- **topic-thinking** → Enum of modes (`data ThinkingMode = Analysis | Design | Validation | Implementation`) + an LLM prim_op that reads user signal and returns the mode + behavioral instructions. The "Echo Protocol" is a pure function from signal to mode declaration.
- **python-ut** → A set of rules encoded as data type definitions (assertion patterns) + an LLM prim_op that reviews test code against the rules. The patterns and anti-patterns are data, the checking is LLM-powered.
- **skill-management** → A lookup table (`List (Pair String String)` mapping task domains to skill paths) + an LLM prim_op for skill discovery. Pure data, no tool calls needed.

**References:** Fact 1, Fact 4, Fact 7, Fact 13

### Claim 2: Four Skills Are Partially Migratable — Need File I/O or String Formatting
**Reasoning:** These skills have logic that System F can express but depend on operations not yet available.

- **journal** → The append-vs-create decision is a simple conditional on date/topic matching. Needs: file existence check, file append operation, date/time primitives. Could be: `journal_write :: String -> String -> LLM ()` prim_op.
- **change-plan** → The state machine (init→plan→review→implement) maps to an ADT (`data ChangePhase = Init | Plan | Review | Implement`). Checklists can be data types. Needs: file write for `changes/` directory, subagent spawning for review.
- **exploration** → The Notes→Facts→Claims structure maps directly to data types. The validation gate is a pattern match on phase. Needs: file write to `analysis/`, subagent spawning for validation.
- **code-reading-assistant** → The decision tree maps to a function on question type. Needs: file read primitive, code search primitive.

**References:** Fact 2, Fact 3, Fact 5, Fact 6, Note 2

### Claim 3: Five Skills Are Not Currently Migratable — Require Shell/External Tool Integration
**Reasoning:** These skills fundamentally depend on executing shell commands, managing processes, or network I/O — none of which System F currently supports.

- **scripts-docs** → Requires `git log` to check last-modified dates. Needs: shell exec prim_op.
- **bus-cli** → Requires WebSocket client, JSON-RPC protocol. Needs: network prim_ops.
- **deployment** → Requires `systemd-run`, `journalctl`, shell execution. Needs: shell exec prim_op.
- **docs** → Requires MkDocs server, mermaid-cli. Needs: shell exec prim_op.
- **testing** → Requires `uv run python scripts/...`. Needs: shell exec prim_op.

Even if these were migrated, they'd just be thin wrappers around prim_ops that do the real work — the skill content would remain mostly as documentation/reference, not executable logic.

**References:** Fact 8, Fact 9, Fact 10, Fact 11, Fact 12, Note 2

### Claim 4: The Key Architectural Insight Is That LLM Prim_ops Replace "Instruction-Only" Skills — With Caveats
**Reasoning:** Many skills are essentially structured prompts: they tell the LLM *how* to think about a problem (mode switching, testing conventions, exploration structure) without performing any computational work themselves. In System F, `{-# LLM #-} prim_op` serves a similar purpose — the function signature and doc comments become the prompt, and the LLM fills in the execution.

However, there's an important distinction: **skills provide persistent behavioral context** (loaded once, active for the whole conversation), while **prim_ops provide task-specific prompts** (invoked per call). A skill like `topic-thinking` modifies how the LLM behaves across all subsequent interactions; an LLM prim_op only activates when called. This means migration isn't just "translate to prim_op" — it may require a companion mechanism for persistent behavioral injection, or the `LLM` monad's sequencing must carry forward the behavioral state explicitly through data types.

This means the migration path is:
1. Define data types for the skill's domain (e.g., `ThinkingMode`, `ExplorationPhase`, `AssertionPattern`)
2. Define LLM prim_ops for each decision point (e.g., `detect_mode :: String -> ThinkingMode`, `validate_claim :: Claim -> ValidationResult`)
3. Write pure functions for the deterministic logic (e.g., `append_or_create :: JournalState -> String -> Decision`)
4. Compose in the `LLM` monad for sequenced operations, with domain types carrying behavioral state between calls

**References:** Fact 13, Fact 14, Claim 1, Claim 2

### Claim 5: A Generic `shell_exec` Prim_op Would Unlock All Remaining Migrations
**Reasoning:** The only missing capability for skills in Claims 2 and 3 is interaction with the outside world (files, shell, network). If System F had:
- `prim_op shell_exec :: String -> LLM String` — execute a shell command
- `prim_op file_read :: String -> LLM String` — read file contents
- `prim_op file_write :: String -> String -> LLM ()` — write file contents

Then ALL skills become migratable. The data types and logic would live in System F, with side effects channeled through these prim_ops into the `LLM` monad. This is consistent with the existing pattern where `LLM a` serves as the effect type.

**References:** Note 2, Claim 3

---

## Summary

| Skill | Migratable? | What's Needed |
|-------|------------|---------------|
| topic-thinking | ✅ Now | Data types + LLM prim_op |
| python-ut | ✅ Now | Data types + LLM prim_op |
| skill-management | ✅ Now | Lookup table + LLM prim_op |
| journal | ⚠️ Partial | File I/O prim_ops |
| change-plan | ⚠️ Partial | File I/O + subagent prim_ops |
| exploration | ⚠️ Partial | File I/O + subagent prim_ops |
| code-reading-assistant | ⚠️ Partial | File read + code search prim_ops |
| scripts-docs | ❌ Blocked | Shell exec (`git log`) |
| bus-cli | ❌ Blocked | Network (WebSocket) prim_ops |
| deployment | ❌ Blocked | Shell exec prim_op |
| docs | ❌ Blocked | Shell exec prim_op |
| testing | ❌ Blocked | Shell exec prim_op |

**Counts:** 3 fully migratable, 4 partially migratable, 5 blocked