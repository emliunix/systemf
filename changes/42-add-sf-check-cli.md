# Change Plan: Add `sf-check` CLI Command

## Facts

- `bub_sf` is a Bub plugin that integrates SystemF REPL into the agent framework
- CLI commands are registered via `register_cli_commands` hook in `hook_cli.py`
- Commands use `typer` and are attached to the main `bub` CLI app
- SystemF REPL has a `pipeline.execute()` function that does: parse → rename → typecheck → return Module (no evaluation)
- `REPL._load_module(name, file)` reads a file and calls `pipeline.execute()`
- `REPL.search_paths` controls where modules are looked up; parts are joined with `/` and `.sf` appended
- Existing CLI commands: `print-tape`, `list-tapes`
- The user wants to typecheck (not evaluate) a SystemF module from CLI

## Design

### CLI Interface

```bash
uv run bub sf-check -L some/path test.hello
```

- `sf-check`: command name
- `-L PATH`: search path (repeatable, like traditional compilers)
- `MODULE`: module path using dot notation (e.g., `test.hello` → `test/hello.sf`)

### Implementation

Add to `bub_sf/hook_cli.py`:

```python
@app.command("sf-check")
def sf_check(
    ctx: typer.Context,
    module: str = typer.Argument(..., help="Module path to typecheck (e.g., test.hello)"),
    search_paths: list[str] = typer.Option([], "-L", help="Additional search paths"),
) -> None:
    """Typecheck a SystemF module without evaluating it."""
```

Implementation steps:
1. Create a temporary `REPL` instance with the given search paths
2. Call `repl.load(module)` which internally calls `pipeline.execute()`
3. If successful, print "OK: <module>" with the list of exported names
4. If error, print error and exit with code 1

The `REPL` class is imported from `systemf.elab3.repl`.

### New Skill Directory

Create `src/skills/sf-coding/` containing:
- `README.md` — describes the skill and shows the CLI usage
- `example.sf` — a small example SystemF program

## Why It Works

- `pipeline.execute()` does all the compilation phases except evaluation, which is exactly what we want for typechecking
- Using `-L` follows the de facto standard for compiler search paths
- Dot-notation for modules matches how SystemF already works (see `REPL._mod_file`)
- No framework state needed — this is a pure compilation check, so we don't need the hook_impl or fork_store

## Files

| File | Action | Description |
|------|--------|-------------|
| `bub_sf/src/bub_sf/hook_cli.py` | Modify | Add `sf-check` command |
| `src/skills/sf-coding/README.md` | Create | Skill documentation |
| `src/skills/sf-coding/example.sf` | Create | Example SystemF program |
