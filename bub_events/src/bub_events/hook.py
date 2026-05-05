from __future__ import annotations

from pluggy import HookimplMarker

from bub.channels.base import Channel
from bub.framework import BubFramework
from bub.types import MessageHandler

from bub_events.channel import EventsChannel
from bub_events.settings import EventsSettings

hookimpl = HookimplMarker("bub")


class EventsHookImpl:
    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework
        self._settings = EventsSettings()

    @hookimpl
    def provide_channels(self, message_handler: MessageHandler) -> list[Channel]:
        return [EventsChannel(on_receive=message_handler, settings=self._settings)]
