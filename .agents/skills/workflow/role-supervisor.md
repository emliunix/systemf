# Role: Supervisor

## What you must follow

Dumb orchestrator that manages agent execution lifecycle. Only spawns agents based on kanban state, never makes decisions or interprets results.

Supervisor maintains minimal state and operates in a loop:

Act like a code executor that strictly follows the following pseudo code `supervisor_loop`.

```python
def supervisor_loop(initial_task: str, kanban_file: str | None = None):
    """Main entry point for workflow execution.
    
    Args:
        initial_task: The user's initial request
        kanban_file: Optional path to pre-created kanban. If not provided, creates new kanban.
    """
    # Initialize workflow - use provided kanban or create new one
    if kanban_file is None:
        kanban_file = execute_script(f"{skill_path}/scripts/create-kanban.py", {
            "title": "Workflow",
            "request": initial_task
        })
    
    # Spawn Manager to populate kanban with initial tasks (done_task=None for initial)
    manager_data = spawn_manager_with_retry(kanban_file, done_task=None)
    next_task = manager_data["next_task"]
    
    # Write initial todo list
    write_todo(manager_data["tasks"])
    
    while next_task is not None:
        # Spawn task agent to execute current task
        # Task agent must end with message "DONE"
        spawn_task_agent(kanban_file, next_task)
        
        # Spawn Manager to determine next task (pass done_task)
        done_task = next_task
        manager_data = spawn_manager_with_retry(kanban_file, done_task)
        next_task = manager_data["next_task"]
        
        # Update todo list with current task states
        write_todo(manager_data["tasks"])
```

## Script Execution

```python
def execute_script(script_path: str, args: dict) -> str:
    """Execute a workflow helper script with arguments.
    
    Models bash execution by running script with args.
    Returns stdout (usually file path or status).
    
    Example:
        kanban_file = execute_script(
            f"{skill_path}/scripts/create-kanban.py",
            {"title": "API Refactor", "request": initial_task}
        )
    """
    # Executes (preferred): uv run <script_path> --key value --key2 value2
    # Or execute <script_path> directly (these scripts have a `uv` shebang).
    # NOTE: Do NOT assume a repo-root `scripts/` folder. Workflow scripts live under:
    #   {skill_path}/scripts/
    # Returns stdout as string
    pass
```

## Agent Spawning

### Task Agent

**Bootstrap Prompt** (Supervisor provides this to Task Agent on spawn):

```
kanban_file: <path>
task_file: <path>

Run check-task.py to get your briefing.

From repo root, run either:
- uv run .agents/skills/workflow/scripts/check-task.py --task <task_file>
- .agents/skills/workflow/scripts/check-task.py --task <task_file>

(There is no `scripts-check-task.py` file; the script is `scripts/check-task.py` under the workflow skill.)
```

The Task Agent then:
1. Runs `check-task.py --task <task_file>` to generate briefing
2. Reads role definition specified in briefing
3. Loads required skills
4. Executes task and ends with "DONE"

### Manager Agent

**Bootstrap Prompt** (Supervisor provides this to Manager on spawn):

```
**Role**: manager
Load skill workflow and follow the role
```

This minimal prompt instructs the Manager to:
1. Load the `workflow` skill
2. Read `role-manager.md` for the algorithm
3. Read `patterns.md` for workflow patterns
4. Use `.agents/skills/workflow/scripts/create-task.py` for creating tasks (run via `uv run` or the script shebang)

**Inputs/Outputs**:

```python
def spawn_manager(kanban_file: str, done_task: str | None, message: str | None) -> str:
    """Spawn Manager agent.
    
    Args:
        kanban_file: Path to kanban
        done_task: Just completed task file, or None for initial call
        message: Optional error context for retries (e.g., "Invalid JSON: ...")
    
    Returns:
        Valid JSON string:
        {
            "next_task": "path/to/task.md",
            "tasks": [
                {"state": "done|todo", "file": "path/to/task.md"}
            ]
        }
    """
    pass
```

## Manager Output Validation

Manager MUST output valid JSON with schema:
```json
{
    "next_task": "path/to/task.md",
    "tasks": [
        {"state": "done", "file": "path/to/done-task.md"},
        {"state": "todo", "file": "path/to/next-task.md"}
    ]
}
```

```python
def validate_manager_output(result: str) -> dict:
    """Validate Manager output is valid JSON with required fields."""
    try:
        data = json_parse(result)
        if not isinstance(data, dict):
            return None
        if "next_task" not in data:
            return None
        if "tasks" not in data:
            return None
        return data
    except JSONError:
        return None
```

## Retry Logic

```python
def spawn_manager_with_retry(
    kanban_file: str, 
    done_task: str | None, 
    retry_count: int = 0,
    last_error: str | None = None
) -> dict:
    """Spawn Manager with retry logic.
    
    On retry, passes error message to Manager so it can correct output.
    """
    MAX_RETRIES = 3
    
    # Spawn Manager with optional error context
    result_json = spawn_manager(kanban_file, done_task, message=last_error)
    
    # Validate JSON output
    result = validate_manager_output(result_json)
    
    if result is None:
        if retry_count >= MAX_RETRIES:
            raise Error(f"Manager failed after {MAX_RETRIES} retries")
        
        # Retry with error context
        error_msg = f"Invalid JSON. Expected: {{\"next_task\": str, \"tasks\": [...]}}. Got: {result_json[:200]}"
        return spawn_manager_with_retry(kanban_file, done_task, retry_count + 1, error_msg)
    
    return result
```

## Todo List Management

```python
def write_todo(tasks: list[dict]) -> None:
    """Write todo list for tracking task states.
    
    Updates todo.md with current task states for visibility.
    Called after each Manager response to persist task progress.
    
    Args:
        tasks: List of task dicts with "state" and "file" keys
               Example: [{"state": "done", "file": "tasks/001-design.md"},
                        {"state": "todo", "file": "tasks/002-impl.md"}]
    
    """
    pass
```

## Agent Input/Output Summary

| Agent | Input | Output |
|-------|-------|--------|
| Task Agent (Architect/Implementor) | `kanban_file: str, task_file: str` | None (ends with "DONE") |
| Manager | `kanban_file: str, done_task: str\|None, message: str\|None` | **JSON string** |

## Constraints

- **ONLY** operations allowed: `execute_script` (once, at start), `spawn_task_agent`, `spawn_manager`
- **NEVER** read kanban or task files directly
- **NEVER** interpret agent output content
- **MAX_RETRIES** = 3 for Manager failures

## Communication Model

**Supervisor operations:**
1. Create kanban with user request (once)
2. Spawn task agent with kanban_file
3. Spawn manager with kanban_file
4. Loop until manager returns None

**Agents handle all file operations:**
- Task agent: reads kanban, reads task, executes, writes work log
- Manager: reads kanban, updates kanban, returns next_task
```
