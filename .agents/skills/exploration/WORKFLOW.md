# Exploration Workflow

## Todo List

- [ ] Explore: [topic] — gather facts and draft claims
- [ ] Validate: verify claims (subagent reads REFERENCE.md first)
- [ ] If exploration file changed during validation: return to Explore step
- [ ] Merge: integrate into master (only for session files)

## Phase 1: Explore

**Master vs Session:**
- No master exists → write directly to master
- Master exists on related topic → write session file (`{TOPIC}_{DATE}_{ID}_TEMP.md`)

**Subagent:**
```
Working directory: [absolute path]
Read: [plan file] + [related explorations]
Write: [target file]
Scopes: [IN: what to cover, OUT: what to ignore]
Entry points: [file:line]
Deliverable: Notes, Facts, Claims per FORMAT.md
```

**Stop when:** central question answered, or 3+ dead-ends, or claims become speculative.

## Phase 2: Validate

**Subagent (reads REFERENCE.md before starting):**
```
Working directory: [absolute path]
Read: REFERENCE.md + [exploration file]
Task: Verify each claim
- Fact exists at cited location
- Claim follows from facts
- Consistent with other claims
Annotate: VALIDATED Yes/No/Partial, notes
```

**If file changed during review:** restart from Phase 1.

## Phase 3: Merge

**Only for session files.** Merge validated claims into master.

```
Source: [session file]
Target: [master file]
Rules: validated → add, failed → unconfirmed, deduplicate, mark deprecated
```

Post-merge: archive temp file.
