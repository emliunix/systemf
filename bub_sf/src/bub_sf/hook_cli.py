"""CLI commands for tape inspection."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer
from republic.tape.entries import TapeEntry
from republic.tape.query import TapeQuery

from bub_sf.tape_grouping import GroupedEntry, group_entries
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from bub_sf.store.fork_store import SQLiteForkTapeStore


def register_commands(app: typer.Typer, hook_impl: Any) -> None:
    """Register tape CLI commands onto the Typer app."""

    @app.command("print-tape")
    def print_tape(
        ctx: typer.Context,
        tape_name: str = typer.Argument(..., help="Name of the tape to print"),
        limit: int | None = typer.Option(None, "--limit", "-n", help="Limit number of entries"),
        kind: list[str] | None = typer.Option(None, "--kind", help="Filter by entry kind (repeatable)"),
    ) -> None:
        """Print all entries of a tape."""
        store: SQLiteForkTapeStore = hook_impl.fork_store

        async def _run() -> None:
            # Read flat entries so we can separate system prompts
            flat_entries = await store.read(tape_name)

            if flat_entries is None:
                typer.secho(f"Tape '{tape_name}' not found.", err=True, fg=typer.colors.RED)
                raise typer.Exit(1)

            if not flat_entries:
                typer.echo("(no entries)")
                return

            # Separate system entries from everything else
            system_entries = [e for e in flat_entries if e.kind == "system"]
            other_entries = [e for e in flat_entries if e.kind != "system"]

            # Apply limit/kind filters to non-system entries if requested
            if limit is not None or kind:
                query = TapeQuery(store=store, tape=tape_name)
                if kind:
                    query = query.kinds(*kind)
                if limit is not None:
                    query = query.limit(limit)
                other_entries = list(await store.fetch_all(query))
                # Re-filter to exclude system (fetch_all respects kinds but we want to be safe)
                other_entries = [e for e in other_entries if e.kind != "system"]

            # First pass: group and print all non-system entries
            if other_entries:
                grouped = group_entries(other_entries)
                for entry in grouped:
                    _print_entry(entry)

            # Second pass: print the last system prompt once
            if system_entries and not kind:
                last_system = system_entries[-1]
                _print_entry(last_system)

        asyncio.run(_run())
        asyncio.run(hook_impl.framework.shutdown())

    @app.command("list-tapes")
    def list_tapes(ctx: typer.Context) -> None:
        """List all tapes with creation dates (newest first)."""
        store: SQLiteForkTapeStore = hook_impl.fork_store

        async def _run() -> None:
            tapes = await store.list_tapes_ext()
            if not tapes:
                typer.echo("(no tapes)")
                return

            table = Table(title="Tapes", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan", no_wrap=True)
            table.add_column("Created", style="green")

            for name, meta in tapes:
                table.add_row(name, meta["created"])

            console = Console()
            console.print(table)

        asyncio.run(_run())
        asyncio.run(hook_impl.framework.shutdown())


def _print_entry(entry: TapeEntry | GroupedEntry) -> None:
    """Print a single tape entry or grouped entry with rich formatting."""
    if isinstance(entry, GroupedEntry):
        _print_grouped(entry)
        return

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="white")

    table.add_row("entry_id", str(entry.id))
    table.add_row("kind", entry.kind)
    table.add_row("date", entry.date)
    if entry.meta:
        for key, value in entry.meta.items():
            table.add_row(key, str(value))

    body = _render_body(entry)
    if body:
        panel = Panel(
            f"{table}\n\n{body}",
            title=f"[bold]{entry.kind}[/bold]",
            subtitle=f"[dim]id={entry.id}[/dim]",
            border_style="blue",
        )
    else:
        panel = Panel(
            str(table),
            title=f"[bold]{entry.kind}[/bold]",
            subtitle=f"[dim]id={entry.id}[/dim]",
            border_style="blue",
        )

    console = Console()
    console.print(panel)
    console.print()


def _print_grouped(grouped: GroupedEntry) -> None:
    """Print a grouped entry: encoded title + table header + plain content body."""
    primary = grouped.primary
    console = Console()

    # Print encoded title line
    title = _encode_title(primary)
    console.print(f"\n[bold]{title}[/bold]")

    # Build compact meta table
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan", no_wrap=True, width=12)
    table.add_column(style="white")

    table.add_row("id", str(primary.id))
    table.add_row("kind", primary.kind)
    table.add_row("date", primary.date)

    # Kind-specific fields
    if primary.kind == "message" and "role" in primary.payload:
        table.add_row("role", primary.payload["role"])
    elif primary.kind == "anchor" and "name" in primary.payload:
        table.add_row("name", primary.payload["name"])

    # Meta fields
    if primary.meta:
        for key, value in primary.meta.items():
            table.add_row(key, str(value))

    # Pre entries in meta table
    for entry in grouped.pre:
        table.add_row(f"↑ {entry.kind}", f"id={entry.id}")
        _add_summary_rows(table, entry, indent=2)

    # Post entries in meta table
    for entry in grouped.post:
        table.add_row(f"↓ {entry.kind}", f"id={entry.id}")
        _add_summary_rows(table, entry, indent=2)

    # Print meta table in a thin panel
    console.print(Panel(table, border_style="blue", padding=(0, 1)))

    # Print primary content directly (no box wrapping)
    body = _render_body(primary)
    if body:
        console.print(body)

    # Print pre secondary content with separators
    for entry in grouped.pre:
        if entry.kind in ("tool_call", "tool_result", "system"):
            _print_secondary_body(console, entry)

    # Print post secondary content with separators
    for entry in grouped.post:
        if entry.kind in ("tool_call", "tool_result", "error"):
            _print_secondary_body(console, entry)


def _encode_title(entry: TapeEntry) -> str:
    """Encode kind, id, and key attributes into a title line."""
    parts = [entry.kind, f"id={entry.id}"]

    if entry.kind == "message" and "role" in entry.payload:
        parts.append(f"role={entry.payload['role']}")
    elif entry.kind == "anchor" and "name" in entry.payload:
        parts.append(f"name={entry.payload['name']}")

    return " | ".join(parts)


def _add_summary_rows(table: Table, entry: TapeEntry, indent: int = 0) -> None:
    """Add summary rows for secondary entries to the meta table."""
    prefix = " " * indent

    match entry.kind:
        case "event":
            if "name" in entry.payload:
                table.add_row(f"{prefix}name", entry.payload["name"])
            if "data" in entry.payload:
                data_summary = _truncate_json(entry.payload["data"], max_len=80)
                table.add_row(f"{prefix}data", data_summary)
        case "tool_call":
            calls = entry.payload.get("calls", [])
            if calls:
                fn_names = ", ".join(
                    str(c.get("fn", c.get("function", c.get("name", "?"))))
                    for c in calls
                )
                table.add_row(f"{prefix}calls", fn_names[:60])
        case "tool_result":
            results = entry.payload.get("results", [])
            if results:
                table.add_row(f"{prefix}results", f"{len(results)} result(s)")
        case "system":
            content = entry.payload.get("content", "")
            if content:
                table.add_row(f"{prefix}content", content[:60])
        case "error":
            error_msg = entry.payload.get("message") or entry.payload.get("msg") or entry.payload.get("type", "error")
            table.add_row(f"{prefix}error", str(error_msg)[:60])


def _print_secondary_body(console: Console, entry: TapeEntry) -> None:
    """Print a secondary entry's body with a separator."""
    body = _render_body(entry)
    if not body:
        return
    console.print(f"\n[dim]--- {entry.kind} (id={entry.id}) ---[/dim]")
    console.print(body)


def _render_body(entry: TapeEntry) -> str:
    """Render the body of a tape entry based on its kind."""
    match entry.kind:
        case "message":
            return _render_message(entry.payload)
        case "system":
            return entry.payload.get("content", "")
        case "anchor":
            return _render_anchor(entry.payload)
        case "tool_call":
            return _render_tool_call(entry.payload)
        case "tool_result":
            return _render_tool_result(entry.payload)
        case "error":
            return _render_error(entry.payload)
        case "event":
            return _render_event(entry.payload)
        case _:
            return _pretty_json(entry.payload)


def _render_message(payload: dict[str, Any]) -> str:
    """Render a message entry body (role is shown in table)."""
    content = payload.get("content")
    if isinstance(content, list):
        return _pretty_json(content)
    elif isinstance(content, str):
        return content
    else:
        return _pretty_json(payload)


def _render_anchor(payload: dict[str, Any]) -> str:
    """Render an anchor entry."""
    state = payload.get("state")
    if state is not None:
        return _pretty_json(state)
    return ""


# Common tools that get biased/compact rendering
_COMMON_TOOLS = {"search", "fetch", "glob", "grep", "read", "write", "ls", "edit"}


def _render_tool_call(payload: dict[str, Any]) -> str:
    """Render a tool_call entry."""
    calls = payload.get("calls", [])
    if calls and all(isinstance(c, dict) for c in calls):
        fn_name = str(calls[0].get("fn", calls[0].get("function", calls[0].get("name", ""))))
        if fn_name in _COMMON_TOOLS:
            return _render_common_tool_call(calls)
    return _pretty_json(calls)


def _render_common_tool_call(calls: list[dict[str, Any]]) -> str:
    """Render common tool calls in a compact, human-readable format."""
    lines: list[str] = []
    for call in calls:
        fn = call.get("fn", call.get("function", call.get("name", "?")))
        args = call.get("args", call.get("arguments", call.get("parameters", {})))
        if isinstance(args, dict):
            arg_str = _format_common_tool_args(fn, args)
            lines.append(f"{fn}({arg_str})")
        else:
            lines.append(f"{fn}({args})")
    return "\n".join(lines)


def _format_common_tool_args(fn: str, args: dict[str, Any]) -> str:
    """Format arguments for common tools in a compact way."""
    match fn:
        case "search" | "grep":
            parts = []
            for key in ("query", "pattern", "path", "glob"):
                if key in args:
                    parts.append(f"{key}={args[key]!r}")
            return ", ".join(parts) if parts else str(args)
        case "fetch":
            url = args.get("url", "")
            return f"url={url!r}"
        case "glob":
            pattern = args.get("pattern", "")
            return f"pattern={pattern!r}"
        case "read" | "edit" | "write":
            path = args.get("path", "")
            return f"path={path!r}"
        case "ls":
            path = args.get("path", ".")
            return f"path={path!r}"
        case _:
            return str(args)


def _render_tool_result(payload: dict[str, Any]) -> str:
    """Render a tool_result entry, truncating if too long."""
    results = payload.get("results", [])
    if results:
        # Check if this looks like a common tool result (first result is string/list)
        first = results[0]
        if isinstance(first, (str, list)):
            return _render_common_tool_result(results)
    json_str = _pretty_json(results)
    return _truncate_text(json_str, max_lines=30, max_chars=2000)


def _render_common_tool_result(results: list[Any]) -> str:
    """Render common tool results compactly."""
    if not results:
        return "(no results)"

    first = results[0]
    if isinstance(first, str):
        # File content or search results — just show count/lines
        total_len = sum(len(r) for r in results if isinstance(r, str))
        total_lines = sum(r.count("\n") for r in results if isinstance(r, str))
        return f"({total_lines} lines, {total_len} chars — output hidden for brevity)"
    elif isinstance(first, list):
        # List of matches/file paths
        total_items = sum(len(r) for r in results if isinstance(r, list))
        return f"({total_items} items — output hidden for brevity)"
    else:
        return _truncate_text(_pretty_json(results), max_lines=10, max_chars=500)


def _render_error(payload: dict[str, Any]) -> str:
    """Render an error entry."""
    return _pretty_json(payload)


def _render_event(payload: dict[str, Any]) -> str:
    """Render an event entry (usually shown in meta table only)."""
    data = payload.get("data")
    if data is not None:
        return _pretty_json(data)
    return ""


def _pretty_json(value: Any) -> str:
    """Pretty-print a value as indented JSON."""
    return json.dumps(value, indent=2, ensure_ascii=False)


def _truncate_json(value: Any, max_len: int = 80) -> str:
    """Truncate a JSON value to a short string."""
    s = json.dumps(value, ensure_ascii=False)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


def _truncate_text(text: str, max_lines: int = 30, max_chars: int = 2000) -> str:
    """Truncate text to max lines and chars, adding ellipsis if truncated."""
    lines = text.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append("... [truncated]")
        text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars - 3] + "..."
    return text
