---
name: change-plan
description: Change plan workflow for non-trivial code changes. Create, review, and track changes before implementation.
---

# Change Plan

**Before modifying any code, create a change plan.** Applies to any non-trivial change (new feature, bug fix, refactor).

## Workflow

1. **Initialize tracking**: `todowrite` with at least:
   - One item to create the change file
   - Items to track implementation progress

2. **Create the change file**: Write to `changes/1-<change-name>.md` containing:
   - **Facts**: What exists (relevant code paths, current behavior, constraints)
   - **Design**: Exact change (new types, new functions, modified logic)
   - **Why it works**: How the design integrates with existing code
   - **Files**: Concrete list of files to change, add, or delete

3. **Get review**: Spawn a subagent to review the change plan before executing code edits

4. **Implement**: After user approval, execute the plan

## Example

```
# Step 1: Create todos
todowrite([
    {"content": "1. Create change file changes/1-add-bus-retry.md", "status": "in_progress", "priority": "high"},
    {"content": "2. Review change plan with subagent", "status": "pending", "priority": "high"},
    {"content": "3. Implement retry logic in bus client", "status": "pending", "priority": "high"},
])

# Step 2: Create change file
changes/1-add-bus-retry.md with Facts, Design, Why it works, Files
```

## Rules

- **Example filename**: `changes/1-add-literal-patterns.md`
- **Append-only**: If design evolves, create a new file (e.g., `changes/2-add-literal-patterns-v2.md`). Never modify an existing change plan.
- **Mandatory review**: Reviewer subagent checks for consistency with existing architecture, missing edge cases, and incorrect assumptions. Automatic — don't wait for user approval to run it. Implementation requires explicit user approval.


## Change Plan Checklist

### Authoring Checklist

- [ ] **Inventory all call sites** — grep across the repo for every function, method, or class being modified or removed
- [ ] **Categorize migration patterns** — if changing APIs, group call sites by how they must adapt (direct rename, signature change, behavior change, etc.)
- [ ] **Decide delete vs migrate** — for obsolete code, explicitly choose deletion or migration and document the rationale
- [ ] **Identify pre-existing debt vs new bugs** — distinguish legacy issues from defects introduced by the current change
- [ ] **Check production code separately from tests** — review production and test code independently; tests may need updates even when production logic is correct
- [ ] **Verify line numbers match actual files** — ensure all referenced line numbers correspond to the current state of the codebase
- [ ] **List all files to modify, delete, or create** — provide an exhaustive file inventory with the action for each

### Review Checklist

- [ ] **Verify line numbers against actual files** — confirm every line reference in the plan matches the current code
- [ ] **Confirm unreachability** — grep for call sites to verify code marked for deletion is truly unreachable
- [ ] **Scope analysis: in-plan vs out-of-plan** — ensure the plan boundary is clear and no required changes are omitted
- [ ] **Architecture compliance check** — validate the design aligns with existing patterns and constraints
- [ ] **Dead code identification** — flag any code that becomes unused as a result of the change
- [ ] **Import cleanup verification** — check that removed code does not leave stale imports
- [ ] **Verify test coverage** — confirm tests exist or are planned for all modified and new behavior
