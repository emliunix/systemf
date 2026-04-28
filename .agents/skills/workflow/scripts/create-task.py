#!/usr/bin/env -S uv run --script
# /// script
# dependencies = []
# requires-python = ">=3.12"
# ///
"""Create a new task file with validated YAML header.

Usage:
    .agents/skills/workflow/scripts/create-task.py --assignee Architect --expertise "System Design,Python" --kanban tasks/0-kanban.md --creator-role manager --title "Design API"

The script will:
1. Validate required fields (assignee, expertise, kanban, creator-role)
2. Check creator-role is allowed (manager or user only)
3. Generate the next sequential ID
4. Create the task file with proper YAML header
5. Return the file path
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Valid values for validation
VALID_ASSIGNEES = ["Architect", "Implementor"]
VALID_TYPES = ["exploration", "design", "review", "implement", "redesign"]
VALID_PRIORITIES = ["critical", "high", "medium", "low"]
VALID_CREATOR_ROLES = ["manager", "user", "architect", "implementor"]
ALLOWED_CREATOR_ROLES = ["manager", "user"]


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


def get_next_id(tasks_dir: Path) -> int:
    """Get the next sequential ID from existing task files."""
    if not tasks_dir.exists():
        return 0

    max_id = -1
    for f in tasks_dir.iterdir():
        if f.is_file() and f.suffix == ".md":
            match = re.match(r"^(\d+)-", f.name)
            if match:
                task_id = int(match.group(1))
                max_id = max(max_id, task_id)

    return max_id + 1


def validate_assignee(assignee: str) -> str:
    """Validate assignee is one of the allowed values."""
    if assignee not in VALID_ASSIGNEES:
        print(f"Error: Invalid assignee '{assignee}'. Must be one of: {', '.join(VALID_ASSIGNEES)}", file=sys.stderr)
        sys.exit(1)
    return assignee


def validate_creator_role(creator_role: str) -> str:
    """Validate creator_role is allowed to create tasks (manager or user only)."""
    if creator_role not in ALLOWED_CREATOR_ROLES:
        print(f"Error: role '{creator_role}' is not allowed to create task", file=sys.stderr)
        sys.exit(1)
    return creator_role


def parse_list(value: str) -> list[str]:
    """Parse comma-separated string into list."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def infer_task_type(assignee: str, title: str) -> str:
    """Infer task type from assignee and title."""
    title_lower = title.lower()

    if "explor" in title_lower:
        return "exploration"
    elif "design" in title_lower:
        return "design"
    elif "review" in title_lower:
        return "review"
    elif "redesign" in title_lower:
        return "redesign"
    elif assignee == "Architect":
        return "design"
    else:
        return "implement"


def generate_task_header(
    assignee: str,
    expertise: list[str],
    skills: list[str],
    task_type: str,
    priority: str,
    dependencies: list[str],
    refers: list[str],
    kanban: str,
) -> str:
    """Generate the YAML header for a task file."""
    header = "---\n"
    header += f"assignee: {assignee}\n"
    header += f"expertise: {expertise}\n"
    header += f"skills: {skills}\n"
    header += f"type: {task_type}\n"
    header += f"priority: {priority}\n"
    header += f"state: todo\n"
    header += f"dependencies: {dependencies}\n"
    header += f"refers: {refers}\n"
    header += f"kanban: {kanban}\n"
    header += f"created: {datetime.now().isoformat()}\n"
    header += "---\n"
    return header


def generate_task_content(title: str, context: str = "", files: str = "", description: str = "") -> str:
    """Generate the task body content."""
    content = f"\n# Task: {title}\n\n"

    if context:
        content += "## Context\n"
        content += f"{context}\n\n"
    else:
        content += "## Context\n"
        content += "<!-- Background information and relevant context -->\n\n"

    if files:
        content += "## Files\n"
        for f in parse_list(files):
            content += f"- {f}\n"
        content += "\n"
    else:
        content += "## Files\n"
        content += "<!-- List of files to modify or reference -->\n\n"

    if description:
        content += "## Description\n"
        content += f"{description}\n\n"
    else:
        content += "## Description\n"
        content += "<!-- What needs to be done -->\n\n"

    content += "## Work Items\n"
    content += "<!-- Structured, script-validated work items for Manager -->\n"
    content += "<!-- start workitems -->\n"
    content += "work_items: []\n"
    content += "<!-- end workitems -->\n\n"

    content += "## Work Log\n"
    content += "<!-- Work logs will be appended here -->\n"

    return content


def main():
    parser = argparse.ArgumentParser(
        description="Create a new task file with validated YAML header",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  .agents/skills/workflow/scripts/create-task.py --assignee Architect --expertise "System Design,Python" --kanban tasks/0-kanban.md --creator-role manager --title "Design API"
  .agents/skills/workflow/scripts/create-task.py -a Implementor -e "Software Engineering" -k tasks/0-kanban.md -cr user -t "Fix bug"
        """,
    )

    parser.add_argument(
        "--assignee",
        "-a",
        required=True,
        choices=VALID_ASSIGNEES,
        help=f"Task assignee. Must be one of: {', '.join(VALID_ASSIGNEES)}",
    )
    parser.add_argument(
        "--expertise",
        "-e",
        required=True,
        help='Comma-separated list of expertise areas (e.g., "System Design,Python")',
    )
    parser.add_argument(
        "--skills", "-s", default="", help='Comma-separated list of skills to load (e.g., "code-reading,testing")'
    )
    parser.add_argument("--title", "-t", required=True, help="Task title (used for filename)")
    parser.add_argument("--type", choices=VALID_TYPES, help="Task type (auto-inferred from title if not specified)")
    parser.add_argument(
        "--priority", choices=VALID_PRIORITIES, default="medium", help="Task priority (default: medium)"
    )
    parser.add_argument("--dependencies", "-d", default="", help="Comma-separated list of task file dependencies")
    parser.add_argument("--refers", default="", help="Comma-separated list of related task files to reference")
    parser.add_argument("--context", "-c", default="", help="Task context/description")
    parser.add_argument("--files", "-f", default="", help="Comma-separated list of relevant files")
    parser.add_argument("--description", default="", help="Detailed task description")
    parser.add_argument("--tasks-dir", default="./tasks", help="Directory for task files (default: ./tasks)")
    parser.add_argument("--kanban", "-k", required=True, help="Path to kanban file for global context")
    parser.add_argument(
        "--creator-role",
        "-cr",
        required=True,
        choices=VALID_CREATOR_ROLES,
        help="Role of the creator. Only manager and user are allowed to create tasks. Architect and Implementor should NEVER create task files.",
    )

    args = parser.parse_args()

    # Validate inputs
    assignee = validate_assignee(args.assignee)
    creator_role = validate_creator_role(args.creator_role)
    expertise = parse_list(args.expertise)
    skills = parse_list(args.skills)
    dependencies = parse_list(args.dependencies)
    refers = parse_list(args.refers)
    task_type = args.type or infer_task_type(assignee, args.title)

    # Invariant: every task must carry a pointer back to its kanban via `refers`.
    # (The canonical pointer is also stored in the `kanban:` field.)
    if args.kanban and args.kanban not in refers:
        refers.append(args.kanban)

    # Ensure tasks directory exists
    tasks_dir = Path(args.tasks_dir)
    if tasks_dir.exists() and not tasks_dir.is_dir():
        print(f"Error: tasks-dir '{tasks_dir}' exists but is not a directory", file=sys.stderr)
        sys.exit(1)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    # Generate next ID and filename
    task_id = get_next_id(tasks_dir)
    slug = slugify(args.title)
    filename = f"{task_id}-{slug}.md"
    filepath = tasks_dir / filename

    # Generate file content
    header = generate_task_header(
        assignee=assignee,
        expertise=expertise,
        skills=skills,
        task_type=task_type,
        priority=args.priority,
        dependencies=dependencies,
        refers=refers,
        kanban=args.kanban,
    )
    body = generate_task_content(title=args.title, context=args.context, files=args.files, description=args.description)

    # Write file
    filepath.write_text(header + body, encoding="utf-8")

    # Output the filepath
    print(filepath)


if __name__ == "__main__":
    main()
