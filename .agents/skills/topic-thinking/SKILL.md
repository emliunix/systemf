---
name: topic-thinking
description: Manages thinking patterns and mental models when switching between different topics or modes. Use when (1) switching from analysis to design, (2) switching from exploration to validation, (3) switching from reading to writing, (4) any topic transition where thinking approach must change, (5) user signals "we're going to sketch/design/build" after analysis phase.
---

# Topic Thinking Mode Switching

When switching topics, thinking patterns must reset. This skill ensures appropriate mental models are activated for each mode.

## The Switch Signal

Users signal topic switches with phrases like:
- "And we're going to sketch..."
- "Now let's design..."
- "Moving to implementation..."
- "Time to build..."
- "Let's write our own..."

**Action on signal**: Acknowledge the switch and activate the appropriate thinking mode.

## Thinking Modes

### Analysis Mode
**Trigger**: Reading/exploring existing code, documentation, or systems.
**Mental Model**: Detective - gathering evidence, tracing paths, understanding causality.
**Key Questions**:
- What exists and how does it work?
- Where is the evidence?
- What are the relationships?

**Must Do**:
- Cite source locations for every claim
- Trace complete pointer chains
- Distinguish fact from inference
- Document contradictions

**Must Not Do**:
- Propose changes or improvements
- Judge quality or elegance
- Design alternatives

### Design Mode
**Trigger**: Creating new architecture, APIs, or systems after analysis.
**Mental Model**: Architect - making tradeoffs, establishing principles, defining boundaries.
**Key Questions**:
- What are we optimizing for?
- What constraints must we respect?
- What are the minimal necessary concepts?

**Must Do**:
- State design goals explicitly
- Identify simplifications from prior art
- Define clear boundaries and interfaces
- Consider tradeoffs

**Must Not Do**:
- Copy existing implementations blindly
- Assume constraints from analyzed systems apply
- Skip stating principles

### Validation Mode
**Trigger**: Verifying claims, checking evidence, or testing hypotheses.
**Mental Model**: Skeptic - questioning assumptions, seeking disproof, measuring confidence.
**Key Questions**:
- Is the evidence sufficient?
- What would falsify this claim?
- How confident should we be?

**Must Do**:
- Check source locations match claims
- Verify code snippets are accurate
- Assess inference chains
- Report confidence levels

**Must Not Do**:
- Accept claims without verification
- Skip checking cited locations
- Confuse correlation with causation

### Implementation Mode
**Trigger**: Writing concrete code, tests, or specifications.
**Mental Model**: Craftsman - precision, completeness, testability.
**Key Questions**:
- What are the concrete types?
- How do we handle edge cases?
- What's the test strategy?

**Must Do**:
- Write runnable code
- Handle error cases
- Include type signatures
- Define test cases

**Must Not Do**:
- Leave TODOs for "later"
- Skip error handling
- Write pseudocode when real code is needed

## Mode Switching Protocol

When user signals a topic switch:

1. **Echo** - Explicitly state you detected the switch signal
2. **Identify** - Name the new mode and mental model
3. **Confirm Context** - State what you're switching from/to
4. **Activate** - Declare the mode-specific behavior now active
5. **Begin** - Start working in the new mode

### The Echo Protocol (REQUIRED)

Every mode switch MUST be echoed explicitly. This makes the behavior change transparent.

**Template:**
```
"[Switch signal detected]. Activating [Mode] ([Mental Model]). 
Switching from [Old Mode] to [New Mode] - [Context/Goal]."
```

**Required Elements:**
- Quote or paraphrase the user's switch signal
- Name the mode being activated
- Name the mental model (Detective/Architect/Skeptic/Craftsman)
- State the transition (From X → To Y)
- Confirm the new goal/context

### Example Switches

**Analysis → Design**:
```
User: "And we're going to sketch our own module system design"

Response: "Switch signal detected: 'we're going to sketch our own 
module system design'. Activating Design Mode (Architect mental model). 
Switching from Analysis to Design - moving from understanding GHC's 
implementation to designing a simplified alternative focused on single 
unified environments and explicit loading."

Then proceed with design work...
```

**Design → Implementation**:
```
User: "Let's implement the NameEnv"

Response: "Switch signal detected: 'let's implement'. Activating 
Implementation Mode (Craftsman mental model). Switching from Design 
to Implementation - moving from architecture to concrete code with 
complete type signatures and error handling."

Then proceed with implementation...
```

**Exploration → Validation**:
```
User: "Validate those claims against the source"

Response: "Switch signal detected: 'validate those claims'. Activating 
Validation Mode (Skeptic mental model). Switching from Exploration to 
Validation - moving from discovery to verification, checking each claim 
against actual source code."

Then proceed with validation...
```

**Why Echo:**
- Makes mode switches explicit and visible
- Confirms you understood the transition
- Sets expectations for the new behavior
- Prevents silent/unacknowledged context switches

## Cross-Cutting Principles

These apply in ALL modes:

### Structured Codebase Analysis Framework

For deep analysis of complex codebases, apply the **Tiered Analysis Framework** (see `TIERED_ANALYSIS_FRAMEWORK.md`):

| Tier | Purpose | When to Use |
|------|---------|-------------|
| **Base Theme** | Define 3-5 analytical dimensions | Before analyzing code |
| **Main Theme** | Map component relationships | After establishing dimensions |
| **Detailed Facts** | Analyze functions through dimensions | Throughout exploration |

**Key insight:** Mode switching in this skill corresponds to moving between tiers:
- **Analysis Mode** ↔ Establishing base dimensions, detailed facts
- **Design Mode** ↔ Synthesizing main theme from validated facts
- **Validation Mode** ↔ Cross-tier consistency checking

### Evidence Standard
- Every claim must have supporting evidence
- Evidence quality must match claim confidence
- Source citations required for factual claims

### Clarity Over Cleverness
- Explicit is better than implicit
- Simple is better than complex
- Clear names over abbreviations

### Completeness
- Don't leave conceptual gaps
- Handle all error cases
- Document assumptions

## Mode-Specific Reminders

### When in Analysis Mode
- You're a detective, not a critic
- Evidence first, interpretation second
- Cite sources or it didn't happen

### When in Design Mode
- State principles before details
- Question every concept: "Is this necessary?"
- Compare against analyzed alternatives

### Architecture First Principle
**Correct Architecture Over Convenience**: When choosing between implementation approaches, prioritize structural correctness over implementation effort.

**Key Principles:**
- Good names reveal intention (`ValBind` vs anonymous tuple)
- Type definitions exist for semantic clarity
- Self-documenting structures reduce long-term maintenance burden
- Correct structure first, effort evaluation second

**Anti-Pattern: Effort-Based Decision Making**
Choosing the "easier" path (fewer files to touch, less code to write) results in technical debt that wastes more effort later. Effort-based shortcuts accumulate into unmaintainable systems.

**Correct Approach:**
- Honor existing type definitions and architectural decisions
- Use semantically meaningful structures even if they require more boilerplate
- Prefer named attributes over positional indices
- Accept that correct architecture may touch many files - this is a sign the structure matters, not a reason to avoid it

### When in Validation Mode
- Assume claims are wrong until proven
- Look for counter-examples
- Report confidence honestly

### When in Implementation Mode
- Write real, runnable code
- Types are documentation
- Tests prove correctness
