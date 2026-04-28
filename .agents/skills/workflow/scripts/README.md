# Workflow Helper Scripts

This directory contains helper scripts for managing the simplified workflow system.

## Overview

The workflow system uses a simplified structure with all files in `./tasks/`:
- **Task files**: `N-slug.md` (e.g., `0-design-api.md`, `1-implement-models.md`)
- **Kanban files**: `N-kanban-slug.md` (e.g., `2-kanban-api-refactor.md`)
- **Global sequenced numbering**: All files share the same numbering sequence

## How to Run These Scripts

- Preferred: `uv run .agents/skills/workflow/scripts/<script>.py ...`
- Alternative: run `.agents/skills/workflow/scripts/<script>.py ...` directly if it is executable

## Scripts

### 1. create-task.py

Creates a new task file with a validated YAML header.

**Usage:**
```bash
# Basic usage (kanban and creator-role are required)
uv run .agents/skills/workflow/scripts/create-task.py \
    --assignee Architect \
    --expertise "System Design,Python" \
    --title "Design API Layer" \
    --kanban "tasks/0-kanban-project.md" \
    --creator-role manager

# Full usage with all options
uv run .agents/skills/workflow/scripts/create-task.py \
    --assignee Implementor \
    --expertise "Software Engineering,Type Theory" \
    --skills "python-project,testing" \
    --title "Implement Authentication" \
    --kanban "tasks/0-kanban-project.md" \
    --creator-role user \
    --type implement \
    --priority high \
    --dependencies "tasks/0-design-api.md" \
    --refers "tasks/0-design-api.md" \
    --context "Background info here" \
    --files "src/auth.py,tests/test_auth.py" \
    --description "Implement JWT authentication"
```

**Options:**
- `--assignee, -a` (required): Task assignee (Architect, Implementor)
- `--expertise, -e` (required): Comma-separated expertise areas
- `--title, -t` (required): Task title (used for filename slug)
- `--kanban, -k` (required): Path to kanban file for global context
- `--creator-role, -cr` (required): Role of the creator - valid values: `manager`, `user`, `architect`, `implementor`. **IMPORTANT**: Only `manager` and `user` are allowed to create tasks. If `architect` or `implementor` is specified, the script will exit with error: "role {role} is not allowed to create task". This prevents agents from creating task files directly - they should log work items instead.
- `--skills, -s`: Comma-separated skills to load
- `--type`: Task type (exploration, design, review, implement, redesign; auto-inferred if not specified)
- `--priority`: Priority level (critical, high, medium, low; default: medium)
- `--dependencies, -d`: Comma-separated task file dependencies
- `--refers`: Comma-separated related task files to reference
- `--context`: Task context/background
- `--files, -f`: Comma-separated list of relevant files
- `--description`: Detailed task description
- `--tasks-dir`: Directory for task files (default: ./tasks)

**Output:**
- Returns the filepath of the created task (e.g., `tasks/0-design-api-layer.md`)

### 2. create-kanban.py

Creates a new kanban file with a validated YAML header. Creates an **empty** kanban with no tasks - tasks are created separately by the Manager using create-task.py.

**Usage:**
```bash
# Create kanban (empty, Manager will add tasks)
uv run .agents/skills/workflow/scripts/create-kanban.py \
    --title "API Refactor" \
    --request "Refactor the API layer for better performance"
```

**Options:**
- `--title, -t` (required): Kanban title (used for filename)
- `--request, -r` (required): Original user request/description
- `--tasks-dir`: Directory for task files (default: ./tasks)

**Output:**
- Returns the filepath of the created kanban (e.g., `tasks/2-kanban-api-refactor.md`)

**What it does:**
1. Creates the kanban file with proper ID sequencing
2. Preserves user's design document in `request` field
3. Creates an empty kanban; Manager populates tasks separately (see `../role-manager.md`)

### 3. log-task.py

Logs work to a task file using a two-phase commit system with subcommands.

**Subcommands:**
- `generate` - Create temp file for writing work log
- `commit` - Read temp file and append formatted log to task
- `quick` - Directly log content without temp file

**Phase 1 - Generate temp file:**
```bash
# Generate creates ./tmp-{uuid}-log-content.md in workspace
TEMP_FILE=$(uv run .agents/skills/workflow/scripts/log-task.py generate ./tasks/0-explore.md "Initial Analysis")
echo "Temp file: $TEMP_FILE"
# Agent writes work log to $TEMP_FILE...
```

**Phase 2 - Commit log:**
```bash
# Commit reads temp, formats, appends to task, deletes temp
uv run .agents/skills/workflow/scripts/log-task.py commit ./tasks/0-explore.md "Initial Analysis" "$TEMP_FILE" --role Architect --new-state review
```

**Quick mode (direct content):**
```bash
# For simple logs, bypass temp file
uv run .agents/skills/workflow/scripts/log-task.py quick ./tasks/0-explore.md "Quick Update" "Fixed the bug in auth module" --role Architect --new-state review
```

**Subcommand Details:**

`generate TASK TITLE`
- Creates temp file: `./tmp-{uuid}-log-content.md`
- Output: Path to temp file (print only, for scripting)
- Temp file contains template with Facts/Analysis/Conclusion sections

`commit TASK TITLE TEMP_FILE`
- Reads temp file content
- Formats with timestamp and proper structure
- Appends to task file's Work Log section
- Deletes temp file
- Output: "Work log committed to: {task_file}"

`quick TASK TITLE CONTENT`
- Bypasses temp file creation
- Directly commits content as Facts section
- Analysis and Conclusion set to defaults
- Output: "Work log committed to: {task_file}"

**Why two-phase?**
- Agents can write freely without worrying about YAML frontmatter
- Proper formatting and timestamping is handled by the script
- Logs are consistently formatted with Facts/Analysis/Conclusion structure
- Workspace-local temp files are easy to find and edit

### 4. check-task.py

Generates agent briefing from task file metadata. Relieves Supervisor from manually crafting prompts for task agents.

**Usage:**
```bash
# Generate briefing for task agent
uv run .agents/skills/workflow/scripts/check-task.py --task tasks/0-design-api.md
# Or, if the script is executable:
.agents/skills/workflow/scripts/check-task.py --task tasks/0-design-api.md
```

**Output:**
Renders a standardized briefing that agents should follow:

```markdown
# Agent Briefing: Architect

**Task Type:** design
**Priority:** high

## Required Actions

1. **Read your role definition:** `role-architect.md`
   - You MUST understand your responsibilities
   - You MUST follow the algorithm specified in your role

2. **Design Mode Instructions:**
    - Populate the bounded **Work Items** block in the task file (between `<!-- start workitems -->` and `<!-- end workitems -->`)
    - Log work using log-task.py and transition state to `review`

3. **Load required skills:**
    - `code-reading` (read SKILL.md)

## Task Context

**Expertise Required:** System Design, Python
**Task File:** tasks/0-design-api.md

## Critical Reminders

**You MUST:**
- Read ALL required documentation before starting
- Follow your role's algorithm strictly
- Load and consult all required skills
- Write a work log using `log-task.py` before completing

**Do NOT:**
- Skip reading your role definition
- Deviate from your role's algorithm without escalation
- Spawn subagents or create new tasks

## Your Expertise

Apply your expertise in these domains:
- System Design
- Python

---

**Begin by reading:** `role-architect.md`
```

**Purpose:**
- Ensures agents always load their role definition
- Provides consistent task context
- Lists required skills and expertise
- Reminds agents of work log requirements

### 5. update-kanban.py

Updates kanban YAML frontmatter programmatically to reduce corruption from manual edits.

**Usage:**
```bash
uv run .agents/skills/workflow/scripts/update-kanban.py --kanban tasks/2-kanban-my-feature.md \
    --add-task tasks/3-some-task.md \
    --set-current tasks/3-some-task.md
```

This script updates only frontmatter fields like `tasks`, `current`, and `phase` and preserves the kanban body.

## File Naming Convention

All files in `./tasks/` use global sequenced numbering:

```
tasks/
├── 0-design-api.md              # Task: Design API (ID 0)
├── 1-implement-models.md        # Task: Implement Models (ID 1)
├── 2-kanban-api-refactor.md     # Kanban: API Refactor (ID 2)
├── 3-review-models.md           # Task: Review Models (ID 3)
└── 4-fix-bugs.md                # Task: Fix Bugs (ID 4)
```

## Task File Structure

```yaml
---
assignee: Architect
expertise: ['System Design', 'Python']
skills: ['code-reading']
type: design
priority: high
state: todo  # todo | review | done | escalated | cancelled
dependencies: []
refers: ['tasks/0-kanban-project.md']
kanban: tasks/0-kanban-project.md
created: 2026-02-25T11:38:30.998352
---

# Task: Design API Layer

## Context
Background information...

## Files
- src/api.py
- tests/test_api.py

## Description
What needs to be done...

## Work Log

### [2026-02-25 11:38:47] Initial Design Session

**Facts:**
- Analyzed requirements
- Reviewed existing code

**Analysis:**
- Identified key issues
- Proposed solutions

**Conclusion:**
- Design complete
- Ready for implementation

---
```

## Structured Work Items (Bounded Block)

Tasks include a script-validated Work Items section bounded by markers:

```md
## Work Items
<!-- start workitems -->
work_items: []
<!-- end workitems -->
```

Design tasks typically populate `work_items` before transitioning to `state: review`.

## Kanban File Structure

```yaml
---
type: kanban
title: API Refactor
created: 2026-02-25T11:38:34.470783
phase: exploration
current: null
tasks: []
---

# Kanban: API Refactor

## Request
Refactor the API layer for better performance

## Plan Adjustment Log

### [2026-02-25 11:45:00] KANBAN_CREATED

**Details:**
- **reason:** New request received
- **action:** Created exploration task
- **next_step:** Architect will explore codebase

### [2026-02-25 12:30:00] TASKS_CREATED

**Details:**
- **from_work_item:** Design API authentication
- **tasks_created:**
  - tasks/2-design-auth.md
  - tasks/3-implement-auth.md
```
