"""Demo SF hook: per-session REPLSession in state + sf_eval tool for the LLM."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
import asyncio

from pathlib import Path
from typing import Any

from loguru import logger
from bub.builtin.tape import get_tape_name
from bub_sf.sf_helpers import MainInfo
from republic import ToolContext

from bub.builtin.agent import Agent
from bub.framework import BubFramework
from bub.hookspecs import hookimpl
from bub.tools import tool
from bub.types import Envelope, State

from bub_sf.store.fork_store import SQLiteForkTapeStore
from bub_sf.bub_ext import BubExt
from bub_sf.hook_cli import register_commands
from republic.core.results import AsyncStreamEvents, LLMResult, StreamEvent
from republic.tape.store import AsyncTapeStore
from systemf.elab3.repl import REPL
from systemf.elab3.repl_driver import REPLDriver
from systemf.elab3.repl_session import REPLSession, fun_call_tm
from systemf.elab3.types.ast import ImportDecl
from systemf.elab3.types.protocols import Ext
from systemf.elab3.types.ty import LitString
from systemf.elab3.types.val import VLit, VPrim, Val


SYSTEM_PROMPT = """
You have access to a live System F type-checker and evaluator.
Use the `sf.repl` tool for repl commands or to evaluate System F expressions.
Accumulate works by defining new types and values.

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


Some handful builtins:
```
-- module bub
-- compact the tape (replacing tape_handoff with explicity summarization)
compact (Just "what/how to compact")
-- for general compaction
compact Nothing 
```

"""


# ---------------------------------------------------------------------------
# Tool — module-level @tool auto-registers into REGISTRY on import.
# ---------------------------------------------------------------------------


@tool(
    name="sf.repl",
    context=True,
    description="""eval a systemf REPL expr or :command, (:help for more)""",
)
async def sf_repl(expr: str, *rest: str, context: ToolContext) -> str:
    input_ctnt = " ".join((expr, *rest))
    session_id = context.state.get("session_id", "unknown")
    logger.debug(f"sf.repl expr={input_ctnt!r} session_id={session_id}")

    # session is either created for root or preset for nested calls
    repl: REPLSession | None = context.state.get("sf_repl")
    if repl is None:
        raise Exception("REPL session not found")
    repl.state["bub_state"] = context.state

    try:
        res = []
        await REPLDriver(repl, lines=input_ctnt.splitlines(), output=lambda s: res.append(s)).run()
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


class TaskBase:
    lock: asyncio.Lock
    active_task: asyncio.Task | None
    active_task_token: object | None

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.active_task = None
        self.active_task_token = None

    async def ensure_task(self, task_fn: Callable[[], Coroutine[None, None, None]]) -> None:
        async with self.lock:
            task_token = object()
            self.active_task_token = task_token
            if self.active_task is None:
                async def _go_init():
                    try: 
                        await task_fn()
                    except Exception as exc:
                        logger.exception("Error in task", exc_info=exc)
                    finally:
                        async with self.lock:
                            if self.active_task_token is task_token:
                                self.active_task = None
                self.active_task = asyncio.create_task(_go_init())
            else:
                async def _go_after_task(task: asyncio.Task) -> None:
                    # all previous task is guaranteed to have handled its exception
                    await task
                    try:
                        await task_fn()
                    except Exception as exc:
                        logger.exception("Error in task", exc_info=exc)
                    finally:
                        async with self.lock:
                            if self.active_task_token is task_token:
                                self.active_task = None
                self.active_task = asyncio.create_task(_go_after_task(self.active_task))


class SessionInfo(TaskBase):
    session_id: str
    queue: asyncio.Queue[str]
    repl: REPLSession

    def __init__(self, session_id: str, repl: REPLSession) -> None:
        super().__init__()
        self.session_id = session_id
        self.queue = asyncio.Queue()
        self.repl = repl


class SFHookImpl:
    """Wires a per-session REPLSession into framework state and exposes sf.repl."""

    framework: BubFramework
    fork_store: SQLiteForkTapeStore
    _repl: REPL
    _sessions: dict[str, SessionInfo]

    def __init__(self, framework: BubFramework) -> None:
        store = asyncio.run(self._get_fork_store())
        self.framework = framework
        sf_exts: list[Ext] = []
        sf_exts.append(BubExt(store, framework))
        self._repl = REPL(
            search_paths=[str(Path(__file__).parent.resolve())],
            exts=sf_exts
        )
        self._sessions: dict[str, SessionInfo] = {}
        self.fork_store = store

    async def _get_fork_store(self) -> SQLiteForkTapeStore:
        return  await SQLiteForkTapeStore.create_store(Path("./tape_store.db"))

    def get_or_create(self, session_id: str) -> SessionInfo:
        if session_id not in self._sessions:
            repl = self._repl.new_session()
            _init_session(repl)
            self._sessions[session_id] = SessionInfo(session_id, repl)
        return self._sessions[session_id]

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
        
        session = self.get_or_create(session_id)
        state["sf_repl"] = session.repl
        session.queue.put_nowait(prompt)
        out_q = asyncio.Queue()
        await session.ensure_task(lambda: self._run_agent_session(session, state, out_q))
        # NOTE: Returning empty stream is transitional. The actual response goes
        # via tools (e.g., send_message). This old design expected streaming
        # events back through the hook return value. Should be cleaned up once
        # tool-based messaging is fully adopted.
        async def _out() -> AsyncIterator[StreamEvent[LLMResult]]:
            try:
                while True:
                    event = await out_q.get()
                    yield event
            except asyncio.QueueShutDown:
                return
        return AsyncStreamEvents(_out())

    async def _run_agent_session(self, session: SessionInfo, state: State, out_q: asyncio.Queue[StreamEvent[LLMResult]]) -> None:
        if session.queue.empty():
            return
        session.repl.state["bub_state"] = state
        # eval: main prompt
        info = MainInfo.from_session(session.repl)
        str_val = None
        q_val = None
        vals: list[tuple[int, Val]] = []
        match info.str_ty:
            case (i, _):
                prompt = await session.queue.get()
                vals.append((i, VLit(LitString(prompt))))
        match info.prompt_ty:
            case (i, _):
                vals.append((i, VPrim(session.queue)))
        vals_ = [val for _, val in sorted(vals)]
        res = await session.repl.unsafe_eval(fun_call_tm(info.main.id, vals_))
        match res:
            case VPrim([AsyncStreamEvents() as events, _]):
                try:
                    async for event in events:
                        await out_q.put(event)
                finally:
                    out_q.shutdown()
            case _:
                raise Exception(f"Expected AsyncStreamEvents from main.main, got {res}")

    @hookimpl
    def system_prompt(self, state: State) -> str:
        """Tell the LLM it has a System F REPL available via sf.repl."""
        return SYSTEM_PROMPT

    @hookimpl
    def provide_tape_store(self) -> AsyncTapeStore:
        """Provide a tape store instance for Bub's conversation recording feature."""
        return self.fork_store

    @hookimpl
    def register_cli_commands(self, app: Any) -> None:
        """Register CLI commands for tape inspection."""
        register_commands(app, self)

    @hookimpl
    async def shutdown(self) -> None:
        """Perform any necessary cleanup when the framework is shutting down."""
        await self.fork_store.close()


def _init_session(session: REPLSession) -> None:
    """Initialize a REPLSession with any necessary setup."""
    session.add_import(ImportDecl(module="main"))
    session.add_import(ImportDecl(module="bub"))

def _get_agent(state: dict[str, Any]) -> Agent:
    return state["_runtime_agent"]
