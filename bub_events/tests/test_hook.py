import pytest
from unittest.mock import MagicMock

from bub.channels.message import ChannelMessage
from bub_events.hook import EventsHookImpl


@pytest.fixture
def hook():
    return EventsHookImpl(framework=MagicMock())


@pytest.mark.asyncio
async def test_build_prompt_returns_none_for_non_events(hook):
    """build_prompt returns None for non-bub-events channels."""
    message = ChannelMessage(
        session_id="s1",
        channel="telegram",
        content="hello",
    )
    result = await hook.build_prompt(message, session_id="s1", state={})
    assert result is None


@pytest.mark.asyncio
async def test_build_prompt_events_no_topic(hook):
    """build_prompt returns basic prompt for events without topic."""
    message = ChannelMessage(
        session_id="s1",
        channel="bub-events",
        content="disk full",
        context={"sender": "cron"},
    )
    result = await hook.build_prompt(message, session_id="s1", state={})
    assert result is not None
    assert "disk full" in result
    assert "sender=cron" in result


@pytest.mark.asyncio
async def test_build_prompt_events_with_topic_no_doc(hook, tmp_path):
    """build_prompt adds missing doc notice when topic doc doesn't exist."""
    message = ChannelMessage(
        session_id="s1",
        channel="bub-events",
        content="disk full",
        context={"sender": "cron", "topic": "disk-alert"},
    )
    state = {"_runtime_workspace": str(tmp_path)}
    result = await hook.build_prompt(message, session_id="s1", state=state)
    assert "No topic documentation found" in result
    assert "event_prompts/disk-alert.md does not exist" in result


@pytest.mark.asyncio
async def test_build_prompt_events_with_topic_doc_exists(hook, tmp_path):
    """build_prompt adds reference when topic doc exists."""
    # Create topic doc
    event_prompts = tmp_path / "event_prompts"
    event_prompts.mkdir()
    (event_prompts / "disk-alert.md").write_text("# Disk Alert Handling\n\nCheck disk usage and notify.")

    message = ChannelMessage(
        session_id="s1",
        channel="bub-events",
        content="disk full",
        context={"sender": "cron", "topic": "disk-alert"},
    )
    state = {"_runtime_workspace": str(tmp_path)}
    result = await hook.build_prompt(message, session_id="s1", state=state)
    assert "Topic documentation available at: event_prompts/disk-alert.md" in result


@pytest.mark.asyncio
async def test_build_prompt_empty_topic(hook):
    """build_prompt ignores empty topic string."""
    message = ChannelMessage(
        session_id="s1",
        channel="bub-events",
        content="hello",
        context={"topic": ""},
    )
    result = await hook.build_prompt(message, session_id="s1", state={})
    assert "Topic documentation" not in result
    assert "No topic documentation" not in result


@pytest.mark.asyncio
async def test_build_prompt_command(hook):
    """build_prompt handles command messages (starting with ,)."""
    message = ChannelMessage(
        session_id="s1",
        channel="bub-events",
        content=",status",
    )
    result = await hook.build_prompt(message, session_id="s1", state={})
    assert result == ",status"
    assert message.kind == "command"



