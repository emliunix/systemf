"""
Primitive types layout:

- Steering: asyncio.Queue[Prompt]
- Tape: str
- LLM a: [AsyncStreamEvents[TurnResult], Val]

"""
import asyncio
import uuid

from pathlib import Path
from typing import Any, TypedDict, Unpack, cast, overload, override
from collections.abc import AsyncIterator, Generator

from loguru import logger
from bub.builtin.agent import Agent
from bub.builtin.tape import get_tape_name
from bub.framework import BubFramework
from bub_sf.sf_helpers import MatchLLMResult, match_tycon_app, maybe_val, prim_val, split_fun, str_val
from republic.core.results import AsyncStreamEvents, FinalEvent, Finished, Prompt, StreamEvent, ToolCallNeeded, TurnResult

from bub_sf.store.fork_store import SQLiteForkTapeStore
from republic.tape.entries import TapeEntry
from systemf.elab3 import builtins as bi
from systemf.elab3.repl_session import mk_funcall_by_name, mk_funcall_unsafe_fun
from systemf.elab3.val_pp import pp_val
from systemf.elab3.types.protocols import Ext, REPLSessionProto, Synthesizer
from systemf.elab3.types.ty import LitString, Name, Ty, TyConApp, TyString
from systemf.elab3.types.tything import AnId
from systemf.elab3.types.val import VAsync, VData, VLit, VPrim, Val
from systemf.elab3.types.vpartial import VPartial, SessionAwareFinish


class BubExt(Ext):
    store: SQLiteForkTapeStore
    framework: BubFramework

    def __init__(self, store: SQLiteForkTapeStore, framework: BubFramework) -> None:
        self.store = store
        self.framework = framework

    @property
    @override
    def name(self) -> str:
        return "bub"

    @override
    def search_paths(self) -> list[str]:
        return [str(Path(__file__).parent.resolve())]

    @override
    def synthesizers(self) -> list[dict[str, Synthesizer] | Synthesizer] | None:
        return [
            { "bub": BubOps(self.framework) },
            LLMOps()
        ]


def _current_tape(args: list[Val], session: REPLSessionProto | None) -> Val:
    if session is None:
        raise Exception("current_tape must be called with a valid session")
    return VPrim(get_tape_name(session.state["bub_state"]))


def _tape_fork(args: list[Val], session: REPLSessionProto | None) -> Val:
    agent = _get_agent(session)
    tape_name, fork_name = prim_val(args[0]), maybe_val(str_val, args[1])
    fork_name = fork_name or f"{tape_name}/fork"
    fork_name = f"{fork_name}_{uuid.uuid4().hex[:8]}"
    async def _go():
        await agent.tapes.fork_tape(tape_name, fork_name)
        return VPrim(fork_name)
    return VAsync(_go())


def _tape_make(args: list[Val], session: REPLSessionProto | None) -> Val:
    agent = _get_agent(session)
    parent_tape, name = maybe_val(prim_val, args[0]), maybe_val(str_val, args[1])
    suffix = uuid.uuid4().hex[:8]
    if parent_tape is not None:
        tape_name = f"{parent_tape}/{name}-{suffix}"
    else:
        tape_name = f"{name}-{suffix}"
    async def _go():
        await agent.tapes.create(tape_name)
        return VPrim(tape_name)
    return VAsync(_go())


def _inferior_tape(args: list[Val], session: REPLSessionProto | None) -> Val:
    agent = _get_agent(session)
    parent_tape = prim_val(args[0])
    name = maybe_val(str_val, args[1])
    tape_name = f"{parent_tape}/{name}"
    async def _go():
        await agent.tapes.create(tape_name)
        return VPrim(tape_name)
    return VAsync(_go())


def _tape_append(args: list[Val], session: REPLSessionProto | None) -> Val:
    agent = _get_agent(session)
    tape_name = prim_val(args[0])
    role = ["user", "assistant"][cast(VData, args[1]).tag]
    content = str_val(args[2])
    message = {"role": role, "content": content}
    if role == "assistant":
        message["reasoning_content"] = ""
    entry = TapeEntry.message(message)
    async def _go():
        await agent.tapes.append_entry(tape_name, entry)
        return bi.UNIT_VAL
    return VAsync(_go())


def _tape_handoff(args: list[Val], session: REPLSessionProto | None) -> Val:
    agent = _get_agent(session)
    tape_name = prim_val(args[0])
    name = f"{maybe_val(str_val, args[1])}_{uuid.uuid4().hex[:8]}"
    async def _go():
        # TODO: add the summary parameter
        await agent.tapes.handoff(tape_name, name=name)
        return bi.UNIT_VAL
    return VAsync(_go())


def _run_tape_with_autocompaction(args: list[Val], session: REPLSessionProto | None) -> Val:
    if session is None:
        raise Exception("run_tape_with_autocompaction must be called with a valid session")
    agent = _get_agent(session)
    tape_name: str = prim_val(args[0])
    func = args[1]
    async def _go():
        info = await agent.tapes.info(tape_name)
        if info.entries_since_last_anchor > 20:
            await session.unsafe_eval(mk_funcall_by_name("bub.compact", [bi.NOTHING_VAL], session))
        return await session.unsafe_eval(mk_funcall_unsafe_fun(func, [VPrim(tape_name)]))
    return VAsync(_go())


class BubOps(Synthesizer):
    framework: BubFramework
    
    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework

    # TODO: we should refine session to TyLookup, cause get_primop is called on loading,
    # the session might be different from that of evaluting the op. so we need to restrcit
    # it to avoid misuse.
    @override
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        arg_tys, res_ty = split_fun(thing.id.ty)

        match name.surface:
            case "current_tape":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_current_tape))
            case "tape_fork":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_tape_fork))
            case "tape_make":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_tape_make))
            case "inferior_tape":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_inferior_tape))
            case "tape_append":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_tape_append))
            case "tape_handoff":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_tape_handoff))
            case "run_tape_with_autocompaction":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_run_tape_with_autocompaction))
            case _:
                return None


class LLMOps(Synthesizer):
    @override
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        # handles only prim_ops with LLM pragma
        if thing.metas is None or (llm_prag := thing.metas.pragma.get("LLM")) is None:
            return None
        
        llm_opts = [s.strip() for s in llm_prag.split(" ")]
        agent_kwargs = {}
        for opt in llm_opts:
            match opt:
                # NOTE: notools specifically means no other tools, sf.repl is fundamental
                case "notools": agent_kwargs["allowed_tools"] = ["sf.repl"]
                case "noskills": agent_kwargs["allowed_skills"] = []
                case _: pass

        match_res = MatchLLMResult.from_ty(thing.id.ty)

        async def _fun(args: list[Val], session: REPLSessionProto | None) -> Val:
            logger.info(f"LLM function call: {name.mod}.{name.surface}")
            if session is None:
                raise Exception("LLM primops must be called with a valid session")
            session_id = session.state["bub_state"]["session_id"] or "unknown"
            # NOTE: temp/ prefix suppress merge_back
            # NOTE: tape is either temp or explicitly speicfied in args
            tape_name = _tape_name(match_res, args) or f"{session_id}/temp-{uuid.uuid4().hex[:8]}"
            steering = _steering(match_res, args)

            doc = thing.metas.doc if thing.metas else None

            arg_vals, arg_tys = (
                [args[i] for i in match_res.arg_idxs], 
                match_res.arg_tys,
            )
            res_ty = match_res.res_ty

            # TODO: metas.arg_docs is misleading, res_doc is its last element
            arg_docs: list[str | None] = []
            res_doc = None
            if thing.metas:
                arg_docs.extend(thing.metas.arg_docs[:-1])
                res_doc = thing.metas.arg_docs[-1]
            else:
                arg_docs.extend([None] * len(arg_tys))
                res_doc = None
            
            s2 = session.fork()
            s2.state.update({
                **session.state,
            })
            # ensure full copy to avoid mutation backpropagation
            s2.state["bub_state"] = {
                **session.state["bub_state"],
                "sf_repl": s2,
                "tape_name": tape_name,
            }

            # setup forked REPL
            s2.add_args(list((f"arg{i}", v, ty) for i, (ty, v) in enumerate(zip(arg_tys, arg_vals))))
            res: list[Val | None] = [None]
            s2.add_return(res, res_ty)

            llm_call_args = (
                s2, tape_name, steering,
                name, doc,
                arg_vals, arg_tys, arg_docs,
                res, res_ty, res_doc
            )
            # if res_ty is LLM
            if match_res.is_llm_res:
                return await _stream_llm_call(*llm_call_args, **agent_kwargs)
            else:
                return await _direct_llm_call(*llm_call_args, **agent_kwargs)
        
        return VPartial.create(name.surface, match_res.orig_arg_num, SessionAwareFinish.from_async(_fun))


@overload
def _get_agent(state: REPLSessionProto | None) -> Agent: ...

@overload
def _get_agent(state: dict[str, Any]) -> Agent: ...

def _get_agent(state: dict[str, Any] | REPLSessionProto | None) -> Agent:
    state = cast(dict[str, Any], state.state["bub_state"] or {}) if isinstance(state, REPLSessionProto) else state
    if state is None or "_runtime_agent" not in state:
        raise RuntimeError("no runtime agent found in tool context")
    return cast(Agent, state["_runtime_agent"])


async def run_agent_with_repl(repl: REPLSessionProto, tape_name: str, prompt: str, steering: asyncio.Queue[Prompt] | None, **kwargs: Unpack[LLMCallConfig]) -> str:
    """Run a task with sub-agent using specific model and session."""
    state = repl.state["bub_state"]
    agent = _get_agent(state)
    output = await agent.run(
        tape_name=tape_name,
        prompt=prompt,
        steering=steering,
        state=state,
        **kwargs
    )
    return output


async def run_agent_with_repl_and_stream(repl: REPLSessionProto, tape_name: str, prompt: str, steering: asyncio.Queue[Prompt] | None, **kwargs: Unpack[LLMCallConfig]) -> AsyncStreamEvents:
    """Run a task with sub-agent using specific model and session, and stream the output."""
    state = repl.state["bub_state"]
    agent = _get_agent(state)
    return await agent.run_stream(
        tape_name=tape_name,
        prompt=prompt,
        steering=steering,
        state=state,
        **kwargs
    )


def _build_func_prompt(session: REPLSessionProto, name: Name, doc: str | None, args: list[tuple[str, Val, Ty, str | None]], res_ty: Ty, res_doc: str | None) -> str:
    def _build_arg(name: str, arg_val: Val,arg_ty: Ty, doc: str | None) -> Generator[str, None, None]:
        match match_tycon_app(arg_ty, "bub", "Prompt"):
            case [inner_ty]:
                yield from _build_arg_prompt(name, cast(VData, arg_val).vals[0], inner_ty, doc)
            case _:
                yield from _build_arg_plain(name, arg_ty, doc)
    def _build_arg_plain(name: str, arg_ty: Ty, doc: str | None) -> Generator[str, None, None]:
        if doc:
            yield f"""<arg name="{name}" type="{arg_ty}"><doc>{doc}</doc></arg>"""
        else:
            yield f"""<arg name="{name}" type="{arg_ty}" />"""
    def _build_arg_prompt(name: str, arg_val: Val, arg_ty: Ty, doc: str | None) -> Generator[str, None, None]:
        if doc:
            yield f"""<arg name="{name}" type="{arg_ty}"><doc>{doc}</doc>"""
            yield pp_val(session, arg_val, arg_ty)
            yield """</arg>"""
        else:
            yield f"""<arg name="{name}" type="{arg_ty}" />"""

    def _lines() -> Generator[str, None, None]:
        yield "<rules>Strictly follow the instructions in repl:task.instruction to complete the funcall</rules>"
        # NOTE: we included these attributes previously, but then LLM tries to call itself recursively
        # mod="{name.mod}" source="{name.loc}" name="{name.surface}"
        yield f"""<repl:task name="{name}">"""
        if doc:
            yield f"<instruction>{doc}</instruction>"
        if args:
            yield "<args>"
            for arg_name, arg_val, arg_ty, arg_doc in args:
                yield from _build_arg(arg_name, arg_val, arg_ty, arg_doc)
            yield "</args>"
        
        if not _is_unit(res_ty):
            if res_doc:
                yield f"""<return type="{res_ty}"><doc>{res_doc}</doc></return>"""
            else:
                yield f"""<return type="{res_ty}" />"""
            if _is_reply(res_ty):
                yield """<instruction>directly provide the final result to conclude the task (no set_return call needed)</instruction>"""
            else:
                yield """<instruction>call sf.repl "set_return <expr>" (expected output: "MkUnit :: Unit") to set the result value to conclude the task</instruction>"""
        yield "</repl:task>"
    return "\n".join(list(_lines()))


def _pp_nonfunc_val(session: REPLSessionProto, name: str, val: Val, ty: Ty, doc: str | None) -> str:
    # for non-function types, we can just pretty print the value
    match ty, val:
        case TyString(), VLit(LitString()):
            if doc:
                return f"comment: {doc}\n{val.lit.v}"
            else:
                return val.lit.v
        case _:
            if doc:
                doc_ = "\n".join([f"-- {line}" for line in doc.splitlines()])
                return f"{name} :: {ty} = {pp_val(session, val, ty)} {doc_}"
            else:
                return f"{name} :: {ty} = {pp_val(session, val, ty)}"



def _tape_name(match_res: MatchLLMResult, args: list[Val]) -> str | None:
    if match_res.tape_idx is not None:
        match args[match_res.tape_idx]:
            case VPrim(str() as name):
                return name
            case v:
                raise Exception(f"Expected tape, got: {v}")
            

def _steering(match_res: MatchLLMResult, args: list[Val]) -> asyncio.Queue[Prompt] | None:
    if match_res.steering_idx:
        return prim_val(args[match_res.steering_idx])


def _is_unit(ty: Ty) -> bool:
    match ty:
        case TyConApp(name=name, args=[]) if name == bi.BUILTIN_UNIT:
            return True
        case _:
            return False


def _is_reply(ty: Ty) -> bool:
    match ty:
        case TyConApp(name=name, args=[]) if name.surface == "Reply":
            return True
        case _:
            return False


def _mk_reply(text: str) -> Val:
    return VData(0, [VLit(LitString(text))])


def _role_val(val: Val) -> str:
    """Extract role string from Role data constructor.
    
    data Role = User | Assistant
    User      -> VData(0, []) -> "user"
    Assistant -> VData(1, []) -> "assistant"
    """
    match val:
        case VData(0, []):
            return "user"
        case VData(1, []):
            return "assistant"
        case v:
            raise Exception(f"Expected Role value, got: {v}")

def _event_text(result: TurnResult) -> str:
    match result:
        case Finished(res):
            return res.text or ""
        case ToolCallNeeded(result=res):
            return res.text or ""


def wrap_stream_for_res(stream: AsyncStreamEvents[TurnResult], res: list[Val | None]) -> AsyncStreamEvents[TurnResult]:
    """Wrap the stream to set the return value when LLM response is received."""
    async def _wrapped() -> AsyncIterator[StreamEvent[TurnResult]]:
        chunks = []
        async for event in stream:
            match event:
                case FinalEvent():
                    chunks.append(_event_text(event.result))
            yield event
        res[0] = VLit(LitString("".join(chunks)))
    return AsyncStreamEvents(_wrapped())

async def _stream_llm_call(
    session: REPLSessionProto, tape_name: str, steering: asyncio.Queue[Prompt] | None,
    name: Name, doc: str | None,
    arg_vals: list[Val], arg_tys: list[Ty], arg_docs: list[str | None],
    res: list[Val | None], res_ty: Ty, res_doc: str | None,
    **kwargs: Unpack[LLMCallConfig]
) -> Val:
    prompt = "\n".join([
        _pp_nonfunc_val(session, f"arg{i}", v, ty, doc)
        for i, (v, ty, doc) in enumerate(zip(arg_vals, arg_tys, arg_docs))
    ])
    stream = await run_agent_with_repl_and_stream(session, tape_name, prompt, steering, **kwargs)
    stream = wrap_stream_for_res(stream, res)
    # NOTE: actually it's fine, this is `LLM a`
    # but we don't provide any function like `LLM a -> a`
    return VPrim((stream, res))


async def _direct_llm_call(
    session: REPLSessionProto, tape_name: str, steering: asyncio.Queue[Prompt] | None,
    name: Name, doc: str | None,
    arg_vals: list[Val], arg_tys: list[Ty], arg_docs: list[str | None],
    res: list[Val | None], res_ty: Ty, res_doc: str | None,
    **kwargs: Unpack[LLMCallConfig]
) -> Val:
    func_prompt = _build_func_prompt(
        session, name, doc,
        list((f"arg{i}", val, ty, doc) for i, (val, ty, doc) in enumerate(zip(arg_vals, arg_tys, arg_docs))),
        res_ty, res_doc,
    )
    for i in range(3):  # retry up to 3 times
        output = await run_agent_with_repl(session, tape_name, func_prompt, steering, **kwargs)
        if res[0]:
            break
        if _is_reply(res_ty):
            res[0] = _mk_reply(output)
            break
        func_prompt = "you should call sf.repl set_return <expr> to set a proper value"
    # return captured value, discard agent output
    if res[0] is None:
        raise Exception("Expected return value to be set by test_prim body")
    return res[0]


class LLMCallConfig(TypedDict, total=False):
    allowed_tools: list[str] | None
    allowed_skills: list[str] | None
    model: str | None
