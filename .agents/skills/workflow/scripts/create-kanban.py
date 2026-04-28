#!/usr/bin/env -S uv run --script
# /// script
# dependencies = []
# requires-python = ">=3.12"
# ///
"""Create a new kanban file with validated YAML header.

Usage:
    .agents/skills/workflow/scripts/create-kanban.py --title "API Refactor" --request "Refactor the API layer"
    .agents/skills/workflow/scripts/create-kanban.py -t "Bug Fix" -r "Fix critical authentication bug"

The script will:
1. Validate required fields
2. Generate the next sequential ID
3. Create the kanban file with proper YAML header
4. Return the file path

Note: Tasks are created separately using create-task.py by the Manager.
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


def get_next_id(tasks_dir: Path) -> int:
    """Get the next sequential ID from existing files."""
    if not tasks_dir.exists():
        return 0

    max_id = -1
    for f in tasks_dir.iterdir():
        if f.is_file() and f.suffix == ".md":
            match = re.match(r"^(\d+)-", f.name)
            if match:
                file_id = int(match.group(1))
                max_id = max(max_id, file_id)

    return max_id + 1


def generate_kanban_header(title: str, tasks: list[str]) -> str:
    """Generate the YAML header for a kanban file."""
    header = "---\n"
    header += f"type: kanban\n"
    header += f"title: {title}\n"
    header += f"created: {datetime.now().isoformat()}\n"
    header += f"phase: exploration\n"
    header += f"current: null\n"
    header += f"tasks: {tasks}\n"
    header += "---\n"
    return header


def generate_kanban_content(title: str, request: str) -> str:
    """Generate the kanban body content."""
    content = f"\n# Kanban: {title}\n\n"
    content += "## Request\n"
    content += f"{request}\n\n"
    content += "## Plan Adjustment Log\n"
    content += "<!-- Manager logs plan adjustments here -->\n\n"
    return content


def main():
    parser = argparse.ArgumentParser(
        description="Create a new kanban file with validated YAML header",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  .agents/skills/workflow/scripts/create-kanban.py --title "API Refactor" --request "Refactor the API layer"
  .agents/skills/workflow/scripts/create-kanban.py -t "Bug Fix" -r "Fix critical authentication bug"

Note: Create tasks separately using create-task.py
        """,
    )

    parser.add_argument("--title", "-t", required=True, help="Kanban title (used for filename)")
    parser.add_argument("--request", "-r", required=True, help="Original user request/description")
    parser.add_argument("--tasks-dir", default="./tasks", help="Directory for task files (default: ./tasks)")

    args = parser.parse_args()

    # Ensure tasks directory exists
    tasks_dir = Path(args.tasks_dir)
    if tasks_dir.exists() and not tasks_dir.is_dir():
        print(f"Error: tasks-dir '{tasks_dir}' exists but is not a directory", file=sys.stderr)
        sys.exit(1)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    # Generate kanban ID and filename
    kanban_id = get_next_id(tasks_dir)
    slug = slugify(args.title)
    filename = f"{kanban_id}-kanban-{slug}.md"
    filepath = tasks_dir / filename

    # Generate file content (empty tasks list - Manager adds tasks separately)
    header = generate_kanban_header(title=args.title, tasks=[])
    body = generate_kanban_content(title=args.title, request=args.request)

    # Write file
    filepath.write_text(header + body, encoding="utf-8")

    # Output the filepath
    print(filepath)


if __name__ == "__main__":
    main()
