"""All-in-one channel demo: chat and general events share one session."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import Any, ClassVar

from loguru import logger
from republic import StreamEvent

from bub.channels.base import Channel
from bub.channels.message import ChannelMessage
from bub.types import MessageHandler


class AllInOneChannel(Channel):
    """Internal demo channel that accepts both chat and event traffic.

    The key point is that chat messages and non-chat notifications can share the
    same `session_id`, which means they follow the same Bub session/tape path.
    """

    name: ClassVar[str] = "allinone"
    DEFAULT_CHAT_ID = "default"

    def __init__(self, on_receive: MessageHandler) -> None:
        self._on_receive = on_receive
        self._queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @staticmethod
    def session_id_for(chat_id: str) -> str:
        """Derive the shared session key for this logical conversation."""
        return f"{AllInOneChannel.name}:{chat_id}"

    async def post_chat(
        self,
        content: str,
        *,
        chat_id: str = DEFAULT_CHAT_ID,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue a chat-style inbound message."""
        await self._queue.put(
            ChannelMessage(
                session_id=self.session_id_for(chat_id),
                channel=self.name,
                chat_id=chat_id,
                content=content,
                kind="normal",
                context=context or {},
            )
        )
        logger.debug("allinone.chat.queued chat_id={} content={!r}", chat_id, content)

    async def post_event(
        self,
        event_name: str,
        payload: Any,
        *,
        chat_id: str = DEFAULT_CHAT_ID,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue a non-chat event into the same shared session."""
        event_context = dict(context or {})
        event_context.setdefault("event_name", event_name)
        event_context.setdefault("event_payload", payload)
        await self._queue.put(
            ChannelMessage(
                session_id=self.session_id_for(chat_id),
                channel=self.name,
                chat_id=chat_id,
                content=f"[{event_name}] {payload}",
                kind="normal",
                context=event_context,
            )
        )
        logger.debug("allinone.event.queued chat_id={} event_name={!r}", chat_id, event_name)

    async def start(self, stop_event: asyncio.Event) -> None:
        self._stop_event = stop_event
        self._task = asyncio.create_task(self._delivery_loop())
        logger.info("allinone.channel.started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("allinone.channel.stopped")

    async def _delivery_loop(self) -> None:
        while self._stop_event is None or not self._stop_event.is_set():
            try:
                message = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            try:
                await self._on_receive(message)
                logger.info(
                    "allinone.delivered session_id={} content={!r}",
                    message.session_id,
                    message.content,
                )
            except Exception:
                logger.exception("allinone.delivery_failed")

    async def send(self, message: ChannelMessage) -> None:
        """Demo outbound sink for replies emitted back to the same channel."""
        logger.info(
            "allinone.outbound session_id={} chat_id={} content={!r}",
            message.session_id,
            message.chat_id,
            message.content,
        )

    def stream_events(
        self, message: ChannelMessage, stream: AsyncIterable[StreamEvent]
    ) -> AsyncIterable[StreamEvent]:
        return stream
