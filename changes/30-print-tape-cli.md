# Change Plan: Add `print-tape` CLI Command to `bub_sf.hook`

## Facts

1. `bub_sf.hook.SFHookImpl` provides a `SQLiteForkTapeStore` (`tape_store.db`) via the `provide_tape_store` hook (`bub_sf/src/bub_sf/hook.py:204-206`).
2. The store implements `AsyncTapeStore` with `read(tape: str) -> list[TapeEntry]` and `list_tapes() -> list[str]` (`bub_sf/docs/store/core.md:217-258`).
3. `TapeEntry` has fields: `id` (assigned entry_id), `kind`, `payload` (dict), `meta` (dict), `date` (ISO string) (`republic/src/republic/tape/entries.py:16-24`).
4. Bub CLI commands are registered via the `register_cli_commands` hook spec (`bub/src/bub/hookspecs.py:79-81`). The framework calls all implementations with a `typer.Typer` instance (`bub/src/bub/framework.py:102`).
5. `SFHookImpl` does **not** currently implement `register_cli_commands`.
6. CLI commands access the `BubFramework` instance via `ctx.ensure_object(BubFramework)` (`bub/src/bub/builtin/cli.py:47`).
7. Tape entry kinds observed in the codebase: `message`, `system`, `anchor`, `tool_call`, `tool_result`, `error`, `event` (`republic/src/republic/tape/entries.py:30-61`).
8. The `message` kind payload follows OpenAI message format: `{"role": str, "content": str | list[dict]}`.
9. The store is async; CLI commands run sync. We can use `asyncio.run()` to bridge, as done in `bub/src/bub/builtin/cli.py:56`.

## Design

### New Hook Method

Add `@hookimpl` method to `SFHookImpl`:

```python
@hookimpl
def register_cli_commands(self, app: typer.Typer) -> None:
    from bub_sf.hook_cli import register_commands
    register_commands(app, self)
```

This keeps the CLI command logic in a separate module to avoid bloating `hook.py`.

### New Module: `bub_sf/src/bub_sf/hook_cli.py`

Implement two commands:

1. **`bub print-tape <tape_name>`** — Print all entries of a tape.
2. **`bub list-tapes`** — Print all tape names (optional but useful).

Both commands need async-to-sync bridging. They access `SFHookImpl.fork_store` directly since `register_cli_commands` receives `self`.

### Entry Rendering Format

Each entry is printed as:

```
---
entry_id: <int>
kind: <str>
date: <ISO timestamp>
<meta keys if any>
---
<body>

```

(empty line between entries)

#### Per-Kind Body Mapping

| Kind | Body |
|------|------|
| `message` | If payload has `role`, print `role: <role>` then `content`. If content is a list (multimodal), pretty-print as JSON. Otherwise print as plain text. |
| `system` | Print `payload["content"]` as plain text. |
| `anchor` | Print `Anchor: <name>`. If `state` present, pretty-print as indented JSON. |
| `tool_call` | Pretty-print `payload["calls"]` as indented JSON array. |
| `tool_result` | Pretty-print `payload["results"]` as indented JSON array. |
| `error` | Pretty-print entire payload as indented JSON. |
| `event` | Print `Event: <name>`. If `data` present, pretty-print as indented JSON. |
| fallback | Pretty-print entire payload as indented JSON. |

### Command Signatures

```python
import typer

def print_tape(
    ctx: typer.Context,
    tape_name: str = typer.Argument(..., help="Name of the tape to print"),
    limit: int = typer.Option(None, "--limit", "-n", help="Limit number of entries"),
    kinds: list[str] = typer.Option(None, "--kind", help="Filter by entry kind"),
) -> None:
    ...

def list_tapes(ctx: typer.Context) -> None:
    ...
```

## Why It Works

1. **Hook integration:** `register_cli_commands` is the canonical Bub extension point for CLI commands. Adding it to `SFHookImpl` follows the same pattern as `BuiltinImpl`.
2. **Direct store access:** `SFHookImpl` already holds `fork_store`. The CLI functions can use it directly without going through the framework, avoiding unnecessary indirection.
3. **Async bridging:** `asyncio.run()` is the standard pattern in the codebase for calling async code from sync CLI handlers.
4. **Text format:** YAML front-matter + body is a well-understood, parseable format. It makes tape entries inspectable in a terminal and greppable.
5. **Kind-specific rendering:** Treating `message` specially (role/content) makes conversation tapes readable. Falling back to JSON for structured kinds ensures no data loss.

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_sf/src/bub_sf/hook.py` | Modify | Add `register_cli_commands` hookimpl to `SFHookImpl` |
| `bub_sf/src/bub_sf/hook_cli.py` | Create | `print_tape` and `list_tapes` command implementations |
| `bub_sf/tests/test_hook_cli.py` | Create | Unit tests for rendering logic and command handlers |

## Checklist

- [x] Inventory call sites — `register_cli_commands` is called once in `framework.py:102`; `SFHookImpl` has no existing CLI registrations.
- [x] Categorize migration patterns — No API changes; purely additive.
- [x] Decide delete vs migrate — N/A; no obsolete code.
- [x] Identify pre-existing debt vs new bugs — N/A.
- [x] Check production code separately from tests — Covered.
- [x] Verify line numbers match actual files — Verified against `main` branch state.
- [x] List all files to modify, delete, or create — Listed above.
