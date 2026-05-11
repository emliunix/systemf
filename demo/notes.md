# Context Architecture Notes

## Key Insight

The key in all agent flow is about **context**.

We have seen:
- **Skills** — externalized context retrieved through a textual index system
- **Subagent** — isolates context for different concerns
- **RAG** — dynamic context building process (context injection)

Now: what should we do with context?

---

## Topic 1: Facts vs Instructions in Context

**The distinction:**
- **Facts** — verifiable state about the world (project structure, dependencies, current file contents)
- **Instructions** — how the agent should behave ("always use pytest", "prefer functional style")

**Current state:** The distinction blurs in practice.
- Skills inject both (AGENTS.md has project facts, skill body has instructions)
- Tape entries are mostly facts but carry implicit instructions
- State dict mixes both freely

**The risk:** Instructions masquerading as facts become stale pollution.
> Example: A skill says "always use pytest" but the project switched to unittest. The instruction is now misinformation.

**Exploration skill's epistemology (good model):**
```
Notes → Facts → Claims
```
- Facts are leaf nodes (verifiable artifacts)
- Claims synthesize from facts (reasoning)
- Notes are context/planning (narrative, non-verifiable)

But this separation exists at the *output* level. We lack the same discipline at the *input* (system prompt) level.

---

## Topic 2: Context Maintenance and Pollution

**The problem:** Context has built-in assumptions that become stale as the project evolves.

**Current mechanisms:**
- Tape is append-only (good for audit trail, bad for stale data)
- Skills are static files (no freshness check)
- Handoff truncates history but doesn't validate
- State dict accumulates without garbage collection

**Skill pollution scenario:**
1. Skill S encodes assumption A about the project
2. Project evolves, assumption A becomes false
3. Skill S continues to be injected into every prompt
4. Agent behavior degrades silently

**The framework can't detect this** because skills have no validity constraints.

---

## Ideas for Improvement

### 1. Validity Constraints on Skills

Skills could declare when they apply:

```yaml
---
name: python-ut
valid_when:
  - file: "pytest.ini"
  - deps: "pytest" in requirements.txt
---
```

The framework verifies preconditions before injecting skill context. Stale skills become no-ops instead of pollution.

**Open question:** Who validates? Framework transparently, or agent explicitly via SystemF primitives?

### 2. Context Entry TTLs / Dependency Tracking

Tape entries could carry metadata:
- `depends_on: ["file:requirements.txt", "skill:python-ut"]`
- `valid_until: 2026-05-11` or `max_age: 1h`

Before each turn, the framework checks dependencies. Stale entries are excluded or flagged.

### 3. Explicit Fact/Instruction Tags

At the system prompt construction level:
- Facts tagged with provenance and verification method
- Instructions tagged with scope and override rules

```
[fact:file src/main.py:34] The project uses unittest
[instruction:skill python-ut] Prefer pytest for new tests
```

When facts and instructions conflict, the agent can resolve explicitly.

### 4. Context as First-Class Value (SystemF direction)

Since context is already a first-class value in SystemF, we could expose:
- `context.validate()` — check freshness
- `context.filter(predicate)` — remove stale entries
- `context.tag(kind, metadata)` — annotate entries

This makes context maintenance explicit and programmable rather than framework magic.

---

## Open Questions

1. **Validation ownership:** Should context validation be explicit in the language (SystemF primitives) or handled transparently by the framework?

2. **Performance:** Validating dependencies on every turn adds overhead. Is it acceptable? Can we cache?

3. **False positives:** A skill with strict validity constraints might fail to apply in edge cases where it should. How to balance?

4. **User control:** How much should users manually curate context vs. trust automatic systems?

---

## Related Architecture

- **Tape model:** Append-only log with anchor-based truncation (current)
- **Skill model:** Static text files injected into system prompt (current)
- **Subagent model:** Context isolation via tape forks (current)
- **Exploration skill:** Facts/Notes/Claims separation at output level (existing good practice)

**Missing:** Systematic freshness validation, dependency tracking, fact/instruction separation at input level.
