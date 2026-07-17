# Repository Guidelines

This is the SystemF + Bub agent platform: a uv Python monorepo. See `README.md`,
`status.md`, and `deploy.md` for product context. Per-package guidance lives in
`bub/AGENTS.md`, `systemf/`, `bub_sf/`, and `bub_events/`.

## Cursor Cloud specific instructions

### Toolchain & layout
- Dependencies are managed by **uv** (installed at `~/.local/bin`, already on `PATH` via `~/.bashrc`). The startup update script runs `git submodule update --init --recursive` + `uv sync`.
- The workspace requires **Python 3.14**, which uv provisions automatically — do not rely on the system `python3` (3.12).
- Workspace members: `systemf`, `bub_sf`, `bub_events` (this repo) plus git submodules `bub` and `republic`. The submodules must be initialized before `uv sync` works.

### Running services / commands
- Standard commands are documented in `README.md` and `bub/AGENTS.md`: `uv run bub chat` (interactive CLI), `uv run bub gateway` (channel listener), `uv run bub run "<msg>"` (one-shot pipeline), `uv run bub sf-check <mod> -L .` (typecheck SystemF, no LLM).
- SystemF language REPL (no LLM needed): `cd systemf && uv run python -m systemf.elab3.repl_main`. It reads from stdin; pipe lines and end with `:quit`.
- Tests: run `uv run pytest -q` from within a package dir (`systemf/`, `bub_sf/`, `bub_events/`, `bub/`, `republic/`). Lint: `uv run ruff check <pkg>/src`.

### Non-obvious caveats
- **LLM key required for the agent flow.** `bub run`/`chat`/`gateway` call an LLM and fail with `No openrouter API key provided` unless `OPENROUTER_API_KEY` (or `BUB_API_KEY`) is set. The core SystemF language (REPL, `sf-check`, typecheck/eval) works with no key.
- **Bub commands often don't exit cleanly.** Many `bub` CLI invocations and `uv run pytest` in `bub/` print their results but then hang (a background thread keeps the process alive). Wrap them in `timeout` (a `124` exit after output is expected). `bub sf-check` does exit cleanly.
- **SQLite tape store sidecars.** `bub_sf` auto-creates `tape_store.db` in the current working directory. If you delete it, also delete `tape_store.db-shm`, `tape_store.db-wal`, and `tape_store.db-journal` — a stale sidecar makes SQLite raise `disk I/O error` and the `sf` plugin fails to initialize. These files are gitignored at the repo root but not inside the `bub/` submodule, so avoid running `bub` from inside `bub/`.
- **`uv run` in a package dir installs that package's dev/test group;** a subsequent root `uv sync` may remove those extras (they are re-added on the next `uv run`).

### Pre-existing test failures (not environment issues)
- `systemf/tests/test_elab3/test_repl_session_funcall.py` fails to import (stale `mk_funcall` reference). Exclude it with `--ignore` to run the rest (668 pass).
- The `bub` and `republic` submodules have some failing tests at their pinned commits (API drift in their own test files). The core workspace packages (`systemf`, `bub_sf`, `bub_events`) pass.
