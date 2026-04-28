#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyyaml"]
# requires-python = ">=3.12"
# ///
"""Update a kanban file frontmatter programmatically.

Purpose:
- Avoid manual YAML edits to kanban files (reduces corruption)
- Manage the `tasks` list and `current` pointer in a consistent way

This script updates ONLY the YAML frontmatter. It preserves the kanban body.

Usage:
  .agents/skills/workflow/scripts/update-kanban.py --kanban tasks/2-kanban-foo.md \
    --add-task tasks/3-some-task.md \
    --set-current tasks/3-some-task.md

  .agents/skills/workflow/scripts/update-kanban.py --kanban tasks/2-kanban-foo.md \
    --remove-task tasks/3-some-task.md

  .agents/skills/workflow/scripts/update-kanban.py --kanban tasks/2-kanban-foo.md \
    --set-phase design

Notes:
- This is intended for Manager usage (workflow coordination).
- It does not append to the Plan Adjustment Log; Manager should log decisions separately.
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def parse_frontmatter(content: str) -> tuple[dict, str] | None:
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    front = parts[1]
    body = parts[2]

    data = yaml.safe_load(front) or {}
    if not isinstance(data, dict):
        return None

    return data, body


def yaml_quote(text: str) -> str:
    # YAML single-quote escaping: '' represents a literal '
    return "'" + text.replace("'", "''") + "'"


def format_yaml_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return yaml_quote(value)
    if isinstance(value, list):
        formatted_items: list[str] = []
        for item in value:
            if item is None:
                formatted_items.append("null")
            elif isinstance(item, str):
                formatted_items.append(yaml_quote(item))
            else:
                formatted_items.append(str(item))
        return "[" + ", ".join(formatted_items) + "]"
    return yaml_quote(str(value))


def format_frontmatter(data: dict) -> str:
    # Keep ordering stable and human-readable
    ordered_keys = ["type", "title", "created", "phase", "current", "tasks"]
    lines: list[str] = ["---"]
    for key in ordered_keys:
        if key in data:
            lines.append(f"{key}: {format_yaml_value(data[key])}")

    # Include any other keys at the end
    for key in sorted(k for k in data.keys() if k not in ordered_keys):
        lines.append(f"{key}: {format_yaml_value(data[key])}")

    lines.append("---")
    return "\n".join(lines) + "\n"


def uniq_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Update a workflow kanban YAML frontmatter safely")
    p.add_argument("--kanban", "-k", required=True, help="Path to kanban markdown file")
    p.add_argument("--add-task", action="append", default=[], help="Task path to add (can be repeated)")
    p.add_argument("--remove-task", action="append", default=[], help="Task path to remove (can be repeated)")
    p.add_argument("--set-current", default=None, help="Set current task path (must exist in tasks list after updates)")
    p.add_argument("--clear-current", action="store_true", help="Set current to null")
    p.add_argument("--set-phase", default=None, help="Set kanban phase (e.g., exploration, design, execute)")

    args = p.parse_args()

    kanban_path = Path(args.kanban)
    if not kanban_path.exists():
        print(f"Error: kanban file not found: {kanban_path}", file=sys.stderr)
        sys.exit(1)

    content = kanban_path.read_text(encoding="utf-8")
    parsed = parse_frontmatter(content)
    if parsed is None:
        print("Error: invalid kanban format (missing/invalid YAML frontmatter)", file=sys.stderr)
        sys.exit(1)

    data, body = parsed

    if data.get("type") != "kanban":
        print(f"Error: expected type: kanban, got: {data.get('type')}", file=sys.stderr)
        sys.exit(1)

    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        print("Error: kanban frontmatter `tasks` must be a list", file=sys.stderr)
        sys.exit(1)

    tasks = [str(t) for t in tasks]

    # Apply mutations
    for t in args.add_task:
        tasks.append(t)

    remove_set = set(args.remove_task)
    if remove_set:
        tasks = [t for t in tasks if t not in remove_set]

    tasks = uniq_preserve_order(tasks)
    data["tasks"] = tasks

    if args.set_phase is not None:
        data["phase"] = args.set_phase

    if args.clear_current:
        data["current"] = None
    elif args.set_current is not None:
        if args.set_current not in tasks:
            print(
                "Error: --set-current must refer to a task present in kanban tasks list (after updates)",
                file=sys.stderr,
            )
            sys.exit(1)
        data["current"] = args.set_current

    new_content = format_frontmatter(data) + body.lstrip("\n")
    kanban_path.write_text(new_content, encoding="utf-8")

    print(f"Updated kanban: {kanban_path}")


if __name__ == "__main__":
    main()
