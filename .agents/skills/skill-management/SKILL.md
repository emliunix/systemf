---
name: skill-management
description: Manage and navigate the skill ecosystem across all locations
---

# Skill Management

Skills are the primary assets for consistent, high-quality work. This skill provides the framework for discovering, checking, and maintaining skills.

## Skill Locations

Skills are scattered across multiple locations:

| Location | Type | Purpose |
|----------|------|---------|
| `/home/liu/.claude/skills/` | System | Global, reusable across projects (python-uv, skill-creator, etc.) |
| `.agent/skills/` | Project | Project-specific conventions (docs, testing, deployment, etc.) |

**System skills** (global):
- `python-uv` - Python script execution with dependency management
- `python-project` - Python project management
- `skill-creator` - Creating new skills
- `skill-install` - Installing skills from .skill files

**Project skills** (this repo):
- `docs` - MkDocs, writing guidelines, mermaid validation
- `testing` - Test running, validation procedures
- `deployment` - Production deployment scripts
- `bus-cli` - Bus and CLI operations
- `scripts-docs` - Script documentation standards

## Skill-First Workflow

**Rule**: Before any work, check if a relevant skill exists and read it.

### Relevance Criteria

| Criterion | Examples |
|-----------|----------|
| **Domain** | docs, testing, deployment, bus |
| **Technology** | mkdocs, pytest, systemd, websockets |
| **File type** | .md → docs skill, .py tests → testing skill |
| **Operation** | serving docs → docs skill, deploying → deployment skill |

### Workflow

1. **Identify task domain/tech/operation**
2. **Check skill manifest** (this document or `ls -la .agent/skills/`)
3. **Read relevant skill(s)** - Multiple skills may apply
4. **Proceed with work** following skill conventions
5. **Update skill if needed** - Skills are living documents

### Examples

| Task | Skills to Check |
|------|----------------|
| Writing documentation | `.agent/skills/docs/SKILL.md` |
| Running tests | `.agent/skills/testing/SKILL.md` |
| Deploying to production | `.agent/skills/deployment/SKILL.md` |
| Using bus CLI | `.agent/skills/bus-cli/SKILL.md` |
| Creating new skill | `/home/liu/.claude/skills/skill-creator/SKILL.md` |
| Running Python script | `/home/liu/.claude/skills/python-uv/SKILL.md` |

## Skill Maintenance

Skills are **living documents**. Update them when:

1. **New conventions discovered** - Add to relevant skill
2. **Errors encountered** - Document pitfalls and solutions
3. **Process changes** - Keep procedures current
4. **Cross-cutting concerns** - Link related skills

### Maintenance Checklist

- [ ] Skill is discoverable (named clearly, in right location)
- [ ] Skill is up-to-date with current practices
- [ ] Skill links to related skills
- [ ] Skill has clear examples
- [ ] Skill is referenced from AGENTS.md or other entry points

## Commands

```bash
# List project skills
ls -la .agent/skills/

# List system skills  
ls -la /home/liu/.claude/skills/

# Read a skill
cat .agent/skills/docs/SKILL.md
```

## Quick Reference

**Always check these skills for common tasks:**

| Task | Skill Path |
|------|------------|
| Documentation | `.agent/skills/docs/SKILL.md` |
| Testing | `.agent/skills/testing/SKILL.md` |
| Deployment | `.agent/skills/deployment/SKILL.md` |
| Bus/CLI | `.agent/skills/bus-cli/SKILL.md` |
| Python scripts | `/home/liu/.claude/skills/python-uv/SKILL.md` |
| Create skill | `/home/liu/.claude/skills/skill-creator/SKILL.md` |
