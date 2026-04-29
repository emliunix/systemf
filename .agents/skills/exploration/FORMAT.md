# Exploration Format

Document structure (dependency order):

1. **Notes** — context, planning, goals. No dependencies. Come first.
2. **Facts** — atomic code snippets, traces, logs. No dependencies. Come after notes.
3. **Claims** — reasoning chains. Depend on facts and prior claims. Come last.

## Rules

- **Facts are leaf.** Every fact must be a raw, verifiable artifact (code, trace, log). No reasoning in facts. Lightweight comments (one sentence of context/focus) are allowed above the artifact.
- **Claims synthesize.** Each claim reasons from multiple facts. A claim may reference any prior facts, notes, or claims.
- **No 1:1 pairing.** Multiple facts may support one claim. Multiple claims may reference the same fact.
- **Dependency order.** Sections are ordered by what they depend on: notes (nothing) → facts (nothing) → claims (facts + notes + prior claims).
- **Cross-references.** Claims must list their references explicitly: "References: Fact 3, Claim 1."
- **External references.** Claims may reference items from other exploration files using the format: `./rel/path/to/file#claimN` or `./rel/path/to/file#factN`. Example: "References: Fact 2, Claim 1, `./analysis/TAPE_EXPLORATION.md#claim3`."

## Section Templates

### Notes
Notes are the most flexible section. They provide context, planning, and guidance without being verifiable facts. Common types:

- **Planning** — what to investigate, scope boundaries, entry points
- **Context** — background on how the system works, prior knowledge
- **Goals** — what questions this exploration aims to answer
- **Approach** — how to investigate, what code paths to trace
- **Observations** — preliminary findings that aren't yet atomic facts
- **Assumptions** — working assumptions to validate or refute
- **Dependencies** — what other explorations or systems this relates to
- **Questions** — open questions that guide the investigation
- **Summarization** — high-level synthesis after claims are validated, bridging back to the central question

```
### Note N: [Topic]
[Context, planning, or guidance. Pure narrative, no evidence required.]
```

### Facts
```
### Fact N: [Title]
`path/to/file:line`
[Raw code or trace. No interpretation.]
```

### Claims
```
### Claim N: [Title]
**Reasoning:** [Chain of reasoning referencing facts and prior claims by number.]
**References:** Fact X, Fact Y, Claim Z, Note W
```
