from collections.abc import Callable, Coroutine
from dataclasses import dataclass

from .protocols import REPLSessionProto
from .val import Val, VAsync


# TODO: investigate how to eliminate None while allow VPartial.create
class SessionAwareFinish:
    def __init__(self, func: Callable[[list[Val], REPLSessionProto | None], Val]):
        self.func = func

    def __call__(self, vals: list[Val], *, session: REPLSessionProto | None = None) -> Val:
        return self.func(vals, session)
    
    @staticmethod
    def from_async(func: Callable[[list[Val], REPLSessionProto | None], Coroutine[None, None, Val]]) -> SessionAwareFinish:
        return SessionAwareFinish(lambda vals, session: VAsync(func(vals, session)))


@dataclass
class VPartial(Val):
    """Partially-applied constructor or primop."""
    name: str
    arity: int
    done: list[Val]
    finish: Callable[[list[Val]], Val] | SessionAwareFinish

    @staticmethod
    def create(name: str, arity: int, finish: Callable[[list[Val]], Val] | SessionAwareFinish) -> Val:
        if arity == 0:
            return finish([])
        else:
            return VPartial(name, arity, [], finish)
