import uuid

from os import path
from typing import Any, TypedDict, Unpack, cast, override
from collections.abc import Callable, Generator
from dataclasses import dataclass

from loguru import logger
from bub.builtin.agent import Agent
from bub.builtin.tape import get_tape_name
from bub.framework import BubFramework
from republic.core.results import AsyncStreamEvents

from bub_sf.store.fork_store import SQLiteForkTapeStore
from republic.tape.entries import TapeEntry
from systemf.elab3 import builtins as bi
from systemf.elab3.val_pp import pp_val
from systemf.elab3.types.protocols import Ext, REPLSessionProto, Synthesizer
from systemf.elab3.types.ty import LitString, Name, Ty, TyConApp, TyForall, TyFun, TyString
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
        return [path.basename(__file__)]

    @override
    def synthesizers(self) -> list[dict[str, Synthesizer] | Synthesizer] | None:
        return [
            { "bub": BubOps(self.store) },
            LLMOps()
        ]


class BubOps(Synthesizer):
    store: SQLiteForkTapeStore
    
    def __init__(self, store: SQLiteForkTapeStore) -> None:
        self.store = store

    # TODO: we should refine session to TyLookup, cause get_primop is called on loading,
    # the session might be different from that of evaluting the op. so we need to restrcit
    # it to avoid misuse.
    @override
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        arg_tys, res_ty = split_fun(thing.id.ty)

        def _currnent_tape(args: list[Val], session: REPLSessionProto | None) -> Val:
            if session is None:
                raise Exception("current_tape must be called with a valid session")
            return VPrim(get_tape_name(session.state["bub_state"]))

        async def _fork_tape(args: list[Val]) -> Val:
            tape_name, fork_name = _prim_val(args[0]), _maybe_val(_str_val, args[1])
            fork_name = fork_name or f"{tape_name}/fork_{uuid.uuid4().hex[:8]}"
            await self.store.fork_tape(tape_name, fork_name)
            return VPrim(fork_name)

        async def _make_tape(args: list[Val]) -> Val:
            parent_tape, name = _maybe_val(_prim_val, args[0]), _str_val(args[1])
            suffix = uuid.uuid4().hex[:8]
            if parent_tape is not None:
                tape_name = f"{parent_tape}/{name}-{suffix}"
            else:
                tape_name = f"{name}-{suffix}"
            await self.store.create(tape_name)
            return VPrim(tape_name)

        async def _append_message(args: list[Val]) -> Val:
            tape_name, content = _prim_val(args[0]), _str_val(args[1])
            entry = TapeEntry.message({"role": "user", "content": content})
            await self.store.append(tape_name, entry)
            return bi.UNIT_VAL

        match name.surface:
            case "current_tape":
                return VPartial.create(name.surface, len(arg_tys), SessionAwareFinish(_currnent_tape))
            case "fork_tape":
                return VPartial.create(name.surface, len(arg_tys), lambda vals: VAsync(_fork_tape(vals)))
            case "make_tape":
                return VPartial.create(name.surface, len(arg_tys), lambda vals: VAsync(_make_tape(vals)))
            case "append_message":
                return VPartial.create(name.surface, len(arg_tys), lambda vals: VAsync(_append_message(vals)))
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
                case "notools": agent_kwargs["allowed_tools"] = ["sf.repl"]
                case "noskills": agent_kwargs["allowed_skills"] = []
                case _: pass

        match_res = _match_llm_funty(thing.id.ty, session)

        async def _fun(args: list[Val], session: REPLSessionProto | None) -> Val:
            logger.info(f"LLM function call: {name.mod}.{name.surface}")
            if session is None:
                raise Exception("LLM primops must be called with a valid session")
            session_id = session.state["bub_state"]["session_id"] or "unknown"
            # NOTE: temp/ prefix suppress merge_back
            # NOTE: tape is either temp or explicitly speicfied in args
            tape_name = _tape_name(match_res, args) or f"{session_id}/temp-{uuid.uuid4().hex[:8]}"

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
                "sf_session": s2,
                "tape_name": tape_name,
            }

            # setup forked REPL
            s2.add_args(list((f"arg{i}", v, ty) for i, (ty, v) in enumerate(zip(arg_tys, arg_vals))))
            res: list[Val | None] = [None]
            s2.add_return(res, res_ty)

            # if res_ty is LLM
            llm_call_args = (
                s2, tape_name,
                name, doc,
                arg_vals, arg_tys, arg_docs,
                res, res_ty, res_doc
            )
            if match_res.is_llm_res:
                return await _stream_llm_call(*llm_call_args, **agent_kwargs)
            else:
                return await _direct_llm_call(*llm_call_args, **agent_kwargs)
        
        return VPartial.create(name.surface, match_res.orig_arg_num, SessionAwareFinish.from_async(_fun))


def split_fun(ty: Ty) -> tuple[list[Ty], Ty]:
    def _go(ty: Ty) -> Generator[Ty, None, None]:
        match ty:
            case TyFun(arg, res):
                yield arg
                yield from _go(res)
            case TyForall(_, body):
                yield from _go(body)
            case _:
                yield ty
    tys = list(_go(ty))
    return tys[:-1], tys[-1]


def _get_agent(state: dict[str, Any]) -> Agent:
    if "_runtime_agent" not in state:
        raise RuntimeError("no runtime agent found in tool context")
    return cast(Agent, state["_runtime_agent"])


async def run_agent_with_repl(repl: REPLSessionProto, tape_name: str, prompt: str, **kwargs: Unpack[LLMCallConfig]) -> str:
    """Run a task with sub-agent using specific model and session."""
    state = repl.state["bub_state"]

    agent = _get_agent(state)
    output = await agent.run(
        tape_name=tape_name,
        prompt=prompt,
        state=state,
        **kwargs
    )
    return output


async def run_agent_with_repl_and_stream(repl: REPLSessionProto, tape_name: str, prompt: str, **kwargs: Unpack[LLMCallConfig]) -> AsyncStreamEvents:
    """Run a task with sub-agent using specific model and session, and stream the output."""
    state = repl.state["bub_state"]
    agent = _get_agent(state)
    return await agent.run_stream(
        tape_name=tape_name,
        prompt=prompt,
        state=state,
        **kwargs
    )


def _build_func_prompt(name: Name, doc: str | None, args: list[tuple[str, Ty, str | None]], res_ty: Ty, res_doc: str | None) -> str:
    def _build_arg(name: str, arg_ty: Ty, doc: str | None) -> str:
        if doc:
            return f"""<arg name="{name}" type="{arg_ty}"><doc>{doc}</doc></arg>"""
        else:
            return f"""<arg name="{name}" type="{arg_ty}" />"""

    def _lines() -> Generator[str, None, None]:
        yield "<rules>Strictly follow the instructions funcall doc to complete the funcall</rules>"
        yield f"""<funcall mod="{name.mod}" source="{name.loc}" name="{name.surface}">"""
        if doc:
            yield f"<doc>{doc}</doc>"
        if args:
            yield "<args>"
            for arg_name, arg_ty, arg_doc in args:
                yield _build_arg(arg_name, arg_ty, arg_doc)
            yield "</args>"
        if res_doc:
            yield f"""<return type="{res_ty}"><doc>{res_doc}</doc></return>"""
        elif not _is_unit(res_ty):
            yield f"""<return type="{res_ty}" />"""
        yield "</funcall>"
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


def _match_llm_ty(ty: Ty, session: REPLSessionProto) -> Ty | None:
    # matches types of the form `LLM a` for some `a`
    match ty:
        case TyConApp(name=name, args=[inner_ty]) if name.surface == "LLM":
            return inner_ty
        case _:
            return None


def _match_tape_ty(ty: Ty, session: REPLSessionProto) -> bool:
    # matches types of the form `Tape` or `Tape a` for some `a`
    match ty:
        case TyConApp(name=name, args=[]) if name.surface == "Tape":
            return True
        case _:
            return False


@dataclass
class MatchLLMResult:
    orig_arg_num: int
    tape_idx: int | None
    arg_tys: list[Ty]
    arg_idxs: list[int]
    is_llm_res: bool
    res_ty: Ty


def _match_llm_funty(ty: Ty, session: REPLSessionProto) -> MatchLLMResult:
    raw_arg_tys, raw_res_ty = split_fun(ty)
    arg_tys = []
    arg_idxs = []
    is_llm_res = False
    res_ty = raw_res_ty
    tape_idx = None
    for i, arg_ty in enumerate(raw_arg_tys):
        if _match_tape_ty(arg_ty, session):
            tape_idx = i
        else:
            arg_idxs.append(i)
            arg_tys.append(arg_ty)
    if (inner_res := _match_llm_ty(res_ty, session)) is not None:
        is_llm_res = True
        res_ty = inner_res
    return MatchLLMResult(
        orig_arg_num=len(raw_arg_tys),
        tape_idx=tape_idx,
        arg_tys=arg_tys,
        arg_idxs=arg_idxs,
        is_llm_res=is_llm_res,
        res_ty=res_ty,
    )


def _tape_name(match_res: MatchLLMResult, args: list[Val]) -> str | None:
    if match_res.tape_idx is not None:
        match args[match_res.tape_idx]:
            case VPrim(str() as name):
                return name
            case v:
                raise Exception(f"Expected tape, got: {v}")


def _is_unit(ty: Ty) -> bool:
    match ty:
        case TyConApp(name=name, args=[]) if name == bi.BUILTIN_UNIT:
            return True
        case _:
            return False


def _prim_val(val: Val) -> Any:
    match val:
        case VPrim(s):
            return s
        case v:
            raise Exception(f"Expected primitive string value, got: {v}")
        

def _str_val(val: Val) -> str:
    match val:
        case VLit(LitString(s)):
            return s
        case v:
            raise Exception(f"Expected literal string value, got: {v}")


def _maybe_val(inside: Callable[[Val], Any], val: Val) -> Any | None:
    match val:
        case VData(0, []):
            return None
        case VData(1, [inner]):
            return inside(inner)
        case v:
            raise Exception(f"Expected Maybe value, got: {v}")


async def _stream_llm_call(
    session: REPLSessionProto, tape_name: str,
    name: Name, doc: str | None,
    arg_vals: list[Val], arg_tys: list[Ty], arg_docs: list[str | None],
    res: list[Val | None], res_ty: Ty, res_doc: str | None,
    **kwargs: Unpack[LLMCallConfig]
) -> Val:
    prompt = "\n".join([
        _pp_nonfunc_val(session, f"arg{i}", v, ty, doc)
        for i, (v, ty, doc) in enumerate(zip(arg_vals, arg_tys, arg_docs))
    ])
    return VPrim((await run_agent_with_repl_and_stream(session, tape_name, prompt, **kwargs), res))


async def _direct_llm_call(
    session: REPLSessionProto, tape_name: str,
    name: Name, doc: str | None,
    arg_vals: list[Val], arg_tys: list[Ty], arg_docs: list[str | None],
    res: list[Val | None], res_ty: Ty, res_doc: str | None,
    **kwargs: Unpack[LLMCallConfig]
) -> Val:
    func_prompt = _build_func_prompt(
        name, doc,
        list((f"arg{i}", ty, doc) for i, (ty, doc) in enumerate(zip(arg_tys, arg_docs))),
        res_ty, res_doc,
    )
    _ = await run_agent_with_repl(session, tape_name, func_prompt, **kwargs)
    # return captured value, discard agent output
    if res[0] is None:
        raise Exception("Expected return value to be set by test_prim body")
    return res[0]


class LLMCallConfig(TypedDict, total=False):
    allowed_tools: list[str] | None
    allowed_skills: list[str] | None
    model: str | None
