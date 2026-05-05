"""CLI commands for tape inspection."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer
from republic.tape.entries import TapeEntry
from republic.tape.query import TapeQuery
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
            if limit is None and not kind:
                entries = await store.read(tape_name)
            else:
                query = TapeQuery(store=store, tape=tape_name)
                if kind:
                    query = query.kinds(*kind)
                if limit is not None:
                    query = query.limit(limit)
                entries = await store.fetch_all(query)

            if entries is None:
                typer.secho(f"Tape '{tape_name}' not found.", err=True, fg=typer.colors.RED)
                raise typer.Exit(1)

            if not entries:
                typer.echo("(no entries)")
                return

            for entry in entries:
                _print_entry(entry)

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


def _print_entry(entry: TapeEntry) -> None:
    """Print a single tape entry with rich formatting."""
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
    """Render a message entry."""
    lines: list[str] = []
    role = payload.get("role")
    if role:
        lines.append(f"role: {role}")
    content = payload.get("content")
    if isinstance(content, list):
        lines.append("content:")
        lines.append(_pretty_json(content))
    elif isinstance(content, str):
        lines.append(f"content: {content}")
    else:
        lines.append(_pretty_json(payload))
    return "\n".join(lines)


def _render_anchor(payload: dict[str, Any]) -> str:
    """Render an anchor entry."""
    lines = [f"Anchor: {payload.get('name', '')}"]
    state = payload.get("state")
    if state is not None:
        lines.append(_pretty_json(state))
    return "\n".join(lines)


def _render_tool_call(payload: dict[str, Any]) -> str:
    """Render a tool_call entry."""
    calls = payload.get("calls", [])
    return _pretty_json(calls)


def _render_tool_result(payload: dict[str, Any]) -> str:
    """Render a tool_result entry."""
    results = payload.get("results", [])
    return _pretty_json(results)


def _render_error(payload: dict[str, Any]) -> str:
    """Render an error entry."""
    return _pretty_json(payload)


def _render_event(payload: dict[str, Any]) -> str:
    """Render an event entry."""
    lines = [f"Event: {payload.get('name', '')}"]
    data = payload.get("data")
    if data is not None:
        lines.append(_pretty_json(data))
    return "\n".join(lines)


def _pretty_json(value: Any) -> str:
    """Pretty-print a value as indented JSON."""
    return json.dumps(value, indent=2, ensure_ascii=False)
