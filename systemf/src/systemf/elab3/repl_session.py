
from typing import Any, Callable, Protocol, cast, overload, override

from pyrsistent import pmap

from systemf.elab3.core_extra import CoreBuilderExtra
from systemf.elab3.types.ast import ImportDecl
from systemf.elab3.types.core import CoreTm
from systemf.elab3.types.protocols import NameGenerator, REPLSessionProto, Synthesizer
from systemf.surface.parser import parse_expression, parse_program, ParseError
from systemf.surface.types import SurfaceTermDeclaration

from . import pipeline
from .pipeline import Code
from . import builtins as bi
from .name_gen import NameGeneratorImpl, check_dups
from .reader_env import ImportSpec, RdrName, ReaderEnv, ImportRdrElt, QualName
from .eval import Evaluator, EvalCtx
from .types import Module, TyThing, REPLContext, Name
from .types.ty import Id, Ty, TyConApp, TyFun
from .types.tything import ACon, AnId, tything_name
from .types.val import VData, Val
from .types.vpartial import VPartial


class REPLSession(EvalCtx, REPLSessionProto):
    """Accumulates imports and bindings. Corresponds to InteractiveContext."""
    ctx: REPLContext
    repl_rdr_env: ReaderEnv               # repl items
    imports_rdr_env: ReaderEnv            # mod imports
    reader_env: ReaderEnv                 # cached merged reader_env of the above 2
    tythings: list[TyThing]               # all definitions
    # keep all evaluated REPL modules and normal modules
    mod_insts: dict[str, dict[Name, Val]] # Cache for evaluated module instances

    _tythings_map: dict[Name, TyThing]
    _core_extra: CoreBuilderExtra
    _state: dict[str, Any]
    _imports: list[str]

    _evaling: list[str]                   # Modules currently being evaluated (for cycle detection)
    _evaluator: Evaluator

    def __init__(self, ctx: REPLContext,
                repl_rdr_env: ReaderEnv,
                tythings: list[TyThing],
                mod_insts: dict[str, dict[Name, Val]],
                ):
        self.ctx = ctx
        self.repl_rdr_env = repl_rdr_env
        # imports are empty initially
        self.imports_rdr_env = ReaderEnv.empty()
        self.reader_env = self.repl_rdr_env
        self.tythings = tythings
        self.mod_insts = mod_insts
        self._tythings_map = {tything_name(thing): thing for thing in tythings}
        self._core_extra = CoreBuilderExtra(self)
        self._state = {}
        self._evaluator = Evaluator(self)
        self._evaling = []


    @property
    def state(self) -> dict[str, Any]:
        return self._state
    
    def clear_state(self):
        self._state = {}

    def fork(self) -> REPLSession:
        """
        Fork this session
        w/ session level states copied.
        """
        return REPLSession(
            ctx=self.ctx,
            repl_rdr_env=ReaderEnv.empty(),
            tythings=self.tythings[:],
            mod_insts=self.mod_insts.copy(),
        )

    def add_import(self, decl: ImportDecl) -> None:
        """Handle an import command by loading the module and updating state."""
        spec = ImportSpec.from_decl(decl)
        mod = self.ctx.load(spec.module_name)
        new_rdr_env = ReaderEnv.from_elts([
            ImportRdrElt.create(name, spec)
            for name, _ in mod.tythings
        ])
        self.imports_rdr_env = self.imports_rdr_env.merge(new_rdr_env)
        self._update_rdr_env()

    def add_args(self, args: list[tuple[str, Val, Ty]]) -> None:
        """Add arguments module in the REPL session."""
        arg_mod = f"Arg{self.ctx.next_replmod_id()}"
        check_dups((n for n, _, _ in args))
        arg_names = [self.name_gen(arg_mod).new_name(n, None) for n, _, _ in args]

        tythings = [cast(TyThing, AnId.create(Id(name=name, ty=ty))) for name, (_, _, ty) in zip(arg_names, args)]
        mod_inst = {
            name: val
            for name, (_, val, _) in zip(arg_names, args)
        }
        self.extend_tythings_rdr(tythings)
        self.mod_insts[arg_mod] = mod_inst

    def add_return(self, ref: list[Val | None], ty: Ty) -> None:
        """Add a return value setter to the REPL session."""
        ret_mod = f"Ret{self.ctx.next_replmod_id()}"
        fun_ty = TyFun(ty, TyConApp(name=bi.BUILTIN_UNIT, args=[]))
        def _fun(args: list[Val]) -> Val:
            if len(args) != 1:
                raise Exception(f"Expected exactly one argument for REPL return, got {len(args)}")
            ref[0] = args[0]
            return bi.UNIT_VAL
        fun_name = self.name_gen(ret_mod).new_name("set_return", None)
        self.extend_tythings_rdr([cast(TyThing, AnId.create(Id(name=fun_name, ty=fun_ty), is_prim=True))])
        self.mod_insts[ret_mod] = {
            fun_name: VPartial.create(fun_name.surface, 1, _fun)
        }

    async def eval(self, input: str) -> tuple[Val, Ty] | None:
        """
        Evaluate a REPL expression by wrapping it in a synthetic module,
        typechecking, then running ``eval_mod``.

        This is where REPL-level caching (e.g. RefCell) would be wired up.
        """
        repl_id = self.ctx.next_replmod_id()
        mod_name = f"REPL{repl_id}"
        file_path = f"<repl {repl_id}>"
        is_expr, ast = normalize_input(file_path, input)
        repl_mod = pipeline.execute(self.ctx, mod_name, file_path, ast,
                                    reader_env=self.reader_env,
                                    type_env=self._tythings_map.copy())
        self.extend_tythings_rdr([thing for _, thing in repl_mod.tythings])
        mod_inst = await self.eval_mod(repl_mod)
        self.mod_insts[mod_name] = mod_inst

        if is_expr:
            # Convention: REPL expressions bind to `it`
            names = self.reader_env.lookup(QualName(mod_name, "it"))
            match names:
                case [ImportRdrElt(name=name)]:
                    val = mod_inst[name]
                    ty = cast(AnId, self._tythings_map[name]).id.ty
                    return val, ty
                case _:
                    raise Exception(f"Expected single binding for `it`, got: {names}")
        return None

    @override
    async def unsafe_eval(self, input: CoreTm) -> Val:
        return await self._evaluator._eval_expr(input, pmap())

    # --- EvalCtx implementation ---------------------------------------------

    @property
    @override
    def core_extra(self) -> CoreBuilderExtra:
        return self._core_extra
    
    def get_session(self) -> REPLSessionProto | None:
        return self
    
    def resolve_name(self, occ: RdrName) -> Name:
        names = self.reader_env.lookup(occ)
        match names:
            case [ImportRdrElt(name=name)]:
                return name
            case []:
                raise Exception(f"Name {occ} not found")
            case _:
                raise Exception(f"Ambiguous name {occ}: {names}")

    def lookup(self, name: Name) -> TyThing:
        # REPL Session is like a special module, check first.
        if (thing := self._tythings_map.get(name)) is not None:
            return thing
        # then normal modules
        if (thing := self.ctx.load(name.mod)._tythings_map.get(name)) is not None:
            return thing
        raise Exception(f"Name {name} not found in REPL session")

    @override
    async def lookup_gbl(self, name: Name) -> Val:
        """Resolve a global name, loading and evaluating modules on demand."""
        mod_name = name.mod

        # 1. Check runtime value cache
        cached = self.mod_insts.get(mod_name, {}).get(name)
        if cached is not None:
            return cached

        # 2. Cycle detection for evaluation
        if mod_name in self._evaling:
            raise Exception(
                f"Cyclic evaluation detected: {'->'.join(self._evaling + [mod_name])}"
            )

        self._evaling.append(mod_name)
        try:
            # 3. Load the typechecked module
            mod = self.ctx.load(mod_name)

            # 4. Eager whole module processing & return
            mod_inst = await self.eval_mod(mod)
            self.mod_insts[mod.name] = mod_inst
            return mod_inst[name]
        finally:
            _ = self._evaling.pop()

    async def eval_mod(self, mod: Module) -> dict[Name, Val]:
        mod_inst = mk_mod_inst(mod, self.mk_primop)
        mod_inst = await self._evaluator.eval_mod(mod, mod_inst)
        return mod_inst

    # --- State management ---

    def extend_tythings_rdr(self, tythings: list[TyThing]):
        """
        This is opinionated for use in REPL, where names shadow previous ones if any
        """
        self.tythings.extend(tythings)
        names = [tything_name(thing) for thing in tythings]
        self._tythings_map.update({name: thing for name, thing in zip(names, tythings)})
        new_rdr = ReaderEnv.from_elts([
            ImportRdrElt.create(name, ImportSpec(name.mod, None, False))
            for name in names
        ])
        self.repl_rdr_env = self.repl_rdr_env.shadow(set(names)).merge(new_rdr)
        self._update_rdr_env()

    def _update_rdr_env(self):
        self.reader_env = self.imports_rdr_env.merge(self.repl_rdr_env)

    # --- helpers ---

    def name_gen(self, mod_name: str) -> NameGenerator:
        return NameGeneratorImpl(mod_name, self.ctx.uniq)

    def mk_primop(self, name: Name, thing: AnId) -> Val:
        if (p := self.ctx.ops_synther.get_primop(name, thing, self)) is not None:
            return p
        raise Exception(f"Unknown primitive operation: {name}")


def normalize_input(file_path: str, input: str) -> tuple[bool, Code]:
    """Normalize REPL input.

    Try expression parsing first. If that fails, try program parsing.
    If program parsing also fails, report the expression parse error
    (it's usually more informative).

    :returns: (is_expr, code)
    """
    expr_err = None
    try:
        expr = parse_expression(input, file_path)
        return True, (
            [],
            [SurfaceTermDeclaration(
                name="it",
                type_annotation=None,
                body=expr,
                docstring=None,
                pragma=None,
            )],
        )
    except ParseError as _expr_err:
        expr_err = _expr_err

    try:
        code: Code = input
        _, decls = parse_program(input, file_path)

        # prefer throw expression parse error
        if not decls and expr_err:
            raise expr_err
        return False, code
    except ParseError as prog_err:
        raise expr_err or prog_err


def mk_mod_inst(mod: Module, get_primop: Callable[[Name, AnId], Val]) -> dict[Name, Val]:
    mod_inst: dict[Name, Val] = {}
    for name, thing in mod.tythings:
        match thing:
            case ACon(name=con_name, tag=tag, arity=arity):
                mod_inst[name] = VPartial.create(
                    con_name.surface, arity,
                    _mk_data(tag),
                )
            case AnId(name=name, is_prim=True):
                mod_inst[name] = get_primop(name, thing)
            case _: pass
    return mod_inst

def _mk_data(tag: int) -> Callable[[list[Val]], Val]:
    def _con(args: list[Val]) -> Val:
        return VData(tag, args)
    return _con
