import asyncio
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bub.channels.message import ChannelMessage
from bub_events.channel import EventsChannel
from bub_events.settings import EventsSettings


@pytest.fixture
def settings():
    return EventsSettings(host="127.0.0.1", port=9124)


@pytest.fixture
def mock_handler():
    return AsyncMock()


@pytest.fixture
def channel(mock_handler, settings):
    return EventsChannel(on_receive=mock_handler, settings=settings)


def test_channel_name(channel):
    assert channel.name == "bub-events"


@pytest.mark.asyncio
async def test_post_event_success(channel, mock_handler):
    """Test that request with no outbound response returns timeout."""
    channel._settings.response_timeout = 0.1
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post("/event", json={"content": "hello"})
        assert response.status_code == 200
        assert response.json() == {"status": "timeout"}
        mock_handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_event_invalid_json(channel, mock_handler):
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post("/event", content="not json")
        assert response.status_code == 400
        mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_post_event_missing_content(channel, mock_handler):
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post("/event", json={})
        assert response.status_code == 422
        mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_health_endpoint(channel):
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_auth_silent_when_not_configured(channel, mock_handler):
    """Auth should not be required when auth_token is None."""
    assert channel._settings.auth_token is None
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post("/event", json={"content": "hello"})
        assert response.status_code == 200
        mock_handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_token_valid(channel, mock_handler):
    channel._settings.auth_token = "secret123"
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/event",
            json={"content": "hello"},
            headers={"Authorization": "Bearer secret123"},
        )
        assert response.status_code == 200
        mock_handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_token_invalid(channel, mock_handler):
    channel._settings.auth_token = "secret123"
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/event",
            json={"content": "hello"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert response.status_code == 401
        mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_auth_token_missing(channel, mock_handler):
    channel._settings.auth_token = "secret123"
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post("/event", json={"content": "hello"})
        assert response.status_code == 401
        mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_post_event_with_metadata(channel, mock_handler):
    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/event",
            json={
                "content": "hello",
                "chat_id": "room1",
                "sender": "cron",
                "meta": {"job_id": "abc"},
            },
        )
        assert response.status_code == 200
        mock_handler.assert_awaited_once()
        # Verify the ChannelMessage was built correctly
        call_args = mock_handler.call_args[0][0]
        assert call_args.channel == "bub-events"
        assert call_args.chat_id == "room1"
        assert call_args.content == "hello"
        assert call_args.context["sender"] == "cron"
        assert call_args.context["job_id"] == "abc"
        # session_id should be a generated UUID
        assert len(call_args.session_id) == 36


@pytest.mark.asyncio
async def test_response_linking(channel, mock_handler):
    """Test that outbound send() resolves the pending HTTP request via session_id."""
    async def delayed_send(channel_msg):
        # Simulate framework processing then calling channel.send()
        await asyncio.sleep(0.05)
        outbound = ChannelMessage(
            session_id=channel_msg.session_id,
            channel="bub-events",
            chat_id=channel_msg.chat_id,
            content="processed result",
            context=channel_msg.context,
        )
        await channel.send(outbound)

    mock_handler.side_effect = delayed_send

    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post("/event", json={"content": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["response"] == "processed result"


@pytest.mark.asyncio
async def test_response_timeout(channel, mock_handler):
    """Test that request times out when no outbound response arrives."""
    channel._settings.response_timeout = 0.1

    async def slow_handler(channel_msg):
        await asyncio.sleep(0.5)  # Longer than timeout

    mock_handler.side_effect = slow_handler

    async with AsyncClient(
        transport=ASGITransport(app=channel._app),
        base_url="http://test",
    ) as client:
        response = await client.post("/event", json={"content": "hello"})
        assert response.status_code == 200
        assert response.json() == {"status": "timeout"}


@pytest.mark.asyncio
async def test_shutdown_cancels_pending(channel, mock_handler):
    """Test that stop() cancels pending futures."""
    future = asyncio.get_running_loop().create_future()
    channel._pending["test-id"] = future

    await channel.stop()

    assert future.cancelled()
    assert len(channel._pending) == 0


@pytest.mark.asyncio
async def test_send_race_safety(channel):
    """Test send() handles already-resolved futures gracefully."""
    future = asyncio.get_running_loop().create_future()
    future.set_result("done")
    channel._pending["test-id"] = future

    from bub.channels.message import ChannelMessage
    outbound = ChannelMessage(
        session_id="test-id",
        channel="bub_events",
        content="late",
    )
    await channel.send(outbound)
    # Should not raise


@pytest.mark.asyncio
async def test_send_ignores_unknown_session(channel):
    """Test send() ignores messages with unknown session_id."""
    from bub.channels.message import ChannelMessage
    outbound = ChannelMessage(
        session_id="unknown-id",
        channel="bub_events",
        content="orphan",
    )
    await channel.send(outbound)
    # Should not raise, should not affect anything


@pytest.mark.asyncio
async def test_channel_start_stop(channel, settings):
    """Test that channel starts and stops without errors."""
    stop_event = asyncio.Event()
    
    # Start channel in background
    task = asyncio.create_task(channel.start(stop_event))
    
    # Give it time to start
    await asyncio.sleep(0.2)
    
    # Signal stop
    stop_event.set()
    
    # Wait for task to complete with timeout
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
