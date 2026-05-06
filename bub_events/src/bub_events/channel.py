from __future__ import annotations

import asyncio
import logging
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


class LoguruHandler(logging.Handler):
    """Bridge Python logging to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


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
        # Bridge FastAPI/uvicorn logging to loguru
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
            logging.getLogger(name).handlers = [LoguruHandler()]

        @self._app.middleware("http")
        async def _log_requests(request: Request, call_next) -> Any:
            logger.debug("http.request method={} path={}", request.method, request.url.path)
            response = await call_next(request)
            logger.debug("http.response status={} path={}", response.status_code, request.url.path)
            return response

        async def _verify_auth(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
            if self._settings.auth_token is None:
                return
            if credentials is None or credentials.credentials != self._settings.auth_token:
                raise HTTPException(status_code=401, detail="Invalid or missing authentication")

        @self._app.post("/event", dependencies=[Depends(_verify_auth)])
        async def _post_event(request: Request) -> dict[str, Any]:
            logger.info("http.request.inbound method=POST path=/event")
            try:
                payload = await request.json()
            except Exception:
                logger.warning("http.request.invalid_json")
                raise HTTPException(status_code=400, detail="Invalid JSON")

            try:
                msg = EventMessage.model_validate(payload)
            except ValidationError as e:
                logger.warning("http.request.validation_error errors={}", e.errors())
                raise HTTPException(status_code=422, detail=e.errors())
            except Exception as e:
                logger.warning("http.request.validation_error detail={}", str(e))
                raise HTTPException(status_code=422, detail=str(e))

            logger.info("http.request.validated content={} chat_id={} sender={}", msg.content, msg.chat_id, msg.sender)
            return await self._handle_request(msg)

        @self._app.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "healthy"}

    async def _handle_request(self, msg: EventMessage) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        logger.info("events.request.start request_id={} content={}", request_id, msg.content)

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
            logger.info("events.request.waiting request_id={} timeout={}", request_id, self._settings.response_timeout)
            response = await asyncio.wait_for(
                future, timeout=self._settings.response_timeout
            )
            logger.info("events.request.complete request_id={} response_len={}", request_id, len(response))
            return {"status": "ok", "response": response}
        except asyncio.TimeoutError:
            logger.info("events.request.timeout request_id={}", request_id)
            return {"status": "timeout"}
        except asyncio.CancelledError:
            logger.info("events.request.cancelled request_id={}", request_id)
            raise
        finally:
            self._pending.pop(request_id, None)

    async def send(self, message: ChannelMessage) -> None:
        request_id = message.session_id
        logger.info("events.send request_id={} content_len={}", request_id, len(message.content))
        if request_id in self._pending:
            future = self._pending.pop(request_id)
            try:
                future.set_result(message.content)
                logger.info("events.send.resolved request_id={}", request_id)
            except asyncio.InvalidStateError:
                logger.warning("events.send.already_resolved request_id={}", request_id)
        else:
            logger.warning("events.send.unknown_request request_id={}", request_id)

    async def start(self, stop_event: asyncio.Event) -> None:
        config = uvicorn.Config(
            self._app,
            host=self._settings.host,
            port=self._settings.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        # Start server in background and return immediately
        # Don't block on stop_event - ChannelManager handles shutdown via stop()
        asyncio.create_task(self._server.serve())

        # Wait until server is ready
        while not self._server.started:
            await asyncio.sleep(0.01)

        logger.info("EventsChannel started on {}:{}", self._settings.host, self._settings.port)

    async def stop(self) -> None:
        logger.info("EventsChannel stopping pending_count={}", len(self._pending))
        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()
        if self._server is not None:
            await self._server.shutdown()
            self._server = None
            logger.info("EventsChannel stopped")
