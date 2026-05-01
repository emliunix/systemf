"""Notification channel: internal async message queue for background events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import ClassVar

from loguru import logger
from republic import StreamEvent

from bub.channels.base import Channel
from bub.channels.message import ChannelMessage
from bub.types import MessageHandler


class NotificationChannel(Channel):
    """Internal async message queue for background events.
    
    Async tasks can post notifications via `post_notification()` which get
    delivered as inbound messages to the main agent through the framework.
    """

    name: ClassVar[str] = "notification"
    
    # Session ID prefix for all notification messages
    SESSION_PREFIX = "notification"
    DEFAULT_CHAT_ID = "internal"

    def __init__(self, on_receive: MessageHandler) -> None:
        self._on_receive = on_receive
        self._queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    async def post_notification(
        self, 
        content: str, 
        *,
        chat_id: str = DEFAULT_CHAT_ID,
        context: dict | None = None,
    ) -> None:
        """Post a notification to be delivered to the main agent.
        
        This is the entry point for async events/tools to send notifications.
        """
        message = ChannelMessage(
            session_id=f"{self.SESSION_PREFIX}:{chat_id}",
            channel=self.name,
            chat_id=chat_id,
            content=content,
            kind="normal",
            context=context or {},
        )
        await self._queue.put(message)
        logger.debug(f"notification.queued content={content!r}")

    async def start(self, stop_event: asyncio.Event) -> None:
        """Start the notification delivery loop."""
        self._stop_event = stop_event
        self._task = asyncio.create_task(self._delivery_loop())
        logger.info("notification.channel.started")

    async def stop(self) -> None:
        """Stop the notification channel."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("notification.channel.stopped")

    async def _delivery_loop(self) -> None:
        """Background task that delivers queued notifications."""
        while self._stop_event is None or not self._stop_event.is_set():
            try:
                # Wait for next notification with timeout to check stop_event
                message = await asyncio.wait_for(
                    self._queue.get(), 
                    timeout=0.5
                )
            except asyncio.TimeoutError:
                continue
            
            try:
                await self._on_receive(message)
                logger.info(f"notification.delivered content={message.content!r}")
            except Exception:
                logger.exception("notification.delivery_failed")

    async def send(self, message: ChannelMessage) -> None:
        """Notification channel doesn't send outbound messages."""
        pass

    def stream_events(
        self, message: ChannelMessage, stream: AsyncIterable[StreamEvent]
    ) -> AsyncIterable[StreamEvent]:
        """Notification channel doesn't stream."""
        return stream
