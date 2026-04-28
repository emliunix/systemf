from collections.abc import Generator
from typing import Any, cast, override
from os import path
import uuid


from bub.builtin.agent import Agent
from bub.framework import BubFramework
from systemf.elab3 import builtins as bi
from systemf.elab3.pp_tything import pp_tything
from systemf.elab3.val_pp import pp_val
from systemf.elab3.types.protocols import Ext, REPLSessionProto, Synthesizer
from systemf.elab3.types.ty import Name, Ty, TyForall, TyFun
from systemf.elab3.types.tything import AnId
from systemf.elab3.types.val import VAsync, VPartial, Val


class BubExt(Ext):
    framework: BubFramework

    def __init__(self, framework: BubFramework) -> None:
        self.framework = framework

    @property
    @override
    def name(self) -> str:
        return "bub"

    @override
    def search_paths(self) -> list[str]:
        return [path.basename(__file__)]

    @override
    def synthesizer(self) -> dict[str, Synthesizer] | Synthesizer | None:
        return LLMOps()


class LLMOps(Synthesizer):
    @override
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        # handles only prim_ops with LLM pragma
        if thing.metas is None or thing.metas.pragma.get("LLM") is None:
            return None

        arg_tys, res_ty = split_fun(thing.id.ty)
        
        async def _fun(args: list[Val]) -> Val:
            s2 = session.fork()
            s2.state.update({
                **session.state,
                "session_id": f"temp/{uuid.uuid4().hex[:8]}",
                "sf_session": s2,
            })

            # setup forked REPL
            s2.add_args(list((f"arg{i}", v, ty) for i, (ty, v) in enumerate(zip(arg_tys, args))))
            res: list[Val | None] = [None]
            s2.add_return(res, res_ty)

            args_lines = [
                f"- arg{i} = {pp_val(s2, arg, arg_ty)}" 
                for i, (arg, arg_ty) in enumerate(zip(args, arg_tys))
            ]
            prompt = f"""
You are inside a LLM function ({name.surface}) call with a REPL session.

The function being called:

{name.mod}.{name.surface} ({name.loc})
{pp_tything(thing)}

The following arguments and set_return function available in the context:

{'\n'.join(args_lines)}\n
- set_return :: {res_ty} -> Unit

Call sf_eval("set_return <value>") to conclude your work and return a value. 

You can use the REPL session to evaluate any System F code, including using built-in functions and data types.
The REPL session has access to all previously defined modules and functions, as well as items defined by parent.
            """

            await run_agent_with_repl(s2, prompt)

            # return captured value
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
    output = ""
    async for event in await agent.run_stream(
        session_id=repl.state.get("session_id", "temp/unknown"),
        prompt=prompt,
        state=repl.state,
    ):
        if event.kind == "error":
            output += f"[Error: {event.data.get('message', 'unknown error')}]"
        elif event.kind == "text":
            output += str(event.data.get("delta", ""))
    return output
