# Multi-Agent Orchestration Patterns: Case-by-Case Analysis

**Date:** 2026-04-28
**Scope:** `docs/patterns.md`, `bub_sf/src/bub_sf/bub_ext.py`, `upstream/bub_backup/analysis/*`

---

## 1. Executive Summary

This report analyzes three artifacts to derive a unified design for multi-agent orchestration in the Bub framework:

1. **User patterns** (`docs/patterns.md`): Seven high-level workflow patterns for multi-agent collaboration, memory management, and safety.
2. **Concrete implementation** (`bub_ext.py`): A `PrimOps` synthesizer that demonstrates a working "child process" primitive — forking a REPL session, injecting arguments, evaluating expressions, and capturing results.
3. **Upstream architecture** (`upstream/bub_backup/analysis/*`): Ten deep-dive documents describing the hook-based plugin system, turn lifecycle, tape management, model execution, and tool orchestration.

**Key finding:** The upstream architecture already provides 80% of the primitives needed for all seven patterns. The remaining 20% requires: (a) a `Tape` snapshot/restore mechanism, (b) a structured subagent spawning protocol, and (c) a supervision/monitoring hook layer. `bub_ext.py` proves that child-for-and-evaluate already works at the type system level.

---

## 2. Artifact-by-Artifact Breakdown

### 2.1 `docs/patterns.md` — The Seven Patterns

| # | Pattern | Core Mechanism | State Model | Granularity |
|---|---------|---------------|-------------|-------------|
| 1 | **traces** | Parallel summarization tape | Sidecar tape per session | Per-turn |
| 2 | **recall** | Topic detection + history search | Indexed trace summaries | Per-turn |
| 3 | **ask_parent** | Nested chat-only subagent | Parent tape snapshot | Ad-hoc query |
| 4 | **ask_child** | Resumeable child pointer | Child tape reference | Task-scoped |
| 5 | **saved_child** | Named snapshots + parallel resume | Persistent snapshots | Multi-turn |
| 6 | **supervised** | Error-loop detection + injection | Supervisor events on tape | Continuous |
| 7 | **setup_constraints** | Tool/directory ACLs | Session-scoped rules | Per-session |

**Cross-cutting concerns:**
- **Fork semantics:** Patterns 3, 4, 5 all require `TAPE.fork()` with different merge policies.
- **State persistence:** Patterns 1, 2, 5 need durable storage outside the main tape.
- **Lifecycle management:** Patterns 4, 5 require child agents to outlive a single turn.
- **Security boundaries:** Pattern 7 must intercept tool calls at the runtime level.

### 2.2 `bub_ext.py` — The Working Prototype

This file implements a `Synthesizer` that exposes a single primitive op: `test_prim`. Despite its test-oriented name, it demonstrates a complete child-agent lifecycle:

```
get_primop("test_prim", thing, session)
├── SPLIT: TyFun → [arg_tys], res_ty
├── CREATE: VPartial(name, arity, _fun)
│   └── _fun(args):
│       ├── FORK: session.fork() → s2
│       ├── SETUP: s2.cmd_add_args([(name, val, ty), ...])
│       ├── CAPTURE: s2.cmd_add_return(res, res_ty)
│       ├── EVAL: s2.eval("arg0"), s2.eval("arg1"), ...
│       ├── EVAL: s2.eval("set_return 1")
│       └── RETURN: res[0]
└── RETURN: VPartial
```

**What it proves:**
1. **Session forking works.** `REPLSessionProto.fork()` creates an isolated child session.
2. **Argument injection works.** `cmd_add_args` binds values into the child namespace.
3. **Return capture works.** `cmd_add_return` sets up a mutable cell for results.
4. **Evaluation in child works.** `s2.eval()` runs code in the child context.
5. **Type-safe boundary.** Arguments and return values are typed via `split_fun()`.

**What it lacks (relative to the patterns):**
- No tape inheritance (child starts fresh, not with parent history).
- No persistent snapshot (child dies when `_fun` returns).
- No parallel execution (one child at a time, synchronously).
- No topic tracking or summarization.
- No supervision or error-loop detection.

### 2.3 Upstream Analysis — Architectural Primitives

The ten upstream documents describe a rich execution environment:

#### 2.3.1 Hook System (01_hook_architecture.md)
- **13 hooks** covering full turn lifecycle.
- `firstresult` vs collect-all semantics.
- Plugin precedence: last-registered wins.
- Fault isolation for observer hooks.

**Relevance:** Patterns 6 (supervised) and 7 (setup_constraints) can be implemented as plugins using `system_prompt`, `save_state`, and `on_error` hooks.

#### 2.3.2 Turn Lifecycle (02_turn_lifecycle.md)
```
resolve_session → load_state → build_prompt → run_model → save_state → render_outbound → dispatch_outbound
```

**Relevance:** Patterns 1 (traces) and 2 (recall) fit naturally into `save_state` (post-turn summarization) and `system_prompt` / `build_prompt` (pre-turn context injection).

#### 2.3.3 Model Execution (07_model_execution.md)
- `Agent.run()` / `Agent.run_stream()` delegate to `republic` library.
- Tape management via `TapeService` with `fork_tape()` and `handoff()`.
- Auto-handoff on context-length errors.
- Tool auto-execution loop.

**Relevance:** The `Tape` abstraction already supports fork isolation. What's missing is **snapshot/restore** and **named session persistence**.

#### 2.3.4 Tools System (10_tools_system.md — inferred from references)
- Tool registry with `REGISTRY`.
- Tool descriptions rendered into system prompt.
- Tool execution via `tape.run_tools_async()`.

**Relevance:** Patterns 3 (ask_parent) and 4 (ask_child) should be exposed as first-class tools, not ad-hoc synthesizer hacks.

---

## 3. Case-by-Case Design Analysis

### Pattern 1: Traces

**Goal:** Maintain a parallel topic-tracking tape that summarizes each turn.

**Upstream primitives available:**
- `save_state` hook: Called in `finally` block after every turn.
- `Tape` / `TapeService`: Can create secondary tapes.
- `system_prompt` hook: Can inject trace context into next turn.

**Design:**
```python
class TracesPlugin:
    @hookimpl
    async def save_state(self, session_id, state, message, model_output):
        # Post-turn: spawn summarization subagent
        summary = await summarize_turn(message, model_output)
        tape_service = state["_runtime_agent"].tapes
        trace_tape = tape_service.session_tape(f"{session_id}__trace")
        trace_tape.append_event("trace.turn", {
            "summary": summary,
            "topics": extract_topics(summary),
            "timestamp": now()
        })
        return {"_trace_tape_id": trace_tape.name}

    @hookimpl
    def system_prompt(self, prompt, state):
        trace_tape_id = state.get("_trace_tape_id")
        if not trace_tape_id:
            return None
        # Injected by build_prompt or system_prompt hook
        return f"<trace_summary>{get_latest_summary(trace_tape_id)}</trace_summary>"
```

**Gap:** No `tape.append_event()` API in current `TapeService`. Need custom event types.

### Pattern 2: Recall

**Goal:** Detect topic switches and pull relevant historical context.

**Upstream primitives available:**
- `build_prompt` hook: Firstresult, can modify prompt before model sees it.
- `Tape` search: Full-text search across history (mentioned in upstream docs).

**Design:**
```python
class RecallPlugin:
    @hookimpl
    async def build_prompt(self, message, session_id, state):
        current_topics = extract_topics(message.content)
        last_topics = state.get("_last_topics", [])
        
        if is_topic_switch(current_topics, last_topics):
            trace_tape = get_trace_tape(session_id)
            relevant = await trace_tape.search(
                kinds=["trace.turn"],
                query=" OR ".join(current_topics)
            )
            context = format_recall_block(relevant)
            return prepend_context(message, context)
        
        state["_last_topics"] = current_topics
        return None  # Let next plugin handle
```

**Gap:** `Tape.search()` API is not confirmed in current codebase. Need to verify.

### Pattern 3: Ask_Parent

**Goal:** Child subagent can query parent when stuck.

**Current implementation:** `bub_ext.py` does the inverse — parent creates child. No child→parent channel exists.

**Design:**
```python
# Tool exposed to child agents
@tool
def ask_parent(question: str) -> str:
    """Ask the parent agent for clarification or guidance.
    
    This creates a restricted chat-only subagent that sees the parent's
    tape snapshot but cannot make tool calls.
    """
    parent_tape = get_current_parent_tape()
    response = run_subagent(
        session=f"temp/ask-parent-{uuid()}",
        prompt=f"Your child agent asks: {question}",
        allowed_tools=set(),  # Chat only!
        state={"inherited_tape": parent_tape.snapshot()}
    )
    return response.text
```

**Key constraints from upstream docs:**
- `allowed_tools=set()` enforces chat-only (no tool calls).
- Parent tape snapshot provides context without merge-back.
- Session naming `temp/...` ensures no persistence.

**Gap:** No `get_current_parent_tape()` or `run_subagent()` primitives in current API.

### Pattern 4: Ask_Child

**Goal:** Parent delegates to child, child returns result + tape pointer. Parent can follow up.

**Current implementation:** `bub_ext.py` is closest — it creates a child session, runs evaluations, and returns a value. But the child dies immediately.

**Design:**
```python
# Tool exposed to parent agents
@tool
def delegate_to_child(task: str, model: str | None = None) -> dict:
    """Delegate a task to a child agent.
    
    Returns the child's result and a tape pointer for follow-up questions.
    """
    child_session = f"child/{slugify(task)}-{uuid()[:8]}"
    result = run_subagent(
        session=child_session,
        prompt=task,
        allowed_tools={"fs.read", "fs.write", "web.fetch"},
        model=model,
        state={"inherited_tape": get_current_tape().snapshot()}
    )
    return {
        "result": result.text,
        "child_tape": child_session,
        "child_session": child_session,
    }

@tool  
def ask_child(child_tape: str, question: str) -> str:
    """Ask a follow-up question to a previously created child agent."""
    return run_subagent(
        session=f"child-resumed/{uuid()[:8]}",
        prompt=f"Previous research in tape {child_tape}.\nNew question: {question}",
        state={"inherited_tape": child_tape}
    ).text
```

**Gap:** Need persistent session storage for child agents across turns. Current `bub_ext.py` child dies after `_fun` returns.

### Pattern 5: Saved_Child

**Goal:** Save child state as named snapshot. Resume later, potentially in parallel.

**Design:**
```python
@tool
def child_snapshot(name: str) -> dict:
    """Save the current child agent's tape as a named snapshot."""
    tape = get_current_tape()
    snapshot = {
        "name": name,
        "tape": tape.name,
        "entries": tape.info().entry_count,
        "timestamp": now(),
        "context": tape.get_recent_entries(n=5)
    }
    persist_snapshot(name, snapshot)
    return snapshot

@tool
def child_resume(name: str, new_task: str) -> str:
    """Resume a previously saved child agent with a new task."""
    snapshot = load_snapshot(name)
    return run_subagent(
        session=f"resumed/{name}-{uuid()[:8]}",
        prompt=f"Continue from snapshot {name}. New task: {new_task}",
        state={"inherited_snapshot": snapshot}
    ).text

@tool
def child_parallel(tasks: list[str], snapshot_name: str | None = None) -> list[str]:
    """Run multiple tasks in parallel, optionally from a shared snapshot."""
    state = {"inherited_snapshot": load_snapshot(snapshot_name)} if snapshot_name else {}
    
    async def run_one(i: int, task: str) -> str:
        return await run_subagent_async(
            session=f"parallel/{i}-{uuid()[:8]}",
            prompt=task,
            state=state
        )
    
    return await asyncio.gather(*[run_one(i, t) for i, t in enumerate(tasks)])
```

**Gap:** No snapshot persistence layer. Need file-based or database snapshot store.

### Pattern 6: Supervised

**Goal:** Sidecar agent monitors main agent, detects loops/distractions, injects phase changes.

**Design:**
```python
class SupervisorPlugin:
    @hookimpl
    async def save_state(self, session_id, state, message, model_output):
        # Skip if this is the supervisor's own turn
        if state.get("_is_supervisor_turn"):
            return None
            
        tape = get_tape(session_id)
        recent = tape.get_recent_entries(n=5)
        
        # Detect error loops
        errors = [e for e in recent if e.kind == "tool_result" and e.status == "error"]
        if len(errors) >= 3:
            intervention = await evaluate_intervention(tape, errors)
            tape.append_event("supervisor.intervention", intervention)
            
        # Detect topic drift
        topics = extract_topics_from_recent(recent)
        if is_distracted(topics, state.get("_current_task_topic")):
            tape.append_event("supervisor.intervention", {
                "issue": "topic_drift",
                "suggestion": "return_to_task"
            })
    
    @hookimpl
    def system_prompt(self, prompt, state):
        tape = get_tape(state["session_id"])
        interventions = tape.search_events(kind="supervisor.intervention")
        if interventions:
            return format_supervisor_notes(interventions[-3:])
        return None
```

**Gap:** No `tape.get_recent_entries()` or `tape.search_events()` API. Need event querying.

### Pattern 7: Setup_Constraints

**Goal:** Restrict tools/directories with enforced permissions and explanations.

**Design:**
```python
class ConstraintsPlugin:
    @hookimpl
    async def load_state(self, message, session_id):
        # Load or initialize constraints for this session
        return {
            "_constraints": load_constraints(session_id) or default_constraints()
        }
    
    @hookimpl
    def system_prompt(self, prompt, state):
        constraints = state.get("_constraints")
        if constraints:
            return render_constraints_prompt(constraints)
        return None

# Tool wrappers enforce constraints
def constrained_fs_read(path: str, state: dict) -> str:
    constraints = state.get("_constraints", {})
    if is_blocked(path, constraints.get("blocked_dirs", [])):
        return f"[BLOCKED: Access to {path} restricted. Reason: {constraints.get('reason')}]")
    return fs_read(path)
```

**Gap:** Tool wrapping requires intercepting tool calls at the `Tape` level. `republic` may support this; need to verify.

---

## 4. Unified Architecture Proposal

### 4.1 Core Abstractions

Based on the analysis, all seven patterns can be built on four core abstractions:

```
┌─────────────────────────────────────────────────────────────┐
│                    Multi-Agent Kernel                        │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Session    │  │    Tape      │  │   SnapshotStore  │  │
│  │  (identity)  │  │  (history)   │  │  (persistence)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Agent      │  │   EventBus   │  │  ConstraintEngine│  │
│  │  (execution) │  │  (pub/sub)   │  │  (enforcement)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 The `Subagent` Protocol

All parent-child patterns (3, 4, 5) need a unified spawning primitive:

```python
class Subagent(Protocol):
    async def spawn(
        self,
        session: str,
        prompt: str,
        allowed_tools: set[str] | None = None,
        model: str | None = None,
        state: dict | None = None,
        merge_back: bool = False,
    ) -> SubagentResult:
        ...
    
    async def resume(
        self,
        session: str,
        prompt: str,
        inherited_tape: str | None = None,
        inherited_snapshot: str | None = None,
    ) -> SubagentResult:
        ...

@dataclass
class SubagentResult:
    text: str
    tape_id: str
    session_id: str
    tool_calls: list[ToolCall]
    events: list[TapeEvent]
```

**Implementation strategy:**
1. **Phase 1:** Extend `bub_ext.py` `PrimOps` to support persistent sessions (not just ephemeral `_fun` closures).
2. **Phase 2:** Add `Subagent` as a first-class tool in the Bub tool registry.
3. **Phase 3:** Implement `SnapshotStore` as a SQLite or JSONL backend.

### 4.3 The `Trace` System

Patterns 1 and 2 need a dedicated sidecar context:

```python
class TraceSystem:
    def __init__(self, tape_service: TapeService):
        self._tapes = tape_service
    
    async def summarize_turn(
        self,
        session_id: str,
        message: Envelope,
        model_output: str,
    ) -> TraceEntry:
        trace_tape = self._tapes.session_tape(f"{session_id}__trace")
        summary = await self._summarize(message, model_output)
        entry = TraceEntry(
            timestamp=now(),
            summary=summary,
            topics=extract_topics(summary),
            keywords=extract_keywords(summary),
        )
        trace_tape.append_custom(entry)
        return entry
    
    async def recall(
        self,
        session_id: str,
        current_topics: list[str],
        max_entries: int = 5,
    ) -> list[TraceEntry]:
        trace_tape = self._tapes.session_tape(f"{session_id}__trace")
        return await trace_tape.search_topics(current_topics, limit=max_entries)
```

**Implementation strategy:**
- Use `save_state` hook to trigger `summarize_turn`.
- Use `build_prompt` hook to inject `recall` results.
- Store traces in a secondary tape with custom event schema.

### 4.4 The `Supervisor` System

Pattern 6 needs continuous monitoring:

```python
class Supervisor:
    def __init__(self, rules: list[SupervisorRule]):
        self.rules = rules
    
    async def check(self, tape: Tape, state: dict) -> list[Intervention]:
        interventions = []
        for rule in self.rules:
            if await rule.check(tape, state):
                interventions.append(await rule.intervene(tape, state))
        return interventions

class ErrorLoopRule(SupervisorRule):
    async def check(self, tape: Tape, state: dict) -> bool:
        recent = tape.get_recent_entries(n=5)
        errors = [e for e in recent if is_error(e)]
        return len(errors) >= 3
    
    async def intervene(self, tape: Tape, state: dict) -> Intervention:
        return Intervention(
            kind="error_loop",
            message="3 consecutive errors detected. Consider a different approach.",
            action=ActionType.FORCE_HANDOFF,
        )
```

**Implementation strategy:**
- `save_state` hook runs supervisor check post-turn.
- `system_prompt` hook injects active interventions.
- `handoff()` is used for forced phase changes.

### 4.5 The `ConstraintEngine`

Pattern 7 needs runtime enforcement:

```python
@dataclass
class Constraints:
    allowed_dirs: list[Path]
    blocked_dirs: list[Path]
    allowed_tools: set[str]
    blocked_tools: set[str]
    max_file_size_mb: int
    reason: str

class ConstraintEngine:
    def __init__(self, constraints: Constraints):
        self.constraints = constraints
    
    def check_tool_call(self, name: str, args: dict) -> tuple[bool, str]:
        if name in self.constraints.blocked_tools:
            return False, f"Tool '{name}' is blocked. Reason: {self.constraints.reason}"
        if name not in self.constraints.allowed_tools:
            return False, f"Tool '{name}' not in allowed list."
        return True, ""
    
    def check_path(self, path: Path) -> tuple[bool, str]:
        for blocked in self.constraints.blocked_dirs:
            if path.is_relative_to(blocked):
                return False, f"Access to {path} blocked. Reason: {self.constraints.reason}"
        if self.constraints.allowed_dirs:
            if not any(path.is_relative_to(a) for a in self.constraints.allowed_dirs):
                return False, f"Access outside allowed directories."
        return True, ""
```

**Implementation strategy:**
- Wrap tool execution in `ConstraintEngine.check_tool_call()`.
- Store constraints in session state via `load_state` hook.
- Inject constraint explanation via `system_prompt` hook.

---

## 5. Implementation Roadmap

### Phase 1: Foundation (Weeks 1–2)
- [ ] Verify `Tape` APIs: `fork()`, `handoff()`, `search()`, custom events.
- [ ] Implement `SnapshotStore` (JSONL files in `~/.bub/snapshots/`).
- [ ] Add `Subagent.spawn()` and `Subagent.resume()` to `bub_ext.py`.

### Phase 2: Parent-Child Patterns (Weeks 3–4)
- [ ] Implement `ask_parent` tool (chat-only subagent).
- [ ] Implement `delegate_to_child` and `ask_child` tools.
- [ ] Implement `child_snapshot` and `child_resume` tools.
- [ ] Add parallel execution support (`asyncio.gather`).

### Phase 3: Memory Patterns (Weeks 5–6)
- [ ] Implement `TraceSystem` as a plugin.
- [ ] Add `summarize_turn` to `save_state` hook.
- [ ] Add `recall` to `build_prompt` hook.
- [ ] Implement topic extraction and switch detection.

### Phase 4: Supervision & Safety (Weeks 7–8)
- [ ] Implement `Supervisor` with `ErrorLoopRule` and `TopicDriftRule`.
- [ ] Implement `ConstraintEngine` with tool/path interception.
- [ ] Add `setup_constraints` tool for dynamic rule changes.

---

## 6. Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| `republic` Tape API doesn't support custom events | High | Fork `republic` or use tape naming convention (`session__trace`) |
| Snapshot persistence creates disk bloat | Medium | TTL-based cleanup, max snapshots per session |
| Parallel subagents overload LLM rate limits | High | Semaphore-based concurrency limit in `child_parallel` |
| Supervisor false positives annoy users | Medium | Configurable sensitivity thresholds, opt-out flag |
| Constraints break legitimate tool calls | Medium | Always include override mechanism (`setup_constraints` tool) |

---

## 7. Conclusion

The user's seven patterns are architecturally sound and largely implementable within the existing Bub framework. `bub_ext.py` already proves the hardest part — child session forking with type-safe value marshaling. The remaining work is:

1. **Persistence layer** for snapshots and traces.
2. **Tool registry additions** for subagent orchestration.
3. **Hook plugins** for supervision and constraints.

The upstream analysis documents provide a robust foundation: the hook system allows clean separation of concerns, the tape system provides conversation state management, and the tool system provides the execution sandbox. All three pattern categories (memory, parent-child, supervision) map cleanly to existing architectural primitives.

**Next step:** Implement Phase 1 (SnapshotStore + Subagent protocol) to validate the design with working code.

---

## Appendix A: Pattern-to-Primitive Mapping

| Pattern | Primary Hooks | Primary Tape Operations | New Abstractions Needed |
|---------|--------------|------------------------|------------------------|
| traces | `save_state`, `system_prompt` | `fork()`, custom events | `TraceSystem` |
| recall | `build_prompt` | `search()` | `TopicExtractor` |
| ask_parent | (tool) | `fork()`, snapshot | `Subagent.spawn()` |
| ask_child | (tool) | `fork()`, snapshot | `Subagent.spawn()`, `Subagent.resume()` |
| saved_child | (tool) | `fork()`, snapshot | `SnapshotStore`, `Subagent.parallel()` |
| supervised | `save_state`, `system_prompt` | `get_recent_entries()` | `Supervisor`, `Intervention` |
| setup_constraints | `load_state`, `system_prompt` | — | `ConstraintEngine` |

## Appendix B: File References

| File | Role |
|------|------|
| `docs/patterns.md` | User's raw pattern definitions |
| `bub_sf/src/bub_sf/bub_ext.py` | Working child-session prototype |
| `upstream/bub_backup/analysis/01_hook_architecture.md` | Hook system deep dive |
| `upstream/bub_backup/analysis/02_turn_lifecycle.md` | Turn lifecycle walkthrough |
| `upstream/bub_backup/analysis/07_model_execution.md` | Model execution and streaming |
| `upstream/bub_backup/analysis/user_design_patterns.md` | Expanded pattern flows |
| `src/bub/system_agent.py` | Current system agent (spawn via bus) |
