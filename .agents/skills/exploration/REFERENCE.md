# Exploration Reference

Pass this file to validation/review subagents alongside the exploration file.

## Evidence Hierarchy

1. **Source code** — Primary, most authoritative
2. **Validated exploration notes** — Secondary (claims marked "Validated" in master files)
3. **Draft exploration notes** — Reference only, not authoritative

When citing validated notes, include both the exploration source and the confirming source code:
```
Source: `analysis/TOPIC_EXPLORATION.md:Claim N` + `path/file:lines`
```

## Claim Quality Standards

Good claims are:
- **Atomic** — One specific fact, not compound
- **Verifiable** — Confirmable by reading source code
- **Attributed** — Linked to specific `file:lines`
- **Dated** — Discovery/update date recorded

## Handling Contradictions

When evidence contradicts an existing claim:
1. Document both the old claim and the new contradictory evidence
2. Flag: add `CONTRADICTS: [old claim source]` to the new finding
3. Stop — do not resolve at subagent level
4. Escalate — parent agent decides whether to keep both, replace, investigate further, or mark uncertain

## Single Channel Principle

Subagent prompts are the **only** communication channel. Once spawned, a subagent cannot ask questions.

Every subagent prompt must include:
- Absolute file paths
- Working directory
- Read vs write file operations
- Entry points and search patterns
- Scope boundaries (IN/OUT)
- Expected deliverable format

Insufficient context leads to wasted time, wrong assumptions, and incomplete findings.

## Common Pitfalls

- **Following too many branches** — Stay within scope boundaries
- **Interface vs implementation** — Distinguish public API from internals
- **Similar names** — Don't assume `Foo` in file A is same as `Foo` in file B
- **Cherry-picking evidence** — Report contradictions, don't hide them
- **Over-confidence** — Mark speculative claims as Low confidence

## Maintenance Rules

1. **Atomic commits** — Each session appends new claims
2. **No deletion** — Mark deprecated, don't remove
3. **Date everything** — Every claim gets discovered/updated date
4. **Link liberally** — Cross-reference related topics
5. **Validate periodically** — Run validation when status changes to Validated
