# People Skill Exploration

## Notes

### Note 1: Goal and Scope
Create a Bub skill for maintaining a personal contact list with learnings about each person. The skill lives in a `my_skills` subproject and uses `people.md` as the default tracking file. Need to understand Bub skill format, discovery mechanism, and registration.

### Note 2: Skill Discovery in Bub
Bub discovers skills from three sources in order: project-local (`$workspace/.agents/skills`), global (`~/.agents/skills`), and builtin (`bub/src/skills`). Skills are directories containing a `SKILL.md` file with YAML frontmatter.

### Note 3: Subproject Structure
User wants a `my_skills` subproject. For Bub to auto-discover skills, they must be in a recognized skill root. A subproject skill can be symlinked into the workspace `.agents/skills/` or the subproject can be configured as an additional skill root.

### Note 4: people.md as Data File
`people.md` is personal data (contact list + learnings) and must be gitignored. It is NOT part of the skill itself but is the default file the skill operates on.

## Facts

### Fact 1: Skill Discovery Code
`bub/src/bub/skills.py:16-19`
```python
PROJECT_SKILLS_DIR = ".agents/skills"
LEGACY_SKILLS_DIR = ".agent/skills"
SKILL_FILE_NAME = "SKILL.md"
SKILL_SOURCES = ("project", "global", "builtin")
```

### Fact 2: Skill Validation Rules
`bub/src/bub/skills.py:105-123`
```python
def _is_valid_frontmatter(*, skill_dir: Path, metadata: dict[str, object]) -> bool:
    name = metadata.get("name")
    description = metadata.get("description")
    return (
        _is_valid_name(name=name, skill_dir=skill_dir)
        and _is_valid_description(description)
        and _is_valid_metadata_field(metadata.get("metadata"))
    )

def _is_valid_name(*, name: object, skill_dir: Path) -> bool:
    if not isinstance(name, str):
        return False
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 64:
        return False
    if normalized_name != skill_dir.name:
        return False
    return SKILL_NAME_PATTERN.fullmatch(normalized_name) is not None
```

### Fact 3: Builtin Skill Example
`bub/src/skills/gh/SKILL.md:1-4`
```yaml
---
name: gh
description: GitHub CLI skill for interacting with GitHub via the gh command line tool. Use when Bub needs to (1) Create, view, or manage GitHub repositories, (2) Work with issues and pull requests, (3) Create and manage releases, (4) Run and monitor GitHub Actions workflows, (5) Create and manage gists, or (6) Perform any GitHub operations via command line.
---
```

### Fact 4: Skill Creator Template Requirements
`bub/src/skills/skill-creator/SKILL.md:56-72`
```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/          - Executable code (Python/Bash/etc.)
    ├── references/       - Documentation intended to be loaded into context as needed
    └── assets/           - Files used in output (templates, icons, fonts, etc.)
```

### Fact 5: Progressive Disclosure Design
`bub/src/skills/skill-creator/SKILL.md:124-130`
```
Skills use a three-level loading system to manage context efficiently:

1. **Metadata (name + description)** - Always in context (~100 words)
2. **SKILL.md body** - When skill triggers (<5k words)
3. **Bundled resources** - As needed by Bub (Unlimited because scripts can be executed without reading into context window)
```

### Fact 6: Skill Naming Rules
`bub/src/skills/skill-creator/SKILL.md:225-231`
```
- Use lowercase letters, digits, and hyphens only; normalize user-provided titles to hyphen-case (e.g., "Plan Mode" -> `plan-mode`).
- When generating names, generate a name under 64 characters (letters, digits, hyphens).
- Prefer short, verb-led phrases that describe the action.
- Namespace by tool when it improves clarity or triggering (e.g., `gh-address-comments`, `linear-address-issue`).
- Name the skill folder exactly after the skill name.
```

## Claims

### Claim 1: People Skill Must Follow Bub Skill Format
The people skill requires a `SKILL.md` with YAML frontmatter containing `name: people` and a `description` field under 1024 characters. The skill directory must be named exactly `people` (matching the `name` field). The description should specify when to use the skill (contact list maintenance, personal relationship tracking, etc.).

**References:** Fact 2, Fact 4, Fact 6

### Claim 2: Skill Should Be Discoverable by Bub
For Bub to auto-discover the people skill, it must reside in a recognized skill root. Options: (1) place directly in workspace `.agents/skills/people/`, (2) place in `my_skills/.agents/skills/people/` and symlink to workspace `.agents/skills/people`, or (3) place in `my_skills/.agents/skills/people/` and rely on manual invocation. The symlink approach preserves the subproject structure while enabling discovery.

**References:** Fact 1, Note 3

### Claim 3: people.md Should Be Gitignored and Referenced by the Skill
`people.md` is personal data and must not be committed. The skill should reference `people.md` as the default file for tracking contacts and learnings. A template or format reference should document the expected structure (e.g., markdown sections per person with name, contact info, tags, and learnings).

**References:** Note 4, Fact 5

### Claim 4: Skill Should Provide Structured Guidance for Contact Management
The SKILL.md body should provide concise guidance on: how to read/update `people.md`, suggested format for entries (name, how met, key facts, topics discussed, follow-up actions), and conventions for maintaining the file. Keep under 500 lines to minimize context bloat.

**References:** Fact 5, Note 1

### Claim 5: References Directory Should Document the people.md Format
Since the people.md format is detailed reference material, it belongs in a `references/people-format.md` file rather than in SKILL.md. This follows the progressive disclosure pattern and keeps SKILL.md lean. SKILL.md should reference this file when format details are needed.

**References:** Fact 4, Fact 5
