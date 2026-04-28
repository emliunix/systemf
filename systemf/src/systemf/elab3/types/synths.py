from dataclasses import dataclass

from .protocols import REPLSessionProto, Synthesizer
from .tything import AnId
from .ty import Name
from .val import Val


class PrimOpsSynth(Synthesizer):
    """A simple synthesizer that provides primitive operations from a given dictionary."""
    ops: dict[str, Val]

    def __init__(self, ops: dict[str, Val]):
        self.ops = ops

    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        return self.ops.get(name.surface)


class SynthRouter(Synthesizer):
    mod_synths: dict[str, Synthesizer]
    next_synth: Synthesizer | None

    def __init__(self, mod_synths: dict[str, Synthesizer], next_synth: Synthesizer | None = None):
        self.mod_synths = mod_synths
        self.next_synth = next_synth

    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        if (synth := self.mod_synths.get(name.mod)) is not None:
            primop = synth.get_primop(name, thing, session)
            if primop is not None:
                return primop
        if self.next_synth is not None:
            return self.next_synth.get_primop(name, thing, session)
        return None
    

@dataclass
class SynthChain(Synthesizer):
    curr: Synthesizer
    next: Synthesizer | None

    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        if (primop := self.curr.get_primop(name, thing, session)) is not None:
            return primop
        if self.next is not None:
            return self.next.get_primop(name, thing, session)
        return None
