from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bub.channels.base import Channel
from bub.envelope import content_of, field_of
from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.types import MessageHandler, State

from bub_events.channel import EventsChannel
from bub_events.settings import EventsSettings


class EventsHookImpl:
    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework
        self._settings = EventsSettings()

    @hookimpl
    def provide_channels(self, message_handler: MessageHandler) -> list[Channel]:
        return [EventsChannel(on_receive=message_handler, settings=self._settings)]

    @hookimpl
    async def build_prompt(self, message, session_id: str, state: State) -> str | list[dict] | None:
        """Build prompt for bub-events channel messages. Return None for non-events."""
        if getattr(message, "channel", None) != "bub-events":
            return None

        # Replicate builtin prompt construction
        text = content_of(message)
        if text.startswith(","):
            message.kind = "command"
            return text

        context = field_of(message, "context_str")
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        context_prefix = f"{context}\n---Date: {now}---\n" if context else ""
        prompt = f"{context_prefix}{text}"

        # Add topic documentation reference
        # Topic is validated at EventMessage construction time (alphanumeric, hyphens, underscores)
        if topic := message.context.get("topic"):
            workspace = state.get("_runtime_workspace", ".")
            topic_doc_path = Path(workspace) / "event_prompts" / f"{topic}.md"
            if topic_doc_path.exists():
                prompt = f"Topic documentation available at: event_prompts/{topic}.md\n\n{prompt}"
            else:
                prompt = f"No topic documentation found for '{topic}' (event_prompts/{topic}.md does not exist).\n\n{prompt}"

        return prompt
