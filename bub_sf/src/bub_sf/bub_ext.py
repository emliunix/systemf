from dataclasses import dataclass
import uuid

from os import path
from typing import Any, cast, override
from collections.abc import Callable, Generator

from bub.builtin.agent import Agent
from bub.builtin.tape import get_tape_name
from bub.framework import BubFramework
from bub_sf.store.fork_store import SQLiteForkTapeStore
from republic.core.results import AsyncStreamEvents
from systemf.elab3 import builtins as bi
from systemf.elab3.pp_tything import pp_tything
from systemf.elab3.val_pp import pp_val
from systemf.elab3.types.protocols import Ext, REPLSessionProto, Synthesizer
from systemf.elab3.types.ty import LitString, Name, Ty, TyConApp, TyForall, TyFun, TyString
from systemf.elab3.types.tything import AnId
from systemf.elab3.types.val import VAsync, VData, VLit, VPartial, VPrim, Val


class BubExt(Ext):
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

    @override
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        arg_tys, res_ty = split_fun(thing.id.ty)

        async def _fork_tape(args: list[Val]) -> Val:
            tape_name, fork_name = _prim_val(args[0]), _maybe_val(_str_val, args[1])
            fork_name = fork_name or f"{tape_name}/fork_{uuid.uuid4().hex[:8]}"
            await self.store.fork_tape(tape_name, fork_name)
            return VPrim(fork_name)

        match name.surface:
            case "current_tape":
                return VPartial.create(name.surface, len(arg_tys), lambda _: VPrim(get_tape_name(session.state)))
            case "fork_tape":
                return VPartial.create(name.surface, len(arg_tys), lambda vals: VAsync(_fork_tape(vals)))
            case _:
                return None


class LLMOps(Synthesizer):
    @override
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        # handles only prim_ops with LLM pragma
        if thing.metas is None or thing.metas.pragma.get("LLM") is None:
            return None

        arg_tys, res_ty = split_fun(thing.id.ty)
        match_res = _match_llm_funty(thing.id.ty, session)

        async def _fun(args: list[Val]) -> Val:
            # NOTE: temp/ prefix suppress merge_back
            # NOTE: tape is either temp or explicitly speicfied in args
            tape_name = _tape_name(match_res, args) or "temp/unknown"
            
            # match_res, thing.metas.arg_docs), match_res.arg_tys
            arg_vals, arg_tys, arg_docs = (
                [args[i] for i in match_res.arg_idxs], 
                match_res.arg_tys,
                [thing.metas.arg_docs[i] for i in match_res.arg_idxs]
                if thing.metas
                else [None] * len(match_res.arg_idxs),
            )
            res_ty = match_res.res_ty
            
            s2 = session.fork()
            s2.state.update({
                **session.state,
                "session_id": f"{tape_name}/sf_{uuid.uuid4().hex[:8]}",
                "sf_session": s2,
                "tape_name": tape_name,
            })

            # setup forked REPL
            s2.add_args(list((f"arg{i}", v, ty) for i, (ty, v) in enumerate(zip(arg_tys, arg_vals))))
            res: list[Val | None] = [None]
            s2.add_return(res, res_ty)

            # if res_ty is LLM
            if match_res.is_llm_res:
                prompt = "\n".join([
                    _pp_nonfunc_val(s2, f"arg{i}", v, ty)
                    for i, (v, ty) in enumerate(zip(arg_vals, arg_tys))
                ])
                return VPrim([run_agent_with_repl_and_stream(s2, prompt)])
            else:
                func_prompt = _build_func_prompt(name, list(enumerate(arg_tys)), res_ty)
                _ = await run_agent_with_repl(s2, func_prompt)
                # return captured value, discard agent output
                if res[0] is None:
                    raise Exception("Expected return value to be set by test_prim body")
                return res[0]
        return VPartial.create(name.surface, len(arg_tys), lambda vals: VAsync(_fun(vals)))


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


async def run_agent_with_repl(repl: REPLSessionProto, prompt: str) -> str:
    """Run a task with sub-agent using specific model and session."""

    agent = _get_agent(repl.state)
    tape_name = get_tape_name(repl.state)
    output = ""
    async for event in await agent.run_stream(
        tape_name=tape_name,
        prompt=prompt,
        state=repl.state,
    ):
        if event.kind == "error":
            output += f"[Error: {event.data.get('message', 'unknown error')}]"
        elif event.kind == "text":
            output += str(event.data.get("delta", ""))
    return output


async def run_agent_with_repl_and_stream(repl: REPLSessionProto, prompt: str) -> AsyncStreamEvents:
    """Run a task with sub-agent using specific model and session, and stream the output."""
    agent = _get_agent(repl.state)
    tape_name = get_tape_name(repl.state)
    return await agent.run_stream(
        tape_name=tape_name,
        prompt=prompt,
        state=repl.state,
    )


def _build_func_prompt(name: Name, args: list[tuple[int, Ty]], res_ty: Ty) -> str:
    arg_strs = [
        f"""<arg name="arg{i}" type="{arg_ty}" />"""
        for i, arg_ty in args
    ]
    return_info = f"""<return type="{res_ty}" />""" if not _is_unit(res_ty) else ""
    return f"""
<function mod="{name.mod}" source="{name.loc}" name="{name.surface}">
<args>
{'\n'.join(arg_strs)}
</args>
{return_info}
</function>
"""


def _pp_nonfunc_val(session: REPLSessionProto, name: str, val: Val, ty: Ty) -> str:
    # for non-function types, we can just pretty print the value
    match ty, val:
        case TyString(), VLit(LitString()):
            return val.lit.v
        case _:
            return f"{name} :: {ty} = {pp_val(session, val, ty)}"


def _match_llm_ty(ty: Ty, session: REPLSessionProto) -> Ty | None:
    # matches types of the form `LLM a` for some `a`
    match ty:
        case TyConApp(name=name, args=[inner_ty]) if name == "LLM":
            return inner_ty
        case _:
            return None


def _match_tape_ty(ty: Ty, session: REPLSessionProto) -> bool:
    # matches types of the form `Tape` or `Tape a` for some `a`
    match ty:
        case TyConApp(name=name, args=[]) if name == "Tape":
            return True
        case _:
            return False

@dataclass
class MatchLLMResult:
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
    if (inner_res := _match_llm_ty(raw_res_ty, session)) is not None:
        is_llm_res = True
        res_ty = inner_res
    return MatchLLMResult(
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
