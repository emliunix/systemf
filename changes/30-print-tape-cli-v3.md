# Change Plan: Add `print-tape` CLI Command to `bub_sf.hook` (v3)

## Problem Statement

The v2 implementation violated the architectural boundary by modifying **republic** (the core framework) to add presentation-layer concerns. Specifically:

- `GroupedEntry`, `group_entries()`, `PRIMARY_KINDS`, `SECONDARY_KINDS` were added to `republic/src/republic/tape/entries.py`
- `is_primary()` / `is_secondary()` methods were added to `TapeEntry`
- `read_grouped()` was added to the `AsyncTapeStore` protocol in `republic/src/republic/tape/store.py`
- Tests were added to `republic/tests/test_group_entries.py`

Republic must remain agnostic to presentation concerns. The grouping heuristic is experimental and CLI-specific. It does not belong in the core framework protocol.

## Facts

1. `bub_sf.hook.SFHookImpl` provides a `SQLiteForkTapeStore` via `provide_tape_store` (`bub_sf/src/bub_sf/hook.py:203-206`).
2. The store implements `AsyncTapeStore` with `read(tape: str) -> list[TapeEntry] | None` and `list_tapes() -> list[str]` (`bub_sf/src/bub_sf/store/fork_store.py:429-479`).
3. `TapeEntry` has fields: `id`, `kind`, `payload` (dict), `meta` (dict), `date` (ISO string) (`republic/src/republic/tape/entries.py:16-24`).
4. Bub CLI commands are registered via `register_cli_commands` hook spec (`bub/src/bub/hookspecs.py:79-81`). The framework calls all implementations with a `typer.Typer` instance (`bub/src/bub/framework.py:102`).
5. `SFHookImpl` implements `register_cli_commands` (`bub_sf/src/bub_sf/hook.py:205-210`).
6. CLI commands access the `BubFramework` instance via `ctx.ensure_object(BubFramework)` (`bub/src/bub/builtin/cli.py:47`).
7. Tape entry kinds observed: `message`, `system`, `anchor`, `tool_call`, `tool_result`, `error`, `event` (`republic/src/republic/tape/entries.py:30-61`).
8. The store is async; CLI commands run sync. We use `asyncio.run()` to bridge (`bub/src/bub/builtin/cli.py:56`).
9. `TapeQuery` supports `kinds` filtering and `limit` via `fetch_all` (`republic/src/republic/tape/query.py:47-51`).
10. The v2 implementation added `read_grouped()` to `SQLiteForkTapeStore` (`bub_sf/src/bub_sf/store/fork_store.py:455-460`) which delegates to `group_entries()` imported from republic.

## Design

### Guiding Principle

**All grouping logic stays in `bub_sf`. Republic remains unchanged.**

### Revert Republic Changes

Restore these files to their pre-v2 state:

| File | Action |
|------|--------|
| `republic/src/republic/tape/entries.py` | Revert — remove `PRIMARY_KINDS`, `SECONDARY_KINDS`, `is_primary()`, `is_secondary()`, `GroupedEntry`, `group_entries()` |
| `republic/src/republic/tape/store.py` | Revert — remove `read_grouped()` from `AsyncTapeStore`, revert imports |
| `republic/tests/test_group_entries.py` | Delete |

### New Module: `bub_sf/src/bub_sf/tape_grouping.py`

Move the grouping logic from republic into a new `bub_sf`-local module:

```python
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
            post_secondary = [e for e in pre if e.kind in ("error", "event")]
            pre_secondary = [e for e in pre if e.kind not in ("error", "event")]
            if pre_secondary:
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
```

### Update `bub_sf/src/bub_sf/hook_cli.py`

Replace the republic import with the local module:

```python
# OLD
from republic.tape.entries import GroupedEntry, TapeEntry, group_entries

# NEW
from republic.tape.entries import TapeEntry
from bub_sf.tape_grouping import GroupedEntry, group_entries
```

Update `print_tape()` to use `store.read()` + local `group_entries()` instead of `store.read_grouped()`:

```python
async def _run() -> None:
    flat_entries = await store.read(tape_name)
    if flat_entries is None:
        typer.secho(f"Tape '{tape_name}' not found.", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)

    if not flat_entries:
        typer.echo("(no entries)")
        return

    system_entries = [e for e in flat_entries if e.kind == "system"]
    other_entries = [e for e in flat_entries if e.kind != "system"]

    if limit is not None or kind:
        query = TapeQuery(store=store, tape=tape_name)
        if kind:
            query = query.kinds(*kind)
        if limit is not None:
            query = query.limit(limit)
        other_entries = list(await store.fetch_all(query))
        other_entries = [e for e in other_entries if e.kind != "system"]

    if other_entries:
        grouped = group_entries(other_entries)
        for entry in grouped:
            _print_entry(entry)

    if system_entries and not kind:
        last_system = system_entries[-1]
        _print_entry(last_system)
```

### Remove `read_grouped()` from `SQLiteForkTapeStore`

Delete `read_grouped()` from `bub_sf/src/bub_sf/store/fork_store.py` (lines 455-460) and remove the `GroupedEntry` / `group_entries` imports from that file.

### Update Tests

| File | Action |
|------|--------|
| `republic/tests/test_group_entries.py` | Delete (moved to bub_sf) |
| `bub_sf/tests/test_tape_grouping.py` | Create — move all grouping tests here, update imports |
| `bub_sf/tests/store/test_fork_tape_store.py` | Modify — remove `test_read_grouped_*` tests |

### Update `bub_sf/tests/test_hook_cli.py`

Update imports to use `TapeEntry` from republic and remove any dependency on republic's grouping.

## Why It Works

1. **Boundary respected:** Republic remains a pure framework with no knowledge of CLI presentation concerns. The grouping heuristic is experimental and may change; keeping it in `bub_sf` prevents framework lock-in.
2. **Zero framework changes:** No files in `republic/` are modified. The submodule stays clean.
3. **Same UX:** The `print-tape` CLI behavior is identical. Only the code location changes.
4. **Local evolution:** `bub_sf` can iterate on grouping logic (e.g., changing what counts as primary/secondary) without a republic release.
5. **Protocol purity:** `AsyncTapeStore` keeps its minimal interface. Presentation helpers are not core storage concerns.

## Files

| File | Action | Description |
|------|--------|-------------|
| `republic/src/republic/tape/entries.py` | Revert | Remove grouping additions |
| `republic/src/republic/tape/store.py` | Revert | Remove `read_grouped()` and imports |
| `republic/tests/test_group_entries.py` | Delete | Tests belong in bub_sf |
| `bub_sf/src/bub_sf/tape_grouping.py` | Create | Grouping logic moved from republic |
| `bub_sf/src/bub_sf/hook_cli.py` | Modify | Use local grouping; remove `read_grouped()` usage |
| `bub_sf/src/bub_sf/store/fork_store.py` | Modify | Remove `read_grouped()` and imports |
| `bub_sf/tests/test_tape_grouping.py` | Create | Grouping tests from republic |
| `bub_sf/tests/store/test_fork_tape_store.py` | Modify | Remove `read_grouped` tests |
| `bub_sf/tests/test_hook_cli.py` | Modify | Update imports |

## Checklist

- [x] Inventory call sites — `group_entries` imported in `hook_cli.py` and `fork_store.py`; `read_grouped` in `fork_store.py` and tests.
- [x] Categorize migration patterns — Republic code is reverted (delete). bub_sf code is updated (import change + local definition).
- [x] Decide delete vs migrate — Delete from republic; migrate to bub_sf.
- [x] Identify pre-existing debt vs new bugs — The v2 design was the debt (wrong layer).
- [x] Check production code separately from tests — Covered.
- [x] Verify line numbers match actual files — Verified against current dirty state.
- [x] List all files to modify, delete, or create — Listed above.
