import pytest
from pydantic import ValidationError

from bub_events.message import EventMessage


def test_event_message_defaults():
    msg = EventMessage(content="hello")
    assert msg.content == "hello"
    assert msg.chat_id == "default"
    assert msg.sender == "unknown"
    assert msg.topic == ""
    assert msg.meta == {}
    assert msg.kind == "normal"


def test_event_message_custom_values():
    msg = EventMessage(
        content="test",
        chat_id="chat_456",
        sender="cron",
        topic="disk-alert",
        meta={"job_id": "abc"},
        kind="command",
    )
    assert msg.chat_id == "chat_456"
    assert msg.sender == "cron"
    assert msg.topic == "disk-alert"
    assert msg.meta == {"job_id": "abc"}
    assert msg.kind == "command"


def test_event_message_missing_content():
    with pytest.raises(ValidationError):
        EventMessage()


def test_event_message_topic_validation():
    """Topic must contain only alphanumeric, hyphens, underscores."""
    # Valid topics
    assert EventMessage(content="x", topic="abc").topic == "abc"
    assert EventMessage(content="x", topic="abc-123").topic == "abc-123"
    assert EventMessage(content="x", topic="abc_123").topic == "abc_123"

    # Invalid topics
    with pytest.raises(ValidationError):
        EventMessage(content="x", topic="../etc/passwd")
    with pytest.raises(ValidationError):
        EventMessage(content="x", topic="foo bar")
    with pytest.raises(ValidationError):
        EventMessage(content="x", topic="foo@bar")
    with pytest.raises(ValidationError):
        EventMessage(content="x", topic="foo/bar")
