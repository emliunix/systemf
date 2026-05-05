# Exploration: Pydantic Usage in Bub

## Notes

### Note 1: Goal
Understand how Pydantic is used in the Bub framework for configuration and validation, to inform the `bub_events` channel design.

## Facts

### Fact 1: Pydantic Settings for Configuration
`bub/src/bub/configure.py` uses `pydantic_settings.BaseSettings` for configuration management.

### Fact 2: Telegram Channel Settings
`bub/src/bub/channels/telegram.py:25-39`
```python
@config(name="telegram")
class TelegramSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="BUB_TELEGRAM_", extra="ignore", env_file=".env")

    token: str = Field(default="", description="Telegram bot token.")
    allow_users: str | None = Field(default=None, description="...")
    allow_chats: str | None = Field(default=None, description="...")
    proxy: str | None = Field(default=None, description="...")
```

### Fact 3: Channel Manager Settings
`bub/src/bub/channels/manager.py:22-41`
```python
@config()
class ChannelSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="BUB_", extra="ignore", env_file=".env")

    enabled_channels: str = Field(default="all", description="...")
    debounce_seconds: float = Field(default=1.0, description="...")
    max_wait_seconds: float = Field(default=10.0, description="...")
    active_time_window: float = Field(default=60.0, description="...")
    stream_output: bool = Field(default=False, description="...")
```

### Fact 4: Tool Input Validation
`bub/src/bub/builtin/tools.py:41-65`
```python
class SearchInput(BaseModel):
    query: str = Field(..., description="The search query string.")
    limit: int = Field(20, description="Maximum number of search results to return.")
    start: str | None = Field(None, description="Optional start date...")
    end: str | None = Field(None, description="Optional end date...")
    kinds: list[str] = Field(...)

class SubAgentInput(BaseModel):
    prompt: str | list[dict] = Field(...)
    model: str | None = Field(None, description="The model to use...")
    session: str = Field(...)
    allowed_tools: list[str] | None = Field(...)
    allowed_skills: list[str] | None = Field(...)
```

### Fact 5: Settings Base Class
`bub/src/bub/configure.py` provides a `Settings` base class that wraps `BaseSettings` with environment variable loading.

## Claims

### Claim 1: Pydantic is Used Primarily for Settings and Tool Inputs
Bub uses Pydantic for:
1. **Configuration**: `Settings` subclasses with `env_prefix` for environment variable auto-loading
2. **Tool input validation**: `BaseModel` subclasses for structured tool arguments

**References:** Fact 2, Fact 3, Fact 4

### Claim 2: The `@config` Decorator Registers Settings Classes
The `@config(name="telegram")` decorator on `TelegramSettings` registers it for lookup via `ensure_config(TelegramSettings)`.

**References:** Fact 2

### Claim 3: Pydantic BaseModel is Appropriate for JSON Message Validation
For the `bub_events` channel, a `BaseModel` subclass can validate incoming JSON messages with proper field types, defaults, and validation rules.

**References:** Fact 4
