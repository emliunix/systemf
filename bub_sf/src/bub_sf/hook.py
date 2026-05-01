"""Demo SF hook: per-session REPLSession in state + sf_eval tool for the LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
import uuid

from loguru import logger
from republic import ToolContext

from bub.builtin.agent import Agent
from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.tools import tool
from bub.types import Envelope, State

from bub_sf.bub_ext import BubExt
from bub_sf.channels.notification import NotificationChannel
from systemf.elab3.repl import REPL
from systemf.elab3.repl_driver import REPLDriver
from systemf.elab3.repl_session import REPLSession
from systemf.elab3.types.protocols import Ext
from systemf.elab3.val_pp import pp_val


SYSTEM_PROMPT = """
You have access to a live System F type-checker and evaluator.
Use the `sf.repl` tool for repl commands or to evaluate System F expressions.
The REPL session persists across turns — definitions accumulate.

Examples:
>> "Hello"
"Hello" :: String
>> 1 + 1
2 :: Int
>> :import bub
bub imported
>> :browse bub
module bub
    -- | expand the input message
    {-# LLM  #-}
    prim_op test_llm :: String -- ^ the message
        -> String
>> test_llm "Hello bub!"
"Some expanded result" :: String
"""


# ---------------------------------------------------------------------------
# Tool — module-level @tool auto-registers into REGISTRY on import.
# ---------------------------------------------------------------------------


@tool(
    name="sf.repl",
    context=True,
    description="""
        Evaluate a System F expression in the current REPL session. 
        Returns the pretty-printed value and type, or an error message.
    """,
)
async def sf_repl(input1: str, *rest: str, context: ToolContext) -> str:
    input_ctnt = " ".join((input1, *rest))
    logger.debug(f"sf.repl expr={input_ctnt!r} session_id={context.state.get('session_id')}")

    sf_hook: SFHookImpl | None = context.state.get("sf_ctx")

    # session is either created for root or preset for nested calls
    session_id: str | None = context.state.get("session_id")
    session: REPLSession | None = context.state.get("sf_session")
    if session is None and sf_hook and session_id:
        session = sf_hook.get_or_create(session_id)
        # forward the whole state
        session.state.update(context.state)
        context.state["sf_session"] = session
    if session is None:
        logger.warning(f"sf.repl.no_session session_id={session_id}")
        return "Error: no REPL session attached to this conversation"

    try:
        res = []
        await REPLDriver(session, lines=input_ctnt.splitlines(), output=lambda s: res.append(s)).run()
        logger.info(f"sf.repl.success res={'\n'.join(res)!r} session_id={session_id}")
        return "\n".join(res)
    except Exception as exc:
        logger.exception(f"sf.repl.error expr={input_ctnt!r}", exc_info=exc)
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Hook implementation — register as a bub entry point:
#
#   [project.entry-points.bub]
#   sf = "bub_sf.sf_hook:SFHookImpl"
# ---------------------------------------------------------------------------


class SFHookImpl:
    """Wires a per-session REPLSession into framework state and exposes sf.repl."""

    framework: BubFramework
    _repl: REPL
    _notification_channel: NotificationChannel | None = None

    def __init__(self, framework: BubFramework) -> None:
        # The module-level @tool already ran when Python imported this module,
        # so sf.repl is already registered — no extra import needed.
        self.framework = framework
        sf_exts: list[Ext] = []
        sf_exts.append(BubExt(framework))
        self._repl = REPL(
            search_paths=[str(Path(__file__).parent.resolve())],
            exts=sf_exts
        )
        self._sessions: dict[str, REPLSession] = {}

    def get_or_create(self, session_id: str) -> REPLSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = self._repl.new_session()
        return self._sessions[session_id]

    @hookimpl
    async def load_state(self, message: Envelope, session_id: str) -> State:
        """Populate state with a persistent REPLSession for this conversation."""
        state: State = {
            "sf_ctx": self,
        }
        if self._notification_channel is not None:
            state["notification_channel"] = self._notification_channel
        return state

    @hookimpl
    def system_prompt(self, prompt: str | list[dict], state: State) -> str:
        """Tell the LLM it has a System F REPL available via sf.repl."""
        return SYSTEM_PROMPT

    @hookimpl
    def provide_channels(self, message_handler) -> list:
        """Provide the notification channel for async events."""
        from bub_sf.channels.notification import NotificationChannel
        self._notification_channel = NotificationChannel(on_receive=message_handler)
        return [self._notification_channel]
