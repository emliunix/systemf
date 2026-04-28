#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyyaml"]
# requires-python = ">=3.12"
# ///
"""
check-task.py - Generate agent briefing from task file metadata.

Relieves Supervisor from manually prompting agents by extracting
task metadata and rendering a standardized briefing.

Usage:
    check-task.py --task tasks/0-design-api.md
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate agent briefing from task file metadata")
    parser.add_argument("--task", "-t", required=True, help="Path to task file (e.g., tasks/0-design-api.md)")
    return parser.parse_args()


def read_task_metadata(task_path: str) -> dict:
    """Read YAML frontmatter from task file."""
    path = Path(task_path)
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {task_path}")

    content = path.read_text()

    # Extract YAML frontmatter
    if not content.startswith("---"):
        raise ValueError(f"Task file missing YAML frontmatter: {task_path}")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid task file format: {task_path}")

    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in task file: {e}")

    return metadata


def get_instructions(role: str, task_type: str) -> list:
    """Get conditional instructions based on role and task type."""
    instructions = []

    # Base instruction: always read role definition
    instructions.append(f"1. **Read your role definition:** `role-{role.lower()}.md`")
    instructions.append("   - You MUST understand your responsibilities")
    instructions.append("   - You MUST follow the algorithm specified in your role")

    # Architect role specific instructions
    if role == "Architect":
        if task_type == "design":
            instructions.append("")
            instructions.append("2. **Design Mode Instructions:**")
            instructions.append("   - Create or update types.py with type definitions")
            instructions.append("   - Define test contracts")
            instructions.append("   - Break large scope into components with dependencies")
            instructions.append("   - Populate the bounded **Work Items** block in the task file (between `<!-- start workitems -->` and `<!-- end workitems -->`)")
            instructions.append("   - Log work using log-task.py and transition state to `review`")
        elif task_type == "review":
            instructions.append("")
            instructions.append("2. **Review Mode Instructions:**")
            instructions.append("   - Read `review.md` for detailed review process")
            instructions.append("   - Load original specification from refers field")
            instructions.append("   - Review code changes for issues and anti-patterns")
            instructions.append("   - Check if changes modify core types/protocols")
            instructions.append("   - Decide: PASS or ESCALATE with work items")
        elif task_type == "exploration":
            instructions.append("")
            instructions.append("2. **Exploration Mode Instructions:**")
            instructions.append("   - Explore codebase to understand structure")
            instructions.append("   - Gather information for planning")
            instructions.append("   - Record findings as structured Work Items in the bounded Work Items block")
            instructions.append("   - Log work using log-task.py and transition state to `review`")
        elif task_type == "redesign":
            instructions.append("")
            instructions.append("2. **Redesign Mode Instructions:**")
            instructions.append("   - Review escalated task and issues")
            instructions.append("   - Redesign with fixes")
            instructions.append("   - Update types.py and contracts")

    # Implementor role specific instructions
    elif role == "Implementor":
        if task_type == "implement":
            instructions.append("")
            instructions.append("2. **Implementation Mode Instructions:**")
            instructions.append("   - Read specification carefully")
            instructions.append("   - Check if task can be subdivided (escalate if yes)")
            instructions.append("   - Check prerequisites (escalate if missing)")
            instructions.append("   - Implement matching spec exactly")
            instructions.append("   - Log work using log-task.py with facts/analysis/conclusion")

    # Manager role specific instructions
    elif role == "Manager":
        instructions.append("")
        instructions.append("2. **Manager Mode Instructions:**")
        instructions.append("   - NEVER do real work (no code, no exploration)")
        instructions.append("   - Create tasks using create-task.py script")
        instructions.append("   - Update kanban state only")
        instructions.append("   - Parse work items from completed tasks")
        instructions.append("   - Handle escalations by creating prerequisite tasks")

    return instructions


def render_briefing(metadata: dict, task_path: str) -> str:
    """Render agent briefing from task metadata."""
    assignee = metadata.get("assignee", "Unknown")
    expertise = metadata.get("expertise", [])
    skills = metadata.get("skills", [])
    task_type = metadata.get("type", "unknown")
    priority = metadata.get("priority", "medium")
    dependencies = metadata.get("dependencies", [])
    refers = metadata.get("refers", [])

    lines = [
        f"# Agent Briefing: {assignee}",
        "",
        f"**Task Type:** {task_type}",
        f"**Priority:** {priority}",
        "",
        "## Required Actions",
        "",
    ]

    # Add conditional instructions based on role and type
    lines.extend(get_instructions(assignee, task_type))

    # Add skills section
    lines.append("")
    lines.append("3. **Load required skills:**")
    if skills:
        for skill in skills:
            lines.append(f"   - `{skill}` (read SKILL.md)")
    else:
        lines.append("   - None specified")

    lines.extend([
        "",
        "## Task Context",
        "",
        f"**Expertise Required:** {', '.join(expertise) if expertise else 'None specified'}",
        f"**Task File:** {task_path}",
    ])

    if dependencies:
        lines.append(f"**Dependencies:** {', '.join(dependencies)}")

    if refers:
        lines.append(f"**References:** {', '.join(refers)}")

    lines.extend([
        "",
        "## Critical Reminders",
        "",
        "**You MUST:**",
        "- Read ALL required documentation before starting",
        "- Follow your role's algorithm strictly",
        "- Load and consult all required skills",
        "- Write a work log using `log-task.py` before completing",
        "",
        "**Do NOT:**",
        "- Skip reading required documentation",
        "- Deviate from your role's algorithm without escalation",
        "- Spawn subagents or create new tasks",
        "",
        "## Your Expertise",
        "",
    ])

    if expertise:
        lines.append("Apply your expertise in these domains:")
        for exp in expertise:
            lines.append(f"- {exp}")
    else:
        lines.append("No specific expertise domains specified.")

    # Determine what to read first
    first_doc = f"role-{assignee.lower()}.md"
    if assignee == "Architect" and task_type == "review":
        first_doc = "role-architect.md AND review.md"

    lines.extend([
        "",
        "---",
        "",
        f"**Begin by reading:** `{first_doc}`",
    ])

    return "\n".join(lines)


def main():
    args = parse_args()

    try:
        metadata = read_task_metadata(args.task)
        briefing = render_briefing(metadata, args.task)
        print(briefing)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
