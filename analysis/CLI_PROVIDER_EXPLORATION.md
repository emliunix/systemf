# Exploration: Bub CLI Provider Mechanism

## Notes

### Note 1: Goal
Understand how Bub CLI commands are registered and dispatched, specifically so we can add a `print_tape` command to `bub_sf.hook`.

### Note 2: Entry Point
Bub uses Pluggy hooks. The hook spec `register_cli_commands(self, app: Any)` is the extension point for adding CLI commands.

## Facts

### Fact 1: CLI Bootstrap Chain
`bub/src/bub/__main__.py:27-42`
```python
def create_cli_app() -> typer.Typer:
    _instrument_bub()
    framework = BubFramework()
    framework.load_hooks()
    app = framework.create_cli_app()
    ...
    return app
```

### Fact 2: Framework Creates Typer App and Calls Hooks
`bub/src/bub/framework.py:89-103`
```python
def create_cli_app(self) -> typer.Typer:
    app = typer.Typer(name="bub", help="Batteries-included, hook-first AI framework", add_completion=False)

    @app.callback(invoke_without_command=True)
    def _main(ctx: typer.Context, workspace: str | None = ...):
        ...
        ctx.obj = self

    self._hook_runtime.call_many_sync("register_cli_commands", app=app)
    return app
```

### Fact 3: Hook Spec Definition
`bub/src/bub/hookspecs.py:79-81`
```python
@hookspec
def register_cli_commands(self, app: Any) -> None:
    """Register CLI commands onto the root Typer application."""
```

### Fact 4: Builtin Implementation Registers Commands
`bub/src/bub/builtin/hook_impl.py:177-188`
```python
@hookimpl
def register_cli_commands(self, app: typer.Typer) -> None:
    from bub.builtin import cli

    app.command("run")(cli.run)
    app.command("chat")(cli.chat)
    app.command("onboard")(cli.onboard)
    app.add_typer(cli.login_app)
    app.command("hooks", hidden=True)(cli.list_hooks)
    app.command("gateway")(cli.gateway)
    app.command("install")(cli.install)
    app.command("uninstall")(cli.uninstall)
    app.command("update")(cli.update)
```

### Fact 5: SF Hook Implementation Does Not Register CLI Commands
`bub_sf/src/bub_sf/hook.py:124-212`
The `SFHookImpl` class implements `load_state`, `run_model_stream`, `system_prompt`, `provide_tape_store`, and `shutdown` — but does **not** implement `register_cli_commands`.

### Fact 6: CLI Command Signature Pattern
`bub/src/bub/builtin/cli.py:37-62`
```python
def run(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="Inbound message content"),
    channel: str = typer.Option("cli", "--channel", help="Message channel"),
    ...
) -> None:
    framework = ctx.ensure_object(BubFramework)
    ...
```

## Claims

### Claim 1: Adding a CLI Command Requires Implementing `register_cli_commands`
To add `print_tape` to the Bub CLI, `SFHookImpl` must implement the `register_cli_commands` hook spec and call `app.command("print-tape")(...)` on the passed `typer.Typer` instance.

**References:** Fact 2, Fact 3, Fact 4, Fact 5

### Claim 2: CLI Commands Receive `BubFramework` via `ctx.obj`
The framework instance is injected into `typer.Context.obj` by the `_main` callback (`Fact 2`). Commands can retrieve it with `ctx.ensure_object(BubFramework)`.

**References:** Fact 2, Fact 6

### Claim 3: Multiple Hook Implementations Can Register Commands on the Same App
`call_many_sync("register_cli_commands", app=app)` invokes **all** registered hook implementations. The builtin impl adds `run`, `chat`, etc.; `SFHookImpl` can add `print-tape` without conflict.

**References:** Fact 2, Fact 4
