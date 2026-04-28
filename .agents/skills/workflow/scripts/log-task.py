#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyyaml"]
# requires-python = ">=3.12"
# ///
"""Log work to a task file using two-phase commit.

Two-phase logging separates writing from formatting:
1. generate: Creates temp file for agent to write work log
2. commit: Reads temp file, formats, appends to task, cleans up

Usage:
    # Generate temp file (Phase 1)
    .agents/skills/workflow/scripts/log-task.py generate ./tasks/0-explore.md "Initial Analysis"
    # Returns: ./tmp-abc12345-log-content.md

    # Agent edits the temp file...

    # Commit log (Phase 2) - REQUIRES --role and --new-state
    .agents/skills/workflow/scripts/log-task.py commit ./tasks/0-explore.md "Initial Analysis" ./tmp-abc12345-log-content.md --role Architect --new-state review

    # Implementor sets review state
    .agents/skills/workflow/scripts/log-task.py commit ./tasks/0-impl.md "Ready" ./tmp-abc12345-log-content.md --role Implementor --new-state review

    # Architect approves to done
    .agents/skills/workflow/scripts/log-task.py commit ./tasks/0-impl.md "Approved" ./tmp-abc12345-log-content.md --role Architect --new-state done

Single-phase mode for quick logs:
    .agents/skills/workflow/scripts/log-task.py quick ./tasks/0-explore.md "Quick Log" "Fixed the bug" --role Architect --new-state done

State transition rules:
- todo → review: Implementation complete (MANDATORY for Implementor)
- review → done: Review passed (ONLY Architect can set 'done')
- Any → escalated: Issues found
- Any → cancelled: Task cancelled
"""

import argparse
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


def generate_temp_template(title: str) -> str:
    """Generate the template for the temporary work log file."""
    return f"""# Work Log: {title}

## Facts
<!-- What was actually done (files modified, code written, tests run, etc.) -->
-

## Analysis
<!-- What problems were encountered, what approaches were tried, key decisions made -->
-

## Conclusion
<!-- Pass/fail/escalate status and why, next steps, blockers if any -->
Status: <!-- ok / blocked / escalate -->

<!-- Additional notes -->
"""


def get_current_state(task_content: str) -> str | None:
    """Extract the current state from YAML frontmatter."""
    if not task_content.startswith("---"):
        return None

    frontmatter_end = task_content.find("\n---", 3)
    if frontmatter_end == -1:
        return None

    frontmatter = task_content[:frontmatter_end]
    match = re.search(r"^state:\s*(\w+)", frontmatter, re.MULTILINE)
    return match.group(1) if match else None


def get_assignee(task_content: str) -> str | None:
    """Extract the assignee from YAML frontmatter."""
    if not task_content.startswith("---"):
        return None

    frontmatter_end = task_content.find("\n---", 3)
    if frontmatter_end == -1:
        return None

    frontmatter = task_content[:frontmatter_end]
    match = re.search(r"^assignee:\s*(\w+)", frontmatter, re.MULTILINE)
    return match.group(1) if match else None


def get_task_type(task_content: str) -> str | None:
    """Extract the task type from YAML frontmatter."""
    if not task_content.startswith("---"):
        return None

    frontmatter_end = task_content.find("\n---", 3)
    if frontmatter_end == -1:
        return None

    frontmatter = task_content[:frontmatter_end]
    match = re.search(r"^type:\s*(\w+)", frontmatter, re.MULTILINE)
    return match.group(1) if match else None


def extract_bounded_block(task_content: str, start_marker: str, end_marker: str) -> str | None:
    """Extract content between two marker lines (exclusive)."""
    start_idx = task_content.find(start_marker)
    if start_idx == -1:
        return None
    end_idx = task_content.find(end_marker, start_idx + len(start_marker))
    if end_idx == -1:
        return None
    return task_content[start_idx + len(start_marker) : end_idx].strip()


def validate_work_items_block(task_content: str) -> tuple[bool, str]:
    """Validate the structured Work Items block.

    The canonical block is bounded by:
      <!-- start workitems -->
      ...YAML...
      <!-- end workitems -->

    The YAML must parse into a mapping with key `work_items` whose value is a list.
    """
    block = extract_bounded_block(task_content, "<!-- start workitems -->", "<!-- end workitems -->")
    if block is None:
        return False, "Missing Work Items block markers (<!-- start workitems --> ... <!-- end workitems -->)."

    try:
        data = yaml.safe_load(block)
    except Exception as e:
        return False, f"Invalid YAML in Work Items block: {e}"

    if not isinstance(data, dict):
        return False, "Work Items block YAML must be a mapping (e.g., work_items: [])."
    if "work_items" not in data:
        return False, "Work Items block YAML must contain `work_items`."
    if not isinstance(data["work_items"], list):
        return False, "`work_items` must be a list."

    return True, ""


def validate_state_transition(current_state: str | None, new_state: str, role: str) -> tuple[bool, str]:
    """Validate state transition follows workflow rules and role permissions.

    Allowed transitions:
    - todo → review: Implementation complete, ready for review (MANDATORY)
    - review → done: Review passed (Only path to done)
    - review → escalated: Review found issues
    - escalated → todo: Prerequisites complete, retry
    - escalated → done: Escalation resolved
    - Any → cancelled: Task cancelled

    Forbidden:
    - todo → done: Direct completion without review
    - Implementor setting state to 'done': Only Architect can approve
    """
    if current_state is None:
        return True, ""

    # Forbidden: todo → done (direct completion)
    if current_state == "todo" and new_state == "done":
        return False, "Forbidden transition: todo → done. All work MUST be reviewed. Use 'review' state instead."

    # Role-based restrictions: Implementor cannot set 'done'
    if role == "Implementor" and new_state == "done":
        return (
            False,
            "Role permission denied: Implementor cannot set state to 'done'. "
            "Only Architect can approve work. Use 'review' or 'escalated' instead.",
        )

    # Allowed transitions
    allowed = {
        "todo": ["review", "cancelled"],
        "review": ["done", "escalated", "cancelled"],
        "escalated": ["todo", "done", "cancelled"],
        "done": ["cancelled"],  # Can cancel even completed tasks
        "cancelled": [],  # Terminal state
    }

    valid_next = allowed.get(current_state, [])
    if new_state in valid_next:
        return True, ""

    return (
        False,
        f"Invalid transition: {current_state} → {new_state}. Allowed from {current_state}: {', '.join(valid_next)}",
    )


def update_task_state(task_content: str, new_state: str) -> str:
    """Update the state field in the YAML frontmatter."""
    # Pattern to match state: value in YAML frontmatter
    pattern = r"^(state:\s*)\w+"

    # Check if there's a YAML frontmatter
    if not task_content.startswith("---"):
        return task_content

    # Find the end of frontmatter
    frontmatter_end = task_content.find("\n---", 3)
    if frontmatter_end == -1:
        return task_content

    # Update state within the frontmatter
    updated = re.sub(pattern, f"\\g<1>{new_state}", task_content, count=1, flags=re.MULTILINE)
    return updated


def format_work_log(title: str, content: str) -> str:
    """Format the work log entry with proper structure."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Extract sections from content
    facts_match = re.search(r"## Facts\s*(.*?)(?=## Analysis|$)", content, re.DOTALL)
    analysis_match = re.search(r"## Analysis\s*(.*?)(?=## Conclusion|$)", content, re.DOTALL)
    conclusion_match = re.search(r"## Conclusion\s*(.*?)(?=## |$)", content, re.DOTALL)

    facts = facts_match.group(1).strip() if facts_match else "<!-- No facts recorded -->"
    analysis = analysis_match.group(1).strip() if analysis_match else "<!-- No analysis recorded -->"
    conclusion = conclusion_match.group(1).strip() if conclusion_match else "<!-- No conclusion recorded -->"

    return f"""### [{timestamp}] {title}

**Facts:**
{facts}

**Analysis:**
{analysis}

**Conclusion:**
{conclusion}

---

"""


def cmd_generate(task_file: Path, title: str) -> None:
    """Generate subcommand: Create temp file for agent to write to."""
    if not task_file.exists():
        print(f"Error: Task file not found: {task_file}", file=sys.stderr)
        sys.exit(1)

    # Create temp file in workspace with UUID
    temp_filename = f"./tmp-{uuid.uuid4().hex[:8]}-log-content.md"
    temp_path = Path(temp_filename)

    template = generate_temp_template(title)
    temp_path.write_text(template, encoding="utf-8")

    # Print only the path (for scripting)
    print(temp_path)


def cmd_commit(task_file: Path, title: str, temp_file: Path, role: str, new_state: str) -> None:
    """Commit subcommand: Read temp file and append formatted log to task."""
    if not task_file.exists():
        print(f"Error: Task file not found: {task_file}", file=sys.stderr)
        sys.exit(1)

    if not temp_file.exists():
        print(f"Error: Temp file not found: {temp_file}", file=sys.stderr)
        sys.exit(1)

    # Read temp file content
    content = temp_file.read_text(encoding="utf-8")

    # Remove the title line since we'll use it in the formatted log
    content = re.sub(r"^# Work Log:.*?\n", "", content, count=1)

    # Format the log entry
    log_entry = format_work_log(title, content)

    # Read task file
    task_content = task_file.read_text(encoding="utf-8")

    # Validate work items block for design tasks when publishing for review/done
    task_type = get_task_type(task_content)
    if task_type == "design" and new_state in {"review", "done"}:
        ok, msg = validate_work_items_block(task_content)
        if not ok:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)

    # Validate and update state (required)
    current_state = get_current_state(task_content)
    is_valid, error_msg = validate_state_transition(current_state, new_state, role)
    if not is_valid:
        print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(1)
    task_content = update_task_state(task_content, new_state)

    # Check if Work Log section exists
    if "## Work Log" not in task_content:
        task_content += "\n\n## Work Log\n\n"

    # Append log entry
    task_content = task_content.rstrip() + "\n\n" + log_entry

    # Write back
    task_file.write_text(task_content, encoding="utf-8")

    # Clean up temp file
    temp_file.unlink()

    print(f"Work log committed to: {task_file} (state: {new_state})")


def cmd_quick(task_file: Path, title: str, content: str, role: str, new_state: str) -> None:
    """Quick subcommand: Directly log content without temp file."""
    if not task_file.exists():
        print(f"Error: Task file not found: {task_file}", file=sys.stderr)
        sys.exit(1)

    # Create minimal content
    temp_content = f"# Work Log\n\n## Facts\n{content}\n\n## Analysis\n-\n\n## Conclusion\nStatus: ok\n"

    # Format and commit directly
    log_entry = format_work_log(title, temp_content)

    task_content = task_file.read_text(encoding="utf-8")

    # Validate work items block for design tasks when publishing for review/done
    task_type = get_task_type(task_content)
    if task_type == "design" and new_state in {"review", "done"}:
        ok, msg = validate_work_items_block(task_content)
        if not ok:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)

    # Validate and update state (required)
    current_state = get_current_state(task_content)
    is_valid, error_msg = validate_state_transition(current_state, new_state, role)
    if not is_valid:
        print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(1)
    task_content = update_task_state(task_content, new_state)

    if "## Work Log" not in task_content:
        task_content += "\n\n## Work Log\n\n"

    task_content = task_content.rstrip() + "\n\n" + log_entry
    task_file.write_text(task_content, encoding="utf-8")

    print(f"Work log committed to: {task_file} (state: {new_state})")


def main():
    parser = argparse.ArgumentParser(
        description="Log work to a task file using two-phase commit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SUBCOMMANDS:

  generate TASK TITLE
    Creates a temp markdown file for you to write your work log.
    The temp file is created in the workspace (./tmp-{uuid}-log-content.md).
    Output: Path to temp file (print only).
    
    Example:
      .agents/skills/workflow/scripts/log-task.py generate ./tasks/0-explore.md "Analysis"

  commit TASK TITLE TEMP_FILE --role ROLE --new-state STATE
    Reads the temp file, formats with timestamp, appends to task, deletes temp.
    This is Phase 2 - call after editing the temp file.
    REQUIRES: --role (who is logging) and --new-state (state transition).
    NOTE: Direct todo→done is forbidden. Must go through review state.
    NOTE: Implementor cannot set 'done' - only Architect can approve.

    Example:
      .agents/skills/workflow/scripts/log-task.py commit ./tasks/0-explore.md "Analysis" ./tmp-abc12345-log-content.md --role Architect --new-state review
      .agents/skills/workflow/scripts/log-task.py commit ./tasks/0-impl.md "Ready for Review" ./tmp-abc12345-log-content.md --role Implementor --new-state review
      .agents/skills/workflow/scripts/log-task.py commit ./tasks/0-impl.md "Review Passed" ./tmp-abc12345-log-content.md --role Architect --new-state done

  quick TASK TITLE CONTENT --role ROLE --new-state STATE
    For simple logs, bypass temp file and commit directly.
    REQUIRES: --role (who is logging) and --new-state (state transition).
    NOTE: Direct todo→done is forbidden. Must go through review state.
    NOTE: Implementor cannot set 'done' - only Architect can approve.

    Example:
      .agents/skills/workflow/scripts/log-task.py quick ./tasks/0-explore.md "Fix" "Fixed the auth bug" --role Architect --new-state done
      .agents/skills/workflow/scripts/log-task.py quick ./tasks/0-impl.md "Ready" "Implementation complete" --role Implementor --new-state review

WORK LOG FORMAT:
  Each log entry includes:
  - Timestamp
  - Facts (what was done)
  - Analysis (decisions, problems)
  - Conclusion (status: ok/blocked/escalate)
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # generate subcommand
    gen_parser = subparsers.add_parser(
        "generate",
        help="Create temp file for writing work log",
        description="Creates a temp markdown file (./tmp-{uuid}-log-content.md) for agent to write work log. Prints path only.",
    )
    gen_parser.add_argument("task", help="Path to the task file")
    gen_parser.add_argument("title", help="Title for this work log entry")

    # commit subcommand
    commit_parser = subparsers.add_parser(
        "commit",
        help="Commit temp file to task",
        description="Reads temp file, formats with timestamp, appends to task, deletes temp file.",
    )
    commit_parser.add_argument("task", help="Path to the task file")
    commit_parser.add_argument("title", help="Title for this work log entry")
    commit_parser.add_argument("temp_file", help="Path to temp file from generate command")
    commit_parser.add_argument(
        "--role",
        "-r",
        required=False,
        choices=["Architect", "Implementor", "Manager", "Supervisor", "user"],
        help="Role of the agent logging work (actor role). Used for permission checks.",
    )
    commit_parser.add_argument(
        "--actor-role",
        required=False,
        choices=["Architect", "Implementor", "Manager", "Supervisor", "user"],
        help="Alias for --role (who is logging).",
    )
    commit_parser.add_argument(
        "--new-state",
        required=True,
        choices=["todo", "review", "done", "escalated", "cancelled"],
        help="Update task state (todo → review → done). Direct todo→done is forbidden. Implementor cannot set 'done'.",
    )

    # quick subcommand
    quick_parser = subparsers.add_parser(
        "quick",
        help="Quick log without temp file",
        description="Directly log content without creating temp file. For simple one-line logs.",
    )
    quick_parser.add_argument("task", help="Path to the task file")
    quick_parser.add_argument("title", help="Title for this work log entry")
    quick_parser.add_argument("content", help="Content for Facts section")
    quick_parser.add_argument(
        "--role",
        "-r",
        required=False,
        choices=["Architect", "Implementor", "Manager", "Supervisor", "user"],
        help="Role of the agent logging work (actor role). Used for permission checks.",
    )
    quick_parser.add_argument(
        "--actor-role",
        required=False,
        choices=["Architect", "Implementor", "Manager", "Supervisor", "user"],
        help="Alias for --role (who is logging).",
    )
    quick_parser.add_argument(
        "--new-state",
        required=True,
        choices=["todo", "review", "done", "escalated", "cancelled"],
        help="Update task state (todo → review → done). Direct todo→done is forbidden. Implementor cannot set 'done'.",
    )

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(Path(args.task), args.title)
    elif args.command == "commit":
        actor_role = args.role or args.actor_role
        if not actor_role:
            print("Error: missing required argument: --role/--actor-role", file=sys.stderr)
            sys.exit(1)
        cmd_commit(Path(args.task), args.title, Path(args.temp_file), actor_role, args.new_state)
    elif args.command == "quick":
        actor_role = args.role or args.actor_role
        if not actor_role:
            print("Error: missing required argument: --role/--actor-role", file=sys.stderr)
            sys.exit(1)
        cmd_quick(Path(args.task), args.title, args.content, actor_role, args.new_state)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
