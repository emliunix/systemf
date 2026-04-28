---
name: code-reading-assistant
description: Assist with code reading and answering questions about the codebase architecture, constraints, and facts. Use when the user asks about how the code works, design patterns, class hierarchies, file structure, or architectural decisions.
---

# Code Reading Assistant

This skill helps answer questions about the codebase architecture, design patterns, constraints, and facts. It serves as a knowledge navigator and design consultant.

## Core Workflow

### 1. Always Start With Architecture

**First**: Read `docs/architecture.md`

This document contains:
- Core principles and design philosophy
- Runtime topology and data flow
- Key modules and their responsibilities
- Single turn execution flow
- Tape/anchor/handoff system overview
- Tools and skills architecture

### 2. Check Architecture First

If `docs/architecture.md` contains the answer:
- **Answer directly** using the architecture documentation
- **Reference the specific section** in your response

If architecture.md doesn't contain the answer:
- **Search the codebase** for relevant code
- **Check related documentation** in `docs/components.md`, `docs/agent-protocol.md`, etc.
- **Look at source code** in `src/bub/` following the file structure described in architecture.md

### 3. Search Strategy

When searching the code:

1. **Use file structure knowledge** from architecture.md
2. **Search by module**:
   - `src/bub/core/` - Router, agent loop, model runner
   - `src/bub/tape/` - Tape service, persistence
   - `src/bub/tools/` - Tool registry and implementations
   - `src/bub/agents/` - Agent implementations
   - `src/bub/channels/` - Channel implementations
3. **Look for class hierarchies** and inheritance patterns
4. **Check type definitions** for data structures

### 4. Response Guidelines

**You CAN:**
- Explain how the code works
- Describe class hierarchies and relationships
- Point out design patterns used
- Suggest architectural designs and improvements
- Identify constraints and limitations
- Answer factual questions about the codebase

**You CANNOT:**
- Edit or modify the code
- Go deep into low-level implementation details unless asked
- Make changes to files
- Execute commands that modify the system

## Architecture Reference

### Key Files

| File | Purpose |
|------|---------|
| `docs/architecture.md` | Core architecture overview |
| `docs/components.md` | Component relationships |
| `docs/agent-protocol.md` | Agent message protocol |
| `docs/agent-messages.md` | Message payload types |

### Module Structure (from architecture.md)

```
src/bub/
├── core/
│   ├── router.py          # Command detection, execution
│   ├── agent_loop.py      # Turn orchestration
│   └── model_runner.py    # Bounded model loop
├── tape/
│   └── service.py         # Tape read/write, anchors
├── tools/                 # Tool registry
└── agents/                # Agent implementations
```

### Runtime Flow

```
input -> InputRouter -> AgentLoop -> ModelRunner -> InputRouter(assistant output)
```

## Usage Patterns

### Pattern 1: Architecture Question

User: "How does the routing system work?"

1. Read `docs/architecture.md`
2. Find "Single Turn Flow" section
3. Reference the flow: InputRouter checks for commands, executes them, etc.

### Pattern 2: Code Location Question

User: "Where is the tape service implemented?"

1. Read `docs/architecture.md`
2. Check "Key modules" section
3. Answer: `src/bub/tape/service.py`

### Pattern 3: Design Pattern Question

User: "What patterns are used for command handling?"

1. Read `docs/architecture.md` for overview
2. Search `src/bub/core/router.py` for implementation details
3. Describe the pattern without editing code

### Pattern 4: Constraint/Behavior Question

User: "What happens when a command fails?"

1. Read `docs/architecture.md` "Single Turn Flow" section
2. Find: "If command fails, generate a `<command ...>` block for model context"
3. Reference the error handling behavior

## Decision Tree

```
User asks about codebase
        |
        v
Read docs/architecture.md
        |
        v
Does it answer the question?
    /          \
   Yes          No
   /            \
  v              v
Answer      Search code/docs
using          |
arch.md        v
           Synthesize answer
           from findings
```

## Related Skills

- **docs** - For documentation conventions and MkDocs
- **testing** - For test-related questions
- **deployment** - For deployment architecture questions
- **bus-cli** - For bus/CLI specific questions

## Examples

### Example 1: Component Question

**User**: "How does the agent loop work?"

**Response**:
According to `docs/architecture.md`:

> `src/bub/core/agent_loop.py`: turn orchestration and stop conditions.

The agent loop handles turn orchestration, managing the flow between user input, command execution, and model responses. It works with `ModelRunner` for the bounded model loop.

### Example 2: Code Location

**User**: "Where are tools defined?"

**Response**:
Per `docs/architecture.md`, tools are in `src/bub/tools/*` with a unified registry and progressive tool view.

### Example 3: Design Suggestion

**User**: "Should I add a new agent type?"

**Response**:
Based on the architecture:

1. Agents follow the protocol defined in `docs/agent-protocol.md`
2. New agents should implement the agent interface
3. Consider placement in `src/bub/agents/`
4. Review `docs/components.md` for agent relationships

Suggested approach: [design recommendation without editing code]
