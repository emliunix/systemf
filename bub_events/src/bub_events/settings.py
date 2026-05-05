from pydantic import Field
from pydantic_settings import SettingsConfigDict

from bub.configure import Settings


class EventsSettings(Settings):
    model_config = SettingsConfigDict(env_prefix="BUB_EVENTS_", extra="ignore")

    host: str = Field(default="127.0.0.1", description="Bind address")
    port: int = Field(default=9123, description="Listen port")
    auth_token: str | None = Field(default=None, description="Optional Bearer token for authentication")
    response_timeout: float = Field(
        default=30.0, gt=0, description="Seconds to wait for outbound response"
    )
