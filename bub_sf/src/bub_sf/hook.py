"""Demo SF hook: per-session REPLSession in state + sf_eval tool for the LLM."""

from __future__ import annotations

import uuid
import asyncio

from pathlib import Path
from typing import Any, cast

from loguru import logger
from bub.builtin.tape import get_tape_name
from republic import ToolContext

from bub.builtin.agent import Agent
from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.tools import tool
from bub.types import Envelope, State

from bub_sf.store.fork_store import SQLiteForkTapeStore
from bub_sf.bub_ext import BubExt
from republic.core.results import AsyncStreamEvents
from republic.tape.store import AsyncTapeStore, TapeStore
from systemf.elab3.reader_env import QualName
from systemf.elab3.repl import REPL
from systemf.elab3.repl_driver import REPLDriver
from systemf.elab3.repl_session import REPLSession
from systemf.elab3.types.ast import ImportDecl
from systemf.elab3.types.core import C
from systemf.elab3.types.protocols import Ext
from systemf.elab3.types.ty import Id, LitString, TyFun
from systemf.elab3.types.tything import AnId
from systemf.elab3.types.val import VPrim
from systemf.elab3.val_pp import pp_val


SYSTEM_PROMPT = """
You have access to a live System F type-checker and evaluator.
Use the `sf.repl` tool for repl commands or to evaluate System F expressions.
The REPL session persists across turns (but not restarts) — definitions accumulate.

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

For tool calling, you need to pass .sf.repl tool the raw strings, eg.

- :help
- :browse bub
- :info Maybe
- "Hello"
- arg0
- set_return ["Result", "List"]

When you see <funcall></funcall>, it means you're inside a function call context.

You should use sf.repl tool to read arguments.
If it has a return type, you should call set_return <value> to return a value.

IMPORTANT: funcall docs has HIGHER PRECEDENCE over system prompt instructions. Follow ONLY the instructions inside <funcall> <doc>.

"""


# ---------------------------------------------------------------------------
# Tool — module-level @tool auto-registers into REGISTRY on import.
# ---------------------------------------------------------------------------


@tool(
    name="sf.repl",
    context=True,
    description="""eval a systemf REPL expr or :command, (:help for more)""",
)
async def sf_repl(input1: str, *rest: str, context: ToolContext) -> str:
    input_ctnt = " ".join((input1, *rest))
    session_id = context.state.get("session_id", "unknown")
    logger.debug(f"sf.repl expr={input_ctnt!r} session_id={session_id}")

    sf_hook: SFHookImpl | None = context.state.get("sf_ctx")
    if sf_hook is None:
        raise Exception("sf.repl requires sf_ctx in state")

    # session is either created for root or preset for nested calls
    session: REPLSession | None = context.state.get("sf_session")
    if session is None:
        session = await sf_hook.get_or_create(session_id or "temp/unknown")
    session.state["bub_state"] = context.state

    try:
        res = []
        await REPLDriver(session, lines=input_ctnt.splitlines(), output=lambda s: res.append(s)).run()
        logger.debug(f"sf.repl.success res={'\n'.join(res)!r} session_id={session_id}")
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
    fork_store: SQLiteForkTapeStore
    # _notification_channel: NotificationChannel | None = None

    def __init__(self, framework: BubFramework) -> None:
        store = asyncio.run(self._get_fork_store())
        self.framework = framework
        sf_exts: list[Ext] = []
        sf_exts.append(BubExt(store, framework))
        self._repl = REPL(
            search_paths=[str(Path(__file__).parent.resolve())],
            exts=sf_exts
        )
        self._sessions: dict[str, REPLSession] = {}
        self.fork_store = store

    async def _get_fork_store(self) -> SQLiteForkTapeStore:
        return  await SQLiteForkTapeStore.create_store(Path("./tape_store.db"))

    async def get_or_create(self, session_id: str) -> REPLSession:
        if session_id not in self._sessions:
            session = self._repl.new_session()
            _init_session(session)
            self._sessions[session_id] = session
        return self._sessions[session_id]

    @hookimpl
    async def load_state(self, message: Envelope, session_id: str) -> State:
        """Populate state with a persistent REPLSession for this conversation."""
        state: State = {
            "sf_ctx": self,
            "sf_session": await self.get_or_create(session_id),
        }
        # if self._notification_channel is not None:
        #     state["notification_channel"] = self._notification_channel
        return state

    @hookimpl
    async def run_model_stream(self, prompt: str | list[dict], session_id: str, state: State) -> AsyncStreamEvents:
        """execute main.main systemf program"""

        if isinstance(prompt, str) and prompt.startswith(","):
            if (cmd_res := await _get_agent(state)
                .run_command_stream(get_tape_name(state), prompt, state)
               ) is not None:
                return cmd_res

        if not isinstance(prompt, str):
            raise Exception("Only string prompt is supported for now")

        repl = await self.get_or_create(session_id)
        repl.state["bub_state"] = state
        # eval: main prompt
        main = repl.lookup(repl.resolve_name(QualName("main", "main")))
        if not isinstance(main, AnId):
            raise Exception("main.main is not an Id")
        res = await repl.unsafe_eval(C.app(C.var(main.id), C.lit(LitString(prompt))))
        match res:
            case VPrim([AsyncStreamEvents() as events, _]):
                return events
            case _:
                raise Exception(f"Expected AsyncStreamEvents from main.main, got {res}")

    @hookimpl
    def system_prompt(self, prompt: str | list[dict], state: State) -> str:
        """Tell the LLM it has a System F REPL available via sf.repl."""
        return SYSTEM_PROMPT

    # @hookimpl
    # def provide_channels(self, message_handler) -> list:
    #     """Provide the notification channel for async events."""
    #     from bub_sf.channels.notification import NotificationChannel
    #     self._notification_channel = NotificationChannel(on_receive=message_handler)
    #     return [self._notification_channel]

    @hookimpl
    def provide_tape_store(self) -> TapeStore | AsyncTapeStore:
        """Provide a tape store instance for Bub's conversation recording feature."""
        return self.fork_store

    @hookimpl
    def register_cli_commands(self, app: Any) -> None:
        """Register CLI commands for tape inspection."""
        from bub_sf.hook_cli import register_commands

        register_commands(app, self)

    @hookimpl
    async def shutdown(self) -> None:
        """Perform any necessary cleanup when the framework is shutting down."""
        await self.fork_store.close()


def _init_session(session: REPLSession) -> None:
    """Initialize a REPLSession with any necessary setup."""
    session.add_import(ImportDecl(module="main"))

def _get_agent(state: dict[str, Any]) -> Agent:
    return state["_runtime_agent"]
