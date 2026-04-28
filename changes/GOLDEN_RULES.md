# Golden Behavior Rules

## Universal Principles

### 1. Architecture First Principle
**Correct structure over convenience.**

Type definitions and architectural decisions exist for a reason. Honor them:
- Good names reveal intention (`ValBind` vs anonymous tuple)
- Type definitions provide semantic clarity
- Self-documenting structures reduce maintenance burden
- **Correct structure first, effort evaluation second**

### 2. No Shortcuts Based on Effort Evaluation
**Effort-based decision making always results in more wasted efforts.**

- ❌ "It's easier to change 2 files than 10" 
- ✅ "The structure requires 10 files because it matters"
- ❌ "Let's use tuples to avoid boilerplate"
- ✅ "Named types document intent and catch errors at compile time"

**The architecture must be correct in the first place.**

## References

### Required Reading Before Work

1. **Change Protocol** (`AGENTS.md`)
   - Phase 1: Collect affected locations
   - Phase 2: Write change plan to `changes/N-description.md`
   - Phase 3: **MANDATORY subagent review** before edits
   - Phase 4: Execute only after approval

2. **Topic Thinking** (`.agents/skills/topic-thinking/SKILL.md`)
   - Analysis Mode: Detective (evidence first)
   - Design Mode: Architect (principles before details)
   - Implementation Mode: Craftsman (precision, completeness)

3. **Style Guides** (`docs/styles/`)
   - `python.md`: Naming, imports, types
   - `testing-structural.md`: Structural comparison, not property assertions

### Skill-First Checking

**Before starting any work:**
1. Read relevant skills from `.agents/skills/`
2. Check `docs/styles/` for domain conventions
3. Follow the conventions, don't improvise

### Change Plan Requirements

Every non-trivial change requires:
- **Facts**: What exists, current behavior, constraints
- **Design**: Exact change to make
- **Why it works**: How design integrates with existing code
- **Files**: Concrete list of files to change

**Append-only**: Never modify existing change plans. Create `changes/2-description-v2.md` if design evolves.

### Subagent Review

**Mandatory for all change plans.** Reviewer checks:
- Consistency with existing architecture
- Missing edge cases
- Incorrect assumptions

**Do not proceed to implementation until review is complete.**

---

> "The architecture must be correct in the first place."
