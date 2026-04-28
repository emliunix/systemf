# Workflow Patterns

Task orchestration patterns for Manager. These patterns define how to decompose work into tasks and reconcile based on task outcomes using skill constructs.

These patterns are **encoded in the algorithms** in `role-manager.md` and `role-architect.md`. This document describes the algorithm behavior for reference.

---

## Table of Contents

1. [Universal Constraints](#universal-constraints) - Rules that apply to ALL patterns
2. [Quick Reference](#quick-reference) - Pattern selection at a glance
3. [Detailed Patterns](#detailed-patterns)
   - [Discovery](#pattern-discovery) - When information is inadequate
   - [Design-First](#pattern-design-first) - New features and architecture
   - [Design Review](#pattern-design-review) - Validate design before implementation
   - [Implementation-With-Review](#pattern-implementation-with-review) - Universal implementation pattern
   - [Escalation Recovery](#pattern-escalation-recovery) - When review fails
   - [Integration](#pattern-integration) - Multiple parallel streams
4. [Pattern Selection Guide](#pattern-selection-guide)
5. [Pattern Constraints](#pattern-constraints)
6. [Pattern Composition](#pattern-composition)

---

## Universal Constraints

**These rules apply to ALL patterns without exception:**

### State Transitions (Mandatory)
- **Allowed:** `todo → review → done`
- **Forbidden:** Direct `todo → done` transition
- Scripts MUST reject commits that attempt direct `todo → done`

### Single-File Continuity (Mandatory)
- Review uses the **SAME task file** as implementation
- Review work is appended to the existing work log
- No new task file is created for review phases
- Task file tracks complete history: design → implementation → review

### Assignee Field (Mandatory)
- Use `assignee` field (not fixed `role`)
- Same agent can work in different modes on same file
- Current assignee reflects who is actively working

### Review is Universal (Mandatory)
- **ALL implementation work** MUST be reviewed
- No "simple" exceptions that skip review
- Review is a quality gate, not an optional add-on

---

## Quick Reference

| Pattern | Trigger | Structure |
|---------|---------|-----------|
| **Discovery** | Missing information for planning | Exploration → Manager decides |
| **Design-First** | New features, core types, architecture | Design → **Design Review** → Implementation-With-Review |
| **Design Review** | Architect design task complete | Validate work items against patterns → Approved/Redesign |
| **Implementation-With-Review** | ALL implementation work | Implement → Review (same file) → Done |
| **Escalation Recovery** | Review finds issues | Review (escalate) → Prerequisites → Retry |
| **Integration** | Multiple parallel work streams | Parallel tasks → Integration task |

**Pattern Selection Decision Tree:**
```
Missing information? → Discovery
    ↓
New feature/architecture? → Design-First
    ↓
Design task complete with work items? → Design Review
    ↓
Design approved? → Implementation-With-Review
    ↓
Implementation review found issues? → Escalation Recovery
    ↓
Multiple streams? → Integration
```

---

## Detailed Patterns

---

## Pattern: Discovery

**Use when:** Information inadequate for planning.

**Trigger:** Manager cannot determine task structure due to missing context.

**Characteristics:**
- Architect explores and reports findings
- Manager waits before creating implementation tasks
- Findings recorded as structured **Work Items** in the bounded block:
    `<!-- start workitems --> ... <!-- end workitems -->`

**Task Structure:**
```yaml
# Single exploration task
---
assignee: Architect
type: exploration
dependencies: []
skills: [code-reading]
expertise: ["Problem Analysis", "Code Exploration"]
state: todo
---
```

**Flow:**
```
Manager detects missing info → Create Discovery task
    ↓
Architect explores → Appends work items to same file
    ↓
Manager reads work items → Selects appropriate pattern
```

**Manager Actions:**
1. Create exploration task
2. Log plan adjustment: `inadequate_information`
3. Wait for Architect to populate the task’s bounded **Work Items** block
4. After completion, select appropriate pattern based on findings

**State Transitions:**
- `todo → review → done` (Architect reviews own exploration)

---

## Pattern: Design-First

**Use when:** Building new features, modifying core types, or architectural changes.

**Characteristics:**
- Architect creates specification first
- Implementation follows established contracts
- Review validates against design

**Task Structure:**
```yaml
# Task 1: Design
---
assignee: Architect
type: design
title: "<Component> Design"
dependencies: []
skills: [code-reading, domain-specific]
expertise: ["System Design"]
state: todo
---

# Task 2: Implementation (depends on design)
---
assignee: Implementor
type: implement
dependencies: [design_task]
skills: [from work item]
expertise: [from work item]
state: todo
---
```

**Flow:**
```
Discovery (optional) → Design task
    ↓
Architect creates types.py, contracts → State: review → done
    ↓
Manager creates Implementation-With-Review task
    ↓
Implementor builds to spec → Review validates → Done
```

**When to use:**
- New architectural components
- Core type definitions
- Public API design
- Protocol specifications

---

## Pattern: Design Review

**Use when:** Architect completes a design task with work items.

**Trigger:** Design task state is `review` (design complete, needs validation).

**Characteristics:**
- Validates work items against workflow patterns before implementation
- Checks if work items are correctly structured per patterns.md
- Ensures appropriate pattern selection (Design-First vs direct implementation)
- Verifies dependency ordering follows Core-First principle
- Same task file continuity (appends review to design task)

**Task Structure:**
```yaml
# Same task file from design phase
---
assignee: Architect
type: design
title: "Design Review - <Component>"
dependencies: []
skills: [code-reading]
expertise: ["Pattern Matching", "Workflow Design"]
state: review  # Design complete, in review phase
---

# Task: Design Review

## Context
Design task produced work items that need validation against patterns.

## Work Items to Review
- [List of work items from design phase]

## Work Log

### [timestamp] Design | ok
**F:** Created types.py, defined work items...
**A:** Design decisions...
**C:** Design complete. State: review (ready for design review)

### [timestamp] Design Review | ok/escalate
**F:** Reviewed work items against patterns.md
**A:** Pattern compliance analysis...
**C:** APPROVED / REDESIGN REQUIRED
```

**Flow:**
```
Design task (state: review - design complete)
    ↓
Architect runs design_review_mode() algorithm:
  - validate_work_items_against_patterns()
  - check_complexity_decomposition()
  - verify_core_first_ordering()
    ↓
IF approved → State: done → Manager creates implementation tasks
IF escalated → State: escalated → Architect redesigns
```

**Algorithm:** See `role-architect.md` `design_review_mode()` for complete validation logic.

**Manager Actions:**
1. Detect design task state: `review` (via algorithm, not manual check)
2. Assign SAME task file to Architect for design review
3. After review:
   - If approved: Create implementation tasks from work items
   - If escalated: Create redesign task, queue original for retry

---

## Pattern: Implementation-With-Review

**Use when:** ANY implementation work (universal pattern).

**Characteristics:**
- Pre-implementation: Design review (if design task exists)
- Implementation: Build to specification
- Post-implementation: **MANDATORY review on same file**
- Prevents skipping review for "simple" changes

**Task Structure:**
```yaml
# Single task file - reused for review
---
assignee: Implementor
type: implement
title: "Implement - <Component>"
dependencies: [design_task]  # If design-first used
skills: [from work item, testing]
expertise: [from work item]
state: todo
---

# Task: Implement <Component>

## Context
Specification from design task.

## Files
- src/component.py
- tests/test_component.py

## Description
Implementation details...

## Work Log

### [timestamp] Implementation | ok
**F:** Implemented component per spec...
**A:** Decisions made...
**C:** Ready for review. State: review

### [timestamp] Review | ok
**F:** Reviewed implementation against design...
**A:** Validation results...
**C:** Review passed. State: done
```

**Flow:**
```
Task created (state: todo)
    ↓
Implementor works → Appends work log → State: review
    ↓
Review assignee (Architect) validates same file
    ↓
IF review passes → State: done
IF review fails → Escalation Recovery
```

**State Enforcement:**
- Script rejects `todo → done` commits
- Implementor MUST transition to `review`, not `done`
- Reviewer updates state to `done` after validation

---

## Pattern: Escalation Recovery

**Use when:** Review finds implementation doesn't meet specification.

**Trigger:** Review work log contains `ESCALATE` or critical issues.

**Characteristics:**
- **SAME task file continues** (no new task created)
- Reviewer appends `additional_work_items` to same file
- Manager creates prerequisite tasks
- Original task retries after prerequisites complete
- State: `review → escalated → todo` (after prerequisites)

**Flow:**
```
Implementation task (state: review)
    ↓
Architect reviews, finds issues → State: escalated
    ↓
Architect appends to same file:
  - Review findings
  - additional_work_items section
    ↓
Manager detects escalation:
  - Creates prerequisite tasks from work items
  - Updates original task dependencies
  - Original task back to queue
    ↓
Prerequisites complete → Original task retries
    ↓
Implementor addresses issues → State: review → done
```

**Manager Actions:**
1. Detect escalation from work log status (`| escalate` or `| blocked`)
2. Check for `additional_work_items` in task file
3. If work items exist:
   - Create prerequisite tasks
   - Update original task dependencies
   - Keep original task in queue (will retry)
4. Log plan adjustment: `escalation_prerequisites_created`

**Work Log Structure (Escalation):**
```markdown
### [timestamp] Review | escalate

**F:** Reviewed implementation. Found issues:
- Issue 1: Description
- Issue 2: Description

**A:** Root cause analysis...

**C:** ESCALATE - Prerequisites needed before completion

## Additional Work Items

```yaml
additional_work_items:
  - description: Fix issue 1
    files: [src/file.py]
    expertise_required: ["Skill"]
    priority: high
```
```

---

## Pattern: Integration

**Use when:** Multiple work streams converge into single deliverable.

**Characteristics:**
- Parallel implementation tasks
- Integration task depends on all parallel tasks
- Each parallel task follows Implementation-With-Review
- Final validation step

**Task Structure:**
```yaml
# Parallel tasks (no dependencies between them)
---
assignee: Implementor
type: implement
dependencies: [shared_parent_task]
skills: [from work item]
state: todo
---
# ... multiple parallel tasks, each with own review

# Integration task (convergence point)
---
assignee: Implementor
type: implement
title: "Integrate <Feature>"
dependencies: [parallel_task_1, parallel_task_2]
skills: [testing]
expertise: ["System Integration", "Testing"]
state: todo
---
```

**Flow:**
```
Design task
    ↓
Parallel Task A → Review → Done
Parallel Task B → Review → Done
    ↓
Integration Task → Review → Done
```

**Use cases:**
- Multi-component features
- Modular system assembly
- Cross-module changes

**Note:** Each parallel task AND the integration task each follow Implementation-With-Review pattern (separate review phases).

---

## Pattern Selection Guide

Pattern selection is handled by algorithms in `role-manager.md` (`reconcile_tasks()`). This guide documents the algorithm logic:

**Algorithm Decision Tree:**
- Missing information? → **Discovery** (Manager creates exploration task)
- Design task (type: design) with work items complete? → **Design Review** (Manager assigns to Architect)
- New feature/architecture? → **Design-First** → **Design Review** → **Implementation-With-Review**
- Any implementation work? → **Implementation-With-Review** (universal)
- Multiple parallel streams converging? → **Integration**

**Outcome Handling:**
- Design review passed? → Manager creates implementation tasks
- Design review escalated? → Manager creates redesign task, queues original for retry
- Implementation review passed? → Manager marks `done`, creates next tasks
- Implementation review escalated? → **Escalation Recovery**

**Common Algorithm Flows:**

These are the typical pattern sequences the algorithm produces:

**New feature with core types:**
```
Discovery (optional) → Design-First → Design Review → Implementation-With-Review
```

**API changes:**
```
Design-First → Design Review → Implementation-With-Review
```

**Bug fix:**
```
Discovery (if needed) → Implementation-With-Review
```

**Multi-component feature:**
```
Design-First → Integration pattern with parallel Implementation-With-Review tasks
```

---

## Pattern Constraints

**Manager MUST:**
- Follow `reconcile_tasks()` algorithm in `role-manager.md` (patterns are encoded in algorithm)
- Enforce universal constraints (no `todo → done`)
- Use single-file continuity for review phases
- Set `state: todo` when creating tasks
- Log plan adjustments in kanban (algorithms determine transitions)

**Script Enforcement (Required):**
- `log-task.py` MUST reject commits with `todo → done` transition
- MUST allow `todo → review` and `review → done`
- MUST allow `review → escalated` for Escalation Recovery

**Anti-Patterns:**
- Creating direct `todo → done` transition → **VIOLATION**
- Creating new task file for review → Use **single-file continuity**
- Skipping review for "simple" changes → **NO EXCEPTIONS**
- Complex design without design phase → Use **Design-First**
- Creating all tasks upfront → Use **Discovery** to inform planning
- Ignoring escalation status → Trigger **Escalation Recovery**

---

## Pattern Composition

Patterns compose by chaining outputs to inputs:

```
Discovery → Design-First → Design Review → Implementation-With-Review
                ↓              ↓
      Design Redesign (if design review fails)
                ↓
      Implementation Review (if implementation review fails)
                ↓
      Escalation Recovery
                ↓
      Validate-Before-Continue (retry)
                ↓
      Integration (merge with other work)
```

**Composition Rules:**
1. **Discovery** can lead to any pattern based on findings
2. **Design-First** MUST be followed by Implementation-With-Review
3. **Implementation-With-Review** can trigger Escalation Recovery
4. **Escalation Recovery** loops back to Implementation-With-Review
5. **Integration** coordinates multiple parallel Implementation-With-Review tasks

Manager handles composition by treating pattern output as input to next pattern selection.
