---
name: journal
description: Development journal conventions. Append-only entries for tracking changes, decisions, and follow-ups.
---

# Journal

Development journals in `journal/`. Format: `YYYY-MM-DD-topic.md`.

## Purpose

- Record what changed, what broke, what we did, what we learned
- Make it easy to pick up work later or hand off

## Rules

- **Append-only**: Same topic → append to existing file. Different topic → new file.
- **Same day, same topic**: Append
- **Same day, new topic**: New file

## What to Write

Keep entries brief and structured:
- What changed and why
- Issues found + fix status
- Decisions made (especially protocol/schema choices)
- Follow-ups / TODOs

## How to Read (Warm Up)

- Check last 2-3 files for current focus, unresolved issues, key decisions
- Skim for relevance — don't read everything
