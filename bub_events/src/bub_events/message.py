from typing import Any

from pydantic import BaseModel, Field


class EventMessage(BaseModel):
    content: str = Field(..., description="Message content or command")
    chat_id: str = Field("default", description="Chat identifier")
    sender: str = Field("unknown", description="Event sender provenance")
    meta: dict[str, Any] = Field(default_factory=dict, description="Extra metadata (e.g. state identifiers)")
    kind: str = Field("normal", description="Message kind")
