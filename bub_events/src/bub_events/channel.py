from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from loguru import logger
from pydantic import ValidationError

from bub.channels.base import Channel
from bub.channels.message import ChannelMessage
from bub.types import MessageHandler

from bub_events.message import EventMessage
from bub_events.settings import EventsSettings

security = HTTPBearer(auto_error=False)


class EventsChannel(Channel):
    name: ClassVar[str] = "bub_events"

    def __init__(self, on_receive: MessageHandler, settings: EventsSettings) -> None:
        self._on_receive = on_receive
        self._settings = settings
        self._app = FastAPI()
        self._server: uvicorn.Server | None = None
        self._pending: dict[str, asyncio.Future[str]] = {}
        self._setup_routes()

    def _setup_routes(self) -> None:
        async def _verify_auth(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
            if self._settings.auth_token is None:
                return
            if credentials is None or credentials.credentials != self._settings.auth_token:
                raise HTTPException(status_code=401, detail="Invalid or missing authentication")

        @self._app.post("/event", dependencies=[Depends(_verify_auth)])
        async def _post_event(request: Request) -> dict[str, Any]:
            try:
                payload = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON")

            try:
                msg = EventMessage.model_validate(payload)
            except ValidationError as e:
                raise HTTPException(status_code=422, detail=e.errors())
            except Exception as e:
                raise HTTPException(status_code=422, detail=str(e))

            return await self._handle_request(msg)

        @self._app.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "healthy"}

    async def _handle_request(self, msg: EventMessage) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        channel_msg = ChannelMessage(
            session_id=request_id,
            channel="bub_events",
            chat_id=msg.chat_id,
            content=msg.content,
            kind=msg.kind,
            context={"sender": msg.sender, **msg.meta},
        )

        try:
            await self._on_receive(channel_msg)
            response = await asyncio.wait_for(
                future, timeout=self._settings.response_timeout
            )
            return {"status": "ok", "response": response}
        except asyncio.TimeoutError:
            return {"status": "timeout"}
        except asyncio.CancelledError:
            raise
        finally:
            self._pending.pop(request_id, None)

    async def send(self, message: ChannelMessage) -> None:
        request_id = message.session_id
        if request_id in self._pending:
            future = self._pending.pop(request_id)
            try:
                future.set_result(message.content)
            except asyncio.InvalidStateError:
                pass

    async def start(self, stop_event: asyncio.Event) -> None:
        config = uvicorn.Config(
            self._app,
            host=self._settings.host,
            port=self._settings.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        # Start server in background
        server_task = asyncio.create_task(self._server.serve())

        # Wait until server is ready
        while not self._server.started:
            await asyncio.sleep(0.01)

        logger.info(f"EventsChannel started on {self._settings.host}:{self._settings.port}")

        # Wait for shutdown signal
        await stop_event.wait()
        await self.stop()

    async def stop(self) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()
        if self._server is not None:
            logger.info("EventsChannel stopping")
            await self._server.shutdown()
            self._server = None
