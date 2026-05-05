# Bub Skill/Plugin Registration and Discovery Exploration

## Notes

### Note 1: Two Distinct Skill Systems in Bub
Bub has **two parallel mechanisms** for extending its capabilities:
1. **Markdown Skills** - Static knowledge files in `.agents/skills/`, loaded into LLM prompts
2. **Python Package Plugins** - Dynamic hook implementations registered via `bub` entry points

These systems serve different purposes and have different registration mechanisms.

### Note 2: Exploration Goal
Understand exactly how Bub discovers and registers both markdown skills and Python package plugins, specifically for packaging a "people" skill as a Python package that could be distributed via PyPI.

### Note 3: Key Files to Trace
- `bub/src/bub/framework.py` - Plugin loading via entry points
- `bub/src/bub/skills.py` - Markdown skill discovery
- `bub/src/bub/hookspecs.py` - Hook contracts
- `bub/src/bub/builtin/agent.py` - How skills get injected into prompts
- `bub/src/bub/tools.py` - Tool registration mechanism
- `bub/src/bub/builtin/tools.py` - Built-in tools including `skill` tool

## Facts

### Fact 1: Plugin Loading via Entry Points
`bub/src/bub/framework.py:63-87`
```python
def load_hooks(self) -> None:
    import importlib.metadata

    pending_plugins: list[tuple[str, Any]] = []

    self._load_builtin_hooks()
    for entry_point in importlib.metadata.entry_points(group="bub"):
        try:
            plugin = entry_point.load()
        except Exception as exc:
            logger.warning(f"Failed to load plugin '{entry_point.name}': {exc}")
            self._plugin_status[entry_point.name] = PluginStatus(is_success=False, detail=str(exc))
        else:
            pending_plugins.append((entry_point.name, plugin))

    for plugin_name, plugin in pending_plugins:
        try:
            if callable(plugin):  # Support entry points that are classes
                plugin = plugin(self)
            self._plugin_manager.register(plugin, name=plugin_name)
        except Exception as exc:
            logger.warning(f"Failed to initialize plugin '{plugin_name}': {exc}")
            self._plugin_status[plugin_name] = PluginStatus(is_success=False, detail=str(exc))
        else:
            self._plugin_status[plugin_name] = PluginStatus(is_success=True)
```

### Fact 2: Builtin Hooks Loaded First
`bub/src/bub/framework.py:51-61`
```python
def _load_builtin_hooks(self) -> None:
    from bub.builtin.hook_impl import BuiltinImpl

    impl = BuiltinImpl(self)

    try:
        self._plugin_manager.register(impl, name="builtin")
    except Exception as exc:
        self._plugin_status["builtin"] = PluginStatus(is_success=False, detail=str(exc))
    else:
        self._plugin_status["builtin"] = PluginStatus(is_success=True)
```

### Fact 3: Hook Specifications
`bub/src/bub/hookspecs.py:21-113`
```python
class BubHookSpecs:
    """Hook contract for Bub framework extensions."""

    @hookspec(firstresult=True)
    def resolve_session(self, message: Envelope) -> str:
        """Resolve session id for one inbound message."""

    @hookspec(firstresult=True)
    def build_prompt(self, message: Envelope, session_id: str, state: State) -> str | list[dict]:
        """Build model prompt for this turn."""

    @hookspec(firstresult=True)
    def run_model(self, prompt: str | list[dict], session_id: str, state: State) -> str:
        """Run model for one turn and return plain text output."""

    @hookspec(firstresult=True)
    def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
        """Run model for one turn and return a stream of events."""

    @hookspec
    def load_state(self, message: Envelope, session_id: str) -> State:
        """Load state snapshot for one session."""

    @hookspec
    def save_state(self, session_id: str, state: State, message: Envelope, model_output: str) -> None:
        """Persist state updates after one model turn."""

    @hookspec
    def render_outbound(self, message: Envelope, session_id: str, state: State, model_output: str) -> list[Envelope]:
        """Render outbound messages from model output."""

    @hookspec
    def dispatch_outbound(self, message: Envelope) -> bool:
        """Dispatch one outbound message to external channel(s)."""

    @hookspec
    def register_cli_commands(self, app: Any) -> None:
        """Register CLI commands onto the root Typer application."""

    @hookspec
    def onboard_config(self, current_config: dict[str, Any]) -> dict[str, Any] | None:
        """Collect a plugin config fragment for the interactive onboarding command."""

    @hookspec
    def on_error(self, stage: str, error: Exception, message: Envelope | None) -> None:
        """Observe framework errors from any stage."""

    @hookspec
    def system_prompt(self, prompt: str | list[dict], state: State) -> str:
        """Provide a system prompt to be prepended to all model prompts."""

    @hookspec(firstresult=True)
    def provide_tape_store(self) -> TapeStore | AsyncTapeStore:
        """Provide a tape store instance for Bub's conversation recording feature."""

    @hookspec
    def provide_channels(self, message_handler: MessageHandler) -> list[Channel]:
        """Provide a list of channels for receiving messages."""

    @hookspec(firstresult=True)
    def build_tape_context(self) -> TapeContext:
        """Build a tape context for the current session."""

    @hookspec
    def shutdown(self) -> None:
        """Perform any necessary cleanup when the framework is shutting down."""
```

### Fact 4: Markdown Skill Discovery
`bub/src/bub/skills.py:43-60`
```python
def discover_skills(workspace_path: Path) -> list[SkillMetadata]:
    """Discover skills from project, global, and builtin roots with override precedence."""

    skills_by_name: dict[str, SkillMetadata] = {}
    for root, source in _iter_skill_roots(workspace_path):
        if not root.is_dir():
            continue
        for skill_dir in sorted(root.iterdir()):
            if not skill_dir.is_dir():
                continue
            metadata = _read_skill(skill_dir, source=source)
            if metadata is None:
                continue
            key = metadata.name.casefold()
            if key not in skills_by_name:
                skills_by_name[key] = metadata

    return sorted(skills_by_name.values(), key=lambda item: item.name.casefold())
```

### Fact 5: Skill Root Iteration
`bub/src/bub/skills.py:147-165`
```python
def _iter_skill_roots(workspace_path: Path) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    for source in SKILL_SOURCES:
        if source == "project":
            roots.append((workspace_path / PROJECT_SKILLS_DIR, source))
            legacy_path = workspace_path / LEGACY_SKILLS_DIR
            if legacy_path.is_dir():
                warnings.warn(...)
                roots.append((legacy_path, source))
        elif source == "global":
            roots.append((Path.home() / PROJECT_SKILLS_DIR, source))
        elif source == "builtin":
            for path in _builtin_skills_root():
                roots.append((path, source))
    return roots
```

### Fact 6: Builtin Skills Root Resolution
`bub/src/bub/skills.py:141-145`
```python
def _builtin_skills_root() -> list[Path]:
    import importlib

    return [Path(p) for p in importlib.import_module("skills").__path__]
```

### Fact 7: Skills Injected into System Prompt
`bub/src/bub/builtin/agent.py:572-582`
```python
def _system_prompt(self, prompt: str, state: State, allowed_skills: set[str] | None = None) -> str:
    blocks: list[str] = []
    if result := self.framework.get_system_prompt(prompt=prompt, state=state):
        blocks.append(result)
    tools_prompt = render_tools_prompt(REGISTRY.values())
    if tools_prompt:
        blocks.append(tools_prompt)
    workspace = workspace_from_state(state)
    if skills_prompt := self._load_skills_prompt(prompt, workspace, allowed_skills):
        blocks.append(skills_prompt)
    return "\n\n".join(blocks)
```

### Fact 8: Skill Prompt Loading with Hint Expansion
`bub/src/bub/builtin/agent.py:497-504`
```python
def _load_skills_prompt(self, prompt: str, workspace: Path, allowed_skills: set[str] | None = None) -> str:
    skill_index = {
        skill.name.casefold(): skill
        for skill in discover_skills(workspace)
        if allowed_skills is None or skill.name.casefold() in allowed_skills
    }
    expanded_skills = set(HINT_RE.findall(prompt)) & set(skill_index.keys())
    return render_skills_prompt(list(skill_index.values()), expanded_skills=expanded_skills)
```

### Fact 9: Tool Registration via Decorator
`bub/src/bub/tools.py:105-132`
```python
def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    model: type[BaseModel] | None = None,
    description: str | None = None,
    context: bool = False,
) -> Tool | Callable[[Callable], Tool]:
    """Decorator to convert a function into a Tool instance."""

    result = republic_tool(
        func=func,
        name=name,
        model=model,
        description=description,
        context=context,
    )
    if isinstance(result, Tool):
        tool_instance = _add_logging(result)
        REGISTRY[tool_instance.name] = tool_instance
        return tool_instance

    def decorator(func: Callable) -> Tool:
        tool_instance = _add_logging(result(func))
        REGISTRY[tool_instance.name] = tool_instance
        return tool_instance

    return decorator
```

### Fact 10: Skill Loading Tool
`bub/src/bub/builtin/tools.py:158-172`
```python
@tool(context=True, name="skill")
def skill_describe(name: str, *, context: ToolContext) -> str:
    """Load the skill content by name. Return the location and skill content."""
    from bub.utils import workspace_from_state

    allowed_skills = context.state.get("allowed_skills")
    if allowed_skills is not None and name.casefold() not in allowed_skills:
        return f"(skill '{name}' is not allowed in this context)"

    workspace = workspace_from_state(context.state)
    skill_index = {skill.name: skill for skill in discover_skills(workspace)}
    if name.casefold() not in skill_index:
        return "(no such skill)"
    skill = skill_index[name.casefold()]
    return f"Location: {skill.location}\n---\n{skill.body() or '(no content)'}"
```

### Fact 11: Documentation on Shipping Skills in Packages
`bub/website/src/content/docs/docs/extending/plugins.mdx:66-91`
```markdown
## Ship Skills In Extension Packages

Extension packages can also ship skills by including a top-level `skills/` directory in the distribution.

Example layout:

```text
my-extension/
├─ src/
│  ├─ my_extension/
│  │  └─ plugin.py
│  └─ skills/
│     └─ my-skill/
│        └─ SKILL.md
└─ pyproject.toml
```

Configure your build backend to include the `skills/` directory in the package data. For example, with `pdm-backend`:

```toml
[tool.pdm.build]
includes = ["src/"]
```

At runtime, Bub discovers builtin skills from `<site-packages>/skills`, so packaged skills in that location are loaded automatically.
These skills use normal precedence rules and can still be overridden by workspace (`.agents/skills`) or user (`~/.agents/skills`) skills.
```

### Fact 12: Pyproject.toml Entry Point Example
`bub/website/src/content/docs/docs/getting-started/first-plugin.mdx:23-38`
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "bub-echo-plugin"
version = "0.1.0"
dependencies = ["bub"]

[project.entry-points."bub"]
echo = "bub_echo_plugin.plugin:echo_plugin"

[tool.hatch.build.targets.wheel]
packages = ["src/bub_echo_plugin"]
```

## Claims

### Claim 1: Bub Has Two Complementary Extension Mechanisms
Bub uses **markdown skills** for knowledge injection into prompts and **Python plugins** for behavioral extension via hooks. A complete "people skill" package could include both: a markdown skill for the knowledge/workflow guidance AND a Python plugin for custom tools (e.g., structured contact search, reminders).

**References:** Note 1, Fact 3, Fact 4

### Claim 2: Python Plugin Registration Uses Standard Python Entry Points
Plugins are discovered through `importlib.metadata.entry_points(group="bub")`. This is the standard Python packaging mechanism. The plugin package declares its entry point in `pyproject.toml`, and Bub's `BubFramework.load_hooks()` loads and registers them automatically. No special Bub-specific registration code is needed beyond the `@hookimpl` decorator.

**References:** Fact 1, Fact 12

### Claim 3: Plugin Hook Precedence is Load-Order Dependent
`load_hooks()` loads builtin first, then entry points in discovery order. For `firstresult=True` hooks (like `run_model`, `build_prompt`, `system_prompt`), the first implementation to return non-None wins. For multi-result hooks (like `load_state`, `system_prompt` when not firstresult), all implementations contribute. This means plugins can override builtin behavior simply by implementing the same hook.

**References:** Fact 1, Fact 2, Fact 3

### Claim 4: Markdown Skills Are Purely Prompt-Level, Not Code
Skills from `.agents/skills/` or `skills/` packages are discovered by `discover_skills()`, filtered by `allowed_skills`, and rendered into the system prompt as `<available_skills>` XML blocks. They are NOT executable code. The `skill` tool allows the agent to read full skill content on demand. This is fundamentally different from Python plugins which execute code.

**References:** Fact 4, Fact 7, Fact 8, Fact 10

### Claim 5: Packaged Skills Must Be in a `skills/` Module/Package
For Bub to discover skills from a Python package, the package must include a top-level `skills/` directory that becomes importable as the `skills` module. Bub resolves builtin skills via `importlib.import_module("skills").__path__`. This means the package structure needs to ensure `skills/` is included in the distribution and importable.

**References:** Fact 6, Fact 11

### Claim 6: Tools Use Import-Time Registration Side Effects
Tools are registered when their module is imported via the `@tool` decorator, which adds to `bub.tools.REGISTRY` at import time. A plugin package MUST import its tool modules (e.g., `from . import tools`) in its plugin initialization for the tools to be available. Simply having the tool file in the package is not enough.

**References:** Fact 9, Fact 11

### Claim 7: A Complete People Skill Package Would Need Both Mechanisms
A distributed "people skill" Python package should include:
1. A `skills/people/SKILL.md` for the knowledge/workflow guidance (discovered automatically)
2. A Python plugin module that imports tool modules (for custom people-management tools)
3. An entry point in `pyproject.toml` pointing to the plugin instance
4. Optionally, `@hookimpl` for `system_prompt` to inject people-specific context

The markdown skill handles "how to maintain the contact list" while the Python plugin could add tools like "search contacts by tag" or "remind me about follow-ups."

**References:** Fact 3, Fact 4, Fact 9, Fact 11, Fact 12
