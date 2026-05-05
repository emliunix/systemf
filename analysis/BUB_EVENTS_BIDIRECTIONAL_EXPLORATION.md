# Exploration: bub_events Bidirectional Request-Response (Master)

## Topic Tree

```
Master: BUB_EVENTS_BIDIRECTIONAL_EXPLORATION.md
├── Question: How to link inbound HTTP requests to outbound framework responses without modifying bub/
│
├── Consolidated Reference: ChannelMessage Definition and Usage
│   └── File: ./BUB_EVENTS_CHANNEL_MESSAGE_EXPLORATION.md
│   └── Contains: Full field definitions, usage patterns, propagation semantics
│
├── Sub-Exploration 1: Field Propagation Analysis (legacy)
│   └── File: ./BUB_EVENTS_FIELD_PROPAGATION_EXPLORATION.md
│
├── Sub-Exploration 2: Hook Mechanism Analysis (legacy)
│   └── File: ./BUB_EVENTS_HOOK_MECHANISM_EXPLORATION.md
│
├── Sub-Exploration 3: Session ID Linking Design (legacy)
│   └── File: ./BUB_EVENTS_SESSION_ID_LINKING_EXPLORATION.md
│
└── Sub-Exploration 4: Field Usage Definitions (legacy)
    └── File: ./BUB_EVENTS_FIELD_USAGE_EXPLORATION.md
```

## Design Principle

**HTTP request-response is naturally paired.** The user does not need to pass any correlation ID. Each HTTP POST to `/event` waits for the corresponding response. The `session_id` field is an internal implementation detail of the `bub_events` channel, not an API concept.

## Notes

### Note 2: ChannelMessage Field Definitions (Consolidated)

Based on `./BUB_EVENTS_CHANNEL_MESSAGE_EXPLORATION.md`, the framework's message contract:

**Propagated fields** (survive round-trip via `render_outbound`):
- `session_id` — Framework-managed correlation key. **Only field both consumed and reproduced.**
- `channel` — Routing fallback, auto-added to context as `$channel`
- `chat_id` — Sub-identifier, auto-added to context
- `kind` — Message type ("normal" | "command" | "error")
- `output_channel` — Routing override (defaults to `channel`)
- `content` — Semantic change: user prompt → LLM response

**Consume-only fields** (lost in `render_outbound`):
- `context` — Prompt metadata, visible to LLM during turn, lost on response path
- `media` — Multimodal attachments
- `lifespan` — Channel-framework lifecycle contract (managed by `load_state`/`save_state` hooks)

**Unused by framework**:
- `is_active` — Channel-specific flag

**Critical insight:** `render_outbound` constructs a **new** `ChannelMessage` instance. It does not modify the inbound message. Fields not explicitly passed get default values (empty dict, empty list, None).

## Master Claim

### Claim 1: session_id-Based Linking Is the Only Viable Solution
**Reasoning:** Field propagation analysis (Sub 1) shows that `context` is lost in `render_outbound`. Hook mechanism analysis (Sub 2) shows that no hook can inject metadata without causing duplicates or being ignored. Session ID linking (Sub 3) demonstrates that `session_id` naturally survives the round-trip. By generating a UUID per HTTP request and using it as `session_id`, the channel can internally match outbound responses to waiting HTTP requests.
**References:** ./BUB_EVENTS_FIELD_PROPAGATION_EXPLORATION.md, ./BUB_EVENTS_HOOK_MECHANISM_EXPLORATION.md, ./BUB_EVENTS_SESSION_ID_LINKING_EXPLORATION.md, ./BUB_EVENTS_FIELD_USAGE_EXPLORATION.md

### Claim 2: User Should Not Pass session_id
**Reasoning:** `session_id` is a bub framework concept for state routing across turns. In HTTP request-response semantics, each request is independent. The user does not need to (and should not) manage session IDs. If they want to pass state identifiers, they should use `meta` which becomes part of `context` and is visible to the LLM and custom hooks.
**References:** ./BUB_EVENTS_SESSION_ID_LINKING_EXPLORATION.md

### Claim 3: context["user_session_id"] Is Not Needed
**Reasoning:** The original design preserved the user's `session_id` in `context["user_session_id"]`. But since the user should not pass `session_id` (Claim 2), this field serves no purpose. The channel generates a UUID for `session_id` internally, and that's sufficient for linking. Any state identifiers the user wants to pass should go in `meta`.
**References:** Claim 2
