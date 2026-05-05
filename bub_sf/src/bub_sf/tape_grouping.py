"""Tape entry grouping logic for CLI presentation.

This module provides a presentation-layer view that groups flat tape entries
into primary-secondary relationships. It is intentionally kept in bub_sf (not
republic) because the grouping heuristic is CLI-specific and experimental.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from republic.tape.entries import TapeEntry

PRIMARY_KINDS = {"message", "anchor"}
SECONDARY_KINDS = {"tool_call", "tool_result", "system", "error", "event"}


@dataclass(frozen=True)
class GroupedEntry:
    """A primary entry with its associated secondary entries."""

    primary: TapeEntry
    pre: list[TapeEntry] = field(default_factory=list)
    post: list[TapeEntry] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.primary.id

    @property
    def kind(self) -> str:
        return self.primary.kind

    @property
    def payload(self) -> dict[str, Any]:
        return self.primary.payload

    @property
    def meta(self) -> dict[str, Any]:
        return self.primary.meta

    @property
    def date(self) -> str:
        return self.primary.date


def group_entries(entries: list[TapeEntry]) -> list[GroupedEntry]:
    """Group a flat list of entries into primary-secondary pairs.

    Primary kinds (message, anchor) stand alone. Secondary kinds
    (tool_call, tool_result, system, error, event) are absorbed
    into the nearest primary entry:

    - Pre-secondary entries (tool_call, tool_result, system) are
      prepended to the next primary entry.
    - Post-secondary entries (error, event) are appended to the
      previous primary entry.
    - Anchors reset the accumulator and start a new group.
    """
    if not entries:
        return []

    grouped: list[GroupedEntry] = []
    pre: list[TapeEntry] = []

    for entry in entries:
        if entry.kind in PRIMARY_KINDS:
            # Flush accumulated pre entries to the previous primary
            if grouped and pre:
                # Attach trailing secondary entries to previous primary's post
                # only if they are post-secondary kinds
                post_secondary = [e for e in pre if e.kind in ("error", "event")]
                if post_secondary:
                    grouped[-1] = GroupedEntry(
                        primary=grouped[-1].primary,
                        pre=grouped[-1].pre,
                        post=grouped[-1].post + post_secondary,
                    )
                    pre = [e for e in pre if e.kind not in ("error", "event")]

            grouped.append(GroupedEntry(primary=entry, pre=pre, post=[]))
            pre = []
        else:
            pre.append(entry)

    # Handle trailing secondary entries after last primary
    if pre:
        if grouped:
            # Attach to last primary's post
            post_secondary = [e for e in pre if e.kind in ("error", "event")]
            pre_secondary = [e for e in pre if e.kind not in ("error", "event")]
            if pre_secondary:
                # Orphan pre-secondary entries become a synthetic group
                # Use the last pre-secondary as primary with empty payload
                last = pre_secondary[-1]
                synthetic = TapeEntry(
                    id=last.id,
                    kind=last.kind,
                    payload=last.payload,
                    meta=last.meta,
                    date=last.date,
                )
                grouped.append(GroupedEntry(primary=synthetic, pre=pre_secondary[:-1], post=post_secondary))
            elif post_secondary:
                grouped[-1] = GroupedEntry(
                    primary=grouped[-1].primary,
                    pre=grouped[-1].pre,
                    post=grouped[-1].post + post_secondary,
                )
        else:
            # All entries are secondary — create a synthetic group
            last = pre[-1]
            synthetic = TapeEntry(
                id=last.id,
                kind=last.kind,
                payload=last.payload,
                meta=last.meta,
                date=last.date,
            )
            grouped.append(GroupedEntry(primary=synthetic, pre=pre[:-1], post=[]))

    return grouped
