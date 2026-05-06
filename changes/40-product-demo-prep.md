# Product Demo Preparation

## Pitch

> "Every agent framework has compaction and subagents. But they're black boxes. In SystemF, they're just functions — typed, composable, and extensible."

## Demo Story: The Transparent Agent

### Scene 1 — The Problem (1 min)

Show a long-running agent conversation. Context is full. The agent is repeating itself.

**Current tools handle this opaquely:**
- Claude Code: `/compact` — magic happens, you don't see the logic
- Subagent tools: spawn children, but you can't inspect the context passing

### Scene 2 — Compaction as Code (3 min)

Show the compaction pattern in SystemF:

```systemf
-- | Compact a tape by forking, summarizing, and replacing history
compact :: Tape -> String -> IO ()
compact tape reason = do
  let branch = fork_tape tape Nothing
  summary  <- summarize branch reason
  tape_handoff tape reason
  append_message tape summary

-- | Summarize the conversation on a forked tape
{-# LLM #-}
prim_op summarize :: Tape -> String -- ^ reason for compaction
  -> String
```

**Key points:**
- `fork_tape` creates isolated context for the summarization
- `tape_handoff` truncates history (the anchor)
- `append_message` injects the summary
- The whole flow is visible, typed, and modifiable

### Scene 3 — Subagents as Function Calls (3 min)

Show subagents not as a framework tool, but as ordinary functions:

```systemf
-- | Delegate exploration to a child agent
{-# LLM #-}
prim_op explore :: Tape -- ^ parent tape snapshot
  -> String  -- ^ topic
  -> String

-- | Run parallel explorations and merge results
research :: String -> IO String
research topic = do
  let t = current_tape ()
      a = fork_tape t Nothing
      b = fork_tape t Nothing
  ra <- explore a topic
  rb <- explore b (topic ++ " edge cases")
  return (ra ++ "\n---\n" ++ rb)
```

**Key points:**
- `explore` is just a function with a tape argument
- Parallel subagents are just multiple `fork_tape` calls
- No hidden context passing — the tape is explicit

### Scene 4 — Extending the Pattern (2 min)

Show how easy it is to customize:

```systemf
-- | Custom compaction with topic-aware summarization
compact_with_topics :: Tape -> IO ()
compact_with_topics tape = do
  topics <- extract_topics tape
  let branch = fork_tape tape Nothing
      prompt = "Summarize, keeping these topics: " ++ show topics
  summary <- ask branch prompt
  tape_handoff tape "topic-aware-compact"
  append_message tape summary
```

**Key points:**
- Extract topics before compaction
- Customize the summarization prompt
- The logic is in your code, not the framework

### Scene 5 — The Contrast (1 min)

| Feature | Claude Code / Other Tools | SystemF |
|---|---|---|
| Compaction | `/compact` — opaque | `compact tape "reason"` — visible code |
| Subagents | Tool call — hidden context | Function call — tape is explicit |
| Customization | Prompt tweaks only | Restructure the logic entirely |
| Replay | Can't replay | Tape is data in SQLite — replay from any point |

## What This Proves

1. **Agent operations are just code** — not framework magic
2. **Context is a value** — you pass it around, fork it, inspect it
3. **Extensible by default** — change the logic, not just the prompt

## Technical Requirements

- [ ] `tape_handoff` primop implemented (status.md #18)
- [ ] Working `fork_tape`, `append_message`, `current_tape`
- [ ] LLM pragma for `summarize` and `explore`
- [ ] SQLite tape store with inspectable entries

## Fallback Plan

If LLM API is slow:
- Pre-populate tape with entries showing a long conversation
- Show `fork_tape` and `handoff` as mechanical operations
- Demonstrate SQLite inspection without LLM calls

## Deliverables

- [x] Research existing documentation and architecture
- [x] Draft focused demo script
- [ ] Prepare demo environment with sample tape
- [ ] Verify all components work together
- [ ] Rehearse with timing
