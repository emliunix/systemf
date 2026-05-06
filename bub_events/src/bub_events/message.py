from typing import Any

from pydantic import BaseModel, Field, field_validator


class EventMessage(BaseModel):
    content: str = Field(..., description="Message content or command")
    chat_id: str = Field("default", description="Chat identifier")
    sender: str = Field("unknown", description="Event sender provenance (acts as event type)")
    topic: str = Field("", description="Topic identifier for loading documentation")
    meta: dict[str, Any] = Field(default_factory=dict, description="Extra metadata")
    kind: str = Field("normal", description="Message kind")

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        if v and not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Topic must contain only alphanumeric characters, hyphens, and underscores"
            )
        return v
