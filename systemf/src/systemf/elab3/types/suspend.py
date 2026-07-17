from collections.abc import Callable, Coroutine
from dataclasses import dataclass

from .protocols import REPLSessionProto
from .val import Val, VAsync


# Uniform primitive finish signature: receives all collected args plus the
# current session (``None`` outside a REPL session) and returns the result Val.
# It may return a ``VAsync`` for asynchronous primitives (unwrapped by the
# evaluator via ``unasync``).
type PrimFinish = Callable[[list[Val], REPLSessionProto | None], Val]


@dataclass
class VSuspend(Val):
    """A suspended primitive or data-constructor application.

    A primitive (builtin primop, data constructor, or session/async primop) is
    represented uniformly by a single ``finish(args, session)`` callback plus
    its ``arity``.  Evaluation *suspends* — the value stays a ``VSuspend`` —
    until ``arity`` arguments have been collected, at which point ``finish``
    runs.
    """
    name: str
    arity: int
    done: list[Val]
    finish: PrimFinish

    @staticmethod
    def create(name: str, arity: int, finish: PrimFinish) -> Val:
        if arity == 0:
            return finish([], None)
        return VSuspend(name, arity, [], finish)


def finish_async(
    func: Callable[[list[Val], REPLSessionProto | None], Coroutine[None, None, Val]],
) -> PrimFinish:
    """Adapt an async finish into the uniform ``PrimFinish`` by deferring it as
    a ``VAsync`` (which the evaluator awaits)."""
    return lambda args, session: VAsync(func(args, session))
