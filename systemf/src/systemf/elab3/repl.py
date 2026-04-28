"""
REPL - orchestration and state management.

The main context shared across REPL sessions. REPL session is the main interface for REPL.
"""

from pathlib import Path
from typing import Callable, cast, override

from systemf.surface.parser import parse_expression, parse_program, ParseError
from systemf.surface.types import SurfaceTermDeclaration
from systemf.utils.uniq import Uniq

from . import pipeline
from .pipeline import Code
from . import builtins as bi
from . import builtins_rts as rts
from .name_gen import NameCacheImpl
from .reader_env import ReaderEnv
from .repl_session import REPLSession
from .types import Module, REPLContext, Name, NameCache
from .types.protocols import Ext, PrimOpsSynth, REPLSessionProto, Synthesizer
from .types.tything import AnId
from .types.val import VData, VPartial, Val


class REPL(REPLContext):
    """Owns shared state, creates sessions, orchestrates module loading.

    Contains NameCache which wraps the Uniq counter for generating unique IDs.
    Also owns the session counter for unique module names.
    """
    uniq: Uniq
    name_cache: NameCache
    exts: list[Ext]
    ops_synther: Synthesizer
    
    modules: dict[str, Module]
    search_paths: list[str]
    
    _loading: dict[str, str | None]
    _replmod_counter: int

    def __init__(self, search_paths: list[str] | None = None, exts: list[Ext] | None = None):
        self.uniq = Uniq(bi.BUILTIN_ENDS)
        self.name_cache = NameCacheImpl()
        self.modules = {}
        self._loading = {}
        self._replmod_counter = 0
        self.exts = exts or []
        
        mod_synths = {
            "builtins": cast(Synthesizer, PrimOpsSynth(_builtins_primops())),
        }
        paths = search_paths and search_paths[:] or []
        paths.extend([".", str(Path(__file__).parent.parent)])
        for ext in self.exts:
            if (synths := ext.synthesizer()) is not None:
                mod_synths.update(synths)
            if len(ext_paths := ext.search_paths()) > 0:
                paths.extend(ext_paths)
        self.ops_synther = SyntRouter(mod_synths, LLMSynth())
        self.search_paths = paths

    # --- REPLContext implementation -----------------------------------------

    @override
    def next_replmod_id(self) -> int:
        """Get next unique module ID."""
        v = self._replmod_counter
        self._replmod_counter += 1
        return v

    @override
    def load(self, name: str) -> Module:
        return self._load(name, None)

    @override
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        return self.ops_synther.get_primop(name, thing, session)

    def _load(self, name: str, from_mod: str | None = None) -> Module:
        """
        Load a module and its dependencies into HPT.
        """
        if (m := self.modules.get(name)) is not None:
            return m
        if name in self._loading:
            raise Exception(f"Cyclic imports detected: {_build_import_chain(self._loading, name)}")

        self._loading[name] = from_mod
        try:
            m = self._load_module(name, self._mod_file(name))
            self.modules[name] = m
            return m
        finally:
            del self._loading[name]

    def _mod_file(self, module_name: str) -> Path:
        parts = module_name.split(".")
        for sp in self.search_paths:
            p = Path(sp) / ("/".join(parts) + ".sf")
            if p.exists():
                return p
        raise Exception(f"module not found: {module_name}")

    def _load_module(self, name: str, file: Path) -> Module:
        text = file.read_text(encoding="utf-8")
        return pipeline.execute(self, name, str(file), text)

    def new_session(self) -> REPLSession:
        """Create a new REPL session with given state."""
        return REPLSession(
            self,
            reader_env=ReaderEnv.empty(),
            tythings=[],
            mod_insts={},
        )


def _builtins_primops() -> dict[str, Val]:
    """Build the primop cache. Called once at REPL init."""

    # FIX: this is hacky, but we need rename phase of bulitins to get the tags assigned
    # so we just hardcode what will be assigned
    true_val = VData(0, [])
    false_val = VData(1, [])

    builtins: dict[str, Val] = {}

    def _reg(surface: str, arity: int, func):
        builtins[surface] = VPartial.create(surface, arity, func)

    _reg(bi.BUILTIN_INT_PLUS.surface, 2, rts.int_plus)
    _reg(bi.BUILTIN_INT_MINUS.surface, 2, rts.int_minus)
    _reg(bi.BUILTIN_INT_MULTIPLY.surface, 2, rts.int_multiply)
    _reg(bi.BUILTIN_INT_DIVIDE.surface, 2, rts.int_divide)
    _reg(bi.BUILTIN_INT_EQ.surface, 2, rts.mk_int_eq(true_val, false_val))
    _reg(bi.BUILTIN_INT_NEQ.surface, 2, rts.mk_int_neq(true_val, false_val))
    _reg(bi.BUILTIN_INT_LT.surface, 2, rts.mk_int_lt(true_val, false_val))
    _reg(bi.BUILTIN_INT_GT.surface, 2, rts.mk_int_gt(true_val, false_val))
    _reg(bi.BUILTIN_INT_LE.surface, 2, rts.mk_int_le(true_val, false_val))
    _reg(bi.BUILTIN_INT_GE.surface, 2, rts.mk_int_ge(true_val, false_val))
    _reg(bi.BUILTIN_STRING_CONCAT.surface, 2, rts.string_concat)
    _reg(bi.BUILTIN_ERROR.surface, 1, rts.error)
    _reg(bi.BUILTIN_MK_REF.surface, 1, rts.mk_ref)
    _reg(bi.BUILTIN_SET_REF.surface, 2, rts.set_ref)
    _reg(bi.BUILTIN_GET_REF.surface, 1, rts.get_ref)

    return builtins


def _build_import_chain(loads: dict[str, str | None], start: str) -> str:
    chain = [start]
    parent = loads.get(start)
    while parent is not None:
        chain.append(parent)
        parent = loads.get(parent)
    return "->".join(list(reversed(chain)))


class SyntRouter(Synthesizer):
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


class LLMSynth(Synthesizer):
    # move to 
    def get_primop(self, name: Name, thing: AnId, session: REPLSessionProto) -> Val | None:
        # TODO: implement LLM-based synthesizer
        # should be moved to bub_sf extension
        return None