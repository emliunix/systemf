# Design: Extend Channel to Support Events

## Status
Placeholder — design pending.

## Description

Channel is the owner of session, and hence session_id. It is the direct source that knows when a session is idle and needs to compact the context to prepare for later messages.

We need to consider extending the channel abstraction to support events:

- **Session ownership**: Channel owns the session lifecycle and session_id.
- **Idle detection**: Channel knows when a session becomes idle.
- **Context compaction**: Channel is responsible for triggering context compaction when a session goes idle, to keep the context window healthy for future messages.

## References
- Todo item in `status.md`
