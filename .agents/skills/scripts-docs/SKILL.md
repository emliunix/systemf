---
name: scripts-docs
description: Procedure for maintaining documentation of scripts/ folder with last-modified tracking
---

# Scripts Documentation Maintenance

## Principle

Scripts in `scripts/` are debug/integration tools that need documentation with **last modified dates** so we know when docs may be outdated.

## Where to Document

Primary documentation lives in `docs/testing.md` under the "Script Catalog" section.

## Documentation Format

Each script entry should follow this pattern:

```markdown
### script_name.py
**Purpose**: Brief description of what this script does.

**Last Modified**: YYYY-MM-DD

**Usage**:
```bash
python scripts/script_name.py [args]
```

**What it tests**: (Optional) Specific functionality being validated
```

## Checking if Documentation is Current

### Check Single Script
```bash
git log -1 --format="%ai %s" -- scripts/SCRIPT_NAME.py
```

### Check All Scripts at Once
```bash
git log --name-only --pretty=format: scripts/ | grep -E '\.py$|\.sh$' | sort | uniq
```

### View Recent Script Changes
```bash
git log --oneline --name-only scripts/ | head -50
```

Compare git dates with the `Last Modified` field in docs. If they differ, update the documentation.

## When to Update Documentation

Update `docs/testing.md` when:
1. A script's functionality changes significantly
2. A new script is added to `scripts/`
3. A script is removed from `scripts/`
4. You notice the `Last Modified` date is stale (via git log check)

## Example Entry (Reference)

```markdown
### probe_bus.py
**Purpose**: Remote probe to test bus connectivity and spawn functionality.

**Last Modified**: 2026-02-18

**Usage**:
```bash
python scripts/probe_bus.py
```

**What it tests**: Bus connectivity, spawn requests, message flow
```

## Quick Audit Procedure

To audit all script documentation:

1. List all tracked scripts:
   ```bash
   git log --name-only --pretty=format: scripts/ | grep -E '\.py$|\.sh$' | sort | uniq
   ```

2. For each script, check if docs need updating:
   ```bash
   # Get script last modified date
   git log -1 --format="%ai" -- scripts/SCRIPT_NAME.py
   
   # Compare with date in docs/testing.md
   # If different, update the documentation
   ```

3. Update any stale entries in `docs/testing.md`

## Anti-Patterns

- **Don't** create exhaustive catalogs in skill files - use `docs/testing.md` for that
- **Don't** document scripts that no longer exist
- **Don't** leave stale last-modified dates - they make the docs untrustworthy
- **Don't** document implementation details - focus on purpose and usage
