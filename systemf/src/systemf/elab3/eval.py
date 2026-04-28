"""
CEK evaluator for elab3 Core.

Architecture:
- Evaluator is a strict CBV expression-driven CEK machine.
- eval_mod evaluates a topo-sorted list of bindings and returns all results.
- Variable resolution: local env -> ctx.lookup_gbl for module-level references.
- No binding-level caching. The context owns all caching and module management.
- No item types — the evaluator only sees CoreTm and Binding types.
"""

from dataclasses import dataclass
from typing import Protocol, cast

from pyrsistent import pmap

from systemf.elab3.core_extra import CoreBuilderExtra
from systemf.elab3.types.core import (
    C, CoreTm, CoreLit, CoreVar, CoreGlobalVar, CoreLam, CoreApp,
    CoreTyLam, CoreTyApp, CoreLet, CoreCase,
    NonRec, Rec,
    DataAlt, LitAlt, DefaultAlt, Alt,
)
from .types.ty import Id, Name
from .types.mod import Module
from .types.val import VAsync, Val, VLit, VClosure, VPartial, VData, Trap, Env



# =============================================================================
# Continuations
# =============================================================================

@dataclass
class Cont:
    pass


@dataclass
class Halt(Cont):
    pass


@dataclass
class Ar(Cont):
    """Evaluate the argument next, then apply."""
    arg: CoreTm
    env: Env
    k: Cont


@dataclass
class Ap(Cont):
    """Apply a closure/partial/primop to the incoming value."""
    closure: VClosure | VPartial
    k: Cont


@dataclass
class LetBind(Cont):
    """Bind the incoming value to a variable and continue with the body."""
    binder: Id
    body: CoreTm
    env: Env
    k: Cont


@dataclass
class Kases(Cont):
    """Match the incoming value against a list of alts."""
    alts: list[tuple[Alt, CoreTm]]
    scrut_var: Id
    env: Env
    k: Cont


@dataclass
class BackpatchNext(Cont):
    """
    Fill `trap` with the incoming value, then either kick off the next
    (trap, expr) pair in `rest`, or — when `rest` is empty — evaluate `body`
    in `new_env` (all traps filled by then).
    """
    trap: Trap
    rest: list[tuple[Trap, CoreTm]]
    new_env: Env
    body: CoreTm
    k: Cont


# =============================================================================
# EvalCtx protocol
# =============================================================================


class EvalCtx(Protocol):
    """Protocol for the context that resolves module-level names at runtime."""

    async def lookup_gbl(self, name: Name) -> Val: ...
    @property
    def core_extra(self) -> CoreBuilderExtra: ...


# =============================================================================
# Evaluator
# =============================================================================

type Config = tuple[CoreTm, Env, Cont]


class Evaluator:
    """Strict CBV CEK evaluator."""
    ctx: EvalCtx

    def __init__(self, ctx: EvalCtx):
        self.ctx = ctx

    # --- public API ---------------------------------------------------------

    async def eval_mod(self, mod: Module, mod_inst: dict[Name, Val]) -> dict[Name, Val]:
        """Evaluate topo-sorted bindings and return all bound values.

        Each binding is evaluated independently.  For NonRec, the expression
        result is stored under ``binder.name``.  For Rec, the whole group is
        evaluated once and all member values are extracted.

        ``mod_inst`` is mutated in-place and serves as a same-module cache:
        ``step(CoreVar)`` checks it before falling through to
        ``ctx.lookup_gbl``.
        """
        init_env = pmap({bndr.unique: v for bndr, v in mod_inst.items()})
        for binding in mod.bindings:
            match binding:
                case NonRec(binder, expr):
                    val = await self._eval_expr(expr, init_env)
                    mod_inst[binder.name] = val
                    init_env = init_env.set(binder.name.unique, val)
                case Rec([(bndr, _)]):
                    val = await self._eval_expr(CoreLet(binding, CoreVar(bndr)), init_env)
                    mod_inst[bndr.name] = val
                    init_env = init_env.set(bndr.name.unique, val)
                case Rec():
                    bndrs = [bndr for bndr, _ in binding.bindings]
                    vars = [C.var(bndr) for bndr in bndrs]
                    tup, _ = self.ctx.core_extra.mk_tuple(vars, [b.ty for b in bndrs])
                    val = await self._eval_expr(CoreLet(binding, tup), init_env) # eval once
                    # unwrap the tuple
                    for bndr in bndrs[:-1]:
                        v1, val = cast(VData, val).vals
                        mod_inst[bndr.name] = v1
                        init_env = init_env.set(bndr.name.unique, val)
                    mod_inst[bndrs[-1].name] = val
                    init_env = init_env.set(bndrs[-1].name.unique, val)
        return mod_inst

    # --- CEK machine --------------------------------------------------------

    async def _eval_expr(self, t: CoreTm, env: Env) -> Val:
        """Evaluate a CoreTm to a Val using the CEK machine."""
        cur: Config | Val = (t, env, Halt())
        while not isinstance(cur, Val):
            t1, env1, k1 = cur
            cur = await self.step(t1, env1, k1)
        return cur

    async def step(self, t: CoreTm, env: Env, k: Cont) -> Config | Val:
        match t:
            case CoreLit(value=value):
                return await self.call_continue(VLit(value), k)

            case CoreVar(id=id):
                raw = env.get(id.name.unique)
                if raw is not None:
                    match raw:
                        case Trap(v=inner) if inner is not None:
                            return await self.call_continue(inner, k)
                        case Trap():
                            raise Exception(
                                "referencing uninitialized letrec trap for " +
                                f"{id.name.surface!r} (possible non-productive recursion)"
                            )
                        case _:
                            return await self.call_continue(raw, k)
                else:
                    return await self.call_continue(await self.ctx.lookup_gbl(id.name), k)

            case CoreGlobalVar(id=id):
                return await self.step(CoreVar(id), env, k)

            case CoreLam(param=param, body=body):
                return await self.call_continue(VClosure(env, param, body), k)

            case CoreApp(fun=fun, arg=arg):
                return (fun, env, Ar(arg, env, k))

            case CoreTyLam(body=body):
                return (body, env, k)

            case CoreTyApp(fun=fun):
                return (fun, env, k)

            case CoreLet(binding=NonRec(binder=binder, expr=expr), body=body):
                return (expr, env, LetBind(binder, body, env, k))

            case CoreLet(binding=Rec(bindings=bindings), body=body):
                if not bindings:
                    return (body, env, k)

                trap_pairs: list[tuple[Trap, CoreTm]] = [
                    (Trap(), expr) for _, expr in bindings
                ]
                new_env: Env = env
                for (trap, _), (binder, _) in zip(trap_pairs, bindings):
                    new_env = new_env.set(binder.name.unique, trap)

                first_trap, first_expr = trap_pairs[0]
                rest = trap_pairs[1:]
                return (
                    first_expr,
                    new_env,
                    BackpatchNext(first_trap, rest, new_env, body, k),
                )

            case CoreCase(scrut=scrut, var=var, alts=alts):
                return (scrut, env, Kases(alts, var, env, k))

            case _:
                raise Exception(f"step: unhandled term: {t!r}")

    async def call_continue(self, v: Val, k: Cont) -> Config | Val:
        match k:
            case Ar(arg=arg, env=env, k=k2):
                match v:
                    case VClosure() | VPartial():
                        return (arg, env, Ap(v, k2))
                    case _:
                        raise Exception(
                            f"expected closure, partial, or primop in function position, got: {v!r}"
                        )
            case Ap(closure=f, k=k2):
                match f:
                    case VClosure(env=cenv, param=param, body=body):
                        return (body, cenv.set(param.name.unique, v), k2)
                    case VPartial(name=name, arity=arity, done=done, finish=finish):
                        new_done = done + [v]
                        if arity == len(new_done):
                            # VPartial apply is the only place where VAsync can appear
                            return await self.call_continue(await unasync(finish(new_done)), k2)
                        else:
                            return await self.call_continue(
                                VPartial(name, arity, new_done, finish), k2
                            )
            case LetBind(binder=binder, body=body, env=env, k=k2):
                return (body, env.set(binder.name.unique, v), k2)
            case BackpatchNext(trap=trap, rest=rest, new_env=new_env, body=body, k=k2):
                trap.set(v)
                if rest:
                    next_trap, next_expr = rest[0]
                    return (
                        next_expr,
                        new_env,
                        BackpatchNext(next_trap, rest[1:], new_env, body, k2),
                    )
                else:
                    return (body, new_env, k2)
            case Kases(alts=alts, scrut_var=scrut_var, env=env, k=k2):
                scrut_key = scrut_var.name.unique
                for alt, body in alts:
                    match alt, v:
                        case LitAlt(lit=lit), VLit(lit=lit_) if lit == lit_:
                            return (body, env.set(scrut_key, v), k2)
                        case DataAlt(tag=tag, vars=vars), VData(tag=tag_, vals=vals) if tag == tag_:
                            new_env = env
                            for var, val in zip(vars, vals):
                                new_env = new_env.set(var.name.unique, val)
                            return (body, new_env, k2)
                        case DefaultAlt(), _:
                            return (body, env.set(scrut_key, v), k2)
                        case _:
                            pass
                raise Exception(f"no matching case for value: {v!r}")
            case Halt():
                return v
            case _:
                raise Exception(f"invalid continuation: {k!r}")


async def unasync(val: Val) -> Val:
    match val:
        case VAsync(v):
            return await v
        case _:
            return val
