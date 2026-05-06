# 36: Sync Message Processing by Session (Tape) in Channel Manager

**Date:** 2026-05-06
**Status:** Proposed
**Area:** `bub/src/bub/channels/manager.py`

## Problem

**Tape is an append-only list of entries.** When multiple agent calls use the **same tape** in parallel, they see each other's progress — appending entries interleaved with their own. This is the "brain interleaving" problem.

**Fact:** Session ID determines tape.  
**Consequence:** If the channel manager processes multiple inbound messages for the same session ID concurrently, they all operate on the same tape, corrupting each other's context.

### Example

Session `user:123` sends two messages quickly:
1. Message A starts an agent turn, begins appending to tape `user:123`
2. Message B starts another agent turn on the same tape before A finishes
3. Both agents see a mix of each other's tool calls, responses, and reasoning
4. Neither agent has a coherent view of its own conversation

## Proposal

Limit to **1 parallel processing of inbound message by session ID** in `ChannelManager`.

- If a message arrives for a session that is already being processed, queue it
- Only start processing the next message for that session when the current one completes
- Different sessions still process concurrently

## Implementation Notes

This is essentially the same as item 35 (channel manager session serialization). The key insight is **why** serialization is needed: tape append-only semantics make parallel access unsafe.

- Use per-session queues or locks in `ChannelManager`
- See `changes/35-channel-manager-session-serialization.md` for detailed design options

## Related

- `changes/35-channel-manager-session-serialization.md` — detailed serialization design
- `status.md` item 16 — channel manager session serialization
