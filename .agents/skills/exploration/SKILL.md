---
name: exploration
description: Systematic codebase investigation producing structured exploration files (Notes → Facts → Claims). Use when researching unknown systems, tracing code paths, or documenting architecture.
---

# Exploration Skill

An exploration produces a structured document with three sections in dependency order:

1. **Notes** — context, planning, goals
2. **Facts** — atomic code snippets and traces (leaf nodes, no reasoning)
3. **Claims** — reasoning chains referencing facts and prior claims

## Workflow

1. **Create** an exploration file following `FORMAT.md`
2. **Validate** claims (subagent reads `REFERENCE.md` first)
3. **Merge** session files into master (if applicable)

Full process details: `WORKFLOW.md`

## Audience

| Role | Read |
|---|---|
| Creating explorations | `FORMAT.md` + `WORKFLOW.md` |
| Reviewing explorations | `REFERENCE.md` |

## Output Files

- **Master:** `analysis/{TOPIC}_EXPLORATION.md`
- **Session:** `analysis/{TOPIC}_{DATE}_{ID}_TEMP.md`
