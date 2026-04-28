"""Tests for elab3 CEK evaluator."""
import pytest

from typing import override
from pathlib import Path

import systemf

from systemf.elab3 import pipeline
from systemf.elab3.builtins import (
    BUILTIN_ENDS,
    BUILTIN_TRUE,
    BUILTIN_FALSE,
    BUILTIN_BOOL,
    BUILTIN_UNIT,
    BUILTIN_MK_UNIT,
    BUILTIN_LIST,
    BUILTIN_LIST_CONS,
    BUILTIN_LIST_NIL,
    BUILTIN_PAIR,
    BUILTIN_PAIR_MKPAIR,
    BUILTIN_INT_PLUS,
    BUILTIN_INT_MINUS,
    BUILTIN_INT_EQ,
    BUILTIN_STRING_CONCAT,
    BUILTIN_INT_MULTIPLY,
    BUILTIN_INT_DIVIDE,
    BUILTIN_INT_NEQ,
    BUILTIN_INT_LT,
    BUILTIN_INT_GT,
    BUILTIN_INT_LE,
    BUILTIN_INT_GE,
    BUILTIN_ERROR,
    FALSE_VAL,
    NIL_VAL,
    TRUE_VAL,
)
from systemf.elab3.eval import (
    Evaluator,
    EvalCtx,
)
from systemf.elab3.core_extra import CoreBuilderExtra, lookup_data_con
from pyrsistent import pmap

from systemf.elab3.name_gen import NameCacheImpl
from systemf.elab3.repl import _builtins_primops
from systemf.elab3.repl_session import mk_mod_inst
from systemf.elab3.types.protocols import NameCache, REPLContext, TyLookup
from systemf.elab3.types.tything import AnId, TyThing
from systemf.elab3.types.val import (
    Val,
    VLit,
    VClosure,
    VData,
    VPartial,
)
from systemf.elab3.types.core import (
    CoreLit,
    CoreVar,
    CoreLam,
    CoreApp,
    CoreLet,
    CoreTyLam,
    CoreTyApp,
    CoreCase,
    NonRec,
    Rec,
    DataAlt,
    LitAlt,
    DefaultAlt,
    Binding,
)
from systemf.elab3.types.ty import (
    Id,
    LitInt,
    LitString,
    Name,
    TyInt,
    TyFun,
    TyString,
    BoundTv,
)
from systemf.elab3.types.mod import Module
from systemf.utils.uniq import Uniq


# =============================================================================
# Builtin tags (Name.unique — globally unique across all types)
# =============================================================================

TRUE_TAG = 0
FALSE_TAG = 1
NIL_TAG = 0
CONS_TAG = 1
MKUNIT_TAG = 0
MKPAIR_TAG = 0


# =============================================================================
# Helpers
# =============================================================================

def _name(mod: str, surface: str, unique: int) -> Name:
    return Name(mod, surface, unique)


def _id(mod: str, surface: str, unique: int, ty) -> Id:
    return Id(_name(mod, surface, unique), ty)


def _build_chain(loads: dict[str, str | None], start: str) -> str:
    chain = [start]
    parent = loads.get(start)
    while parent is not None:
        chain.append(parent)
        parent = loads.get(parent)
    return "->".join(list(reversed(chain)))


# =============================================================================
# FakeCtx
# =============================================================================


class Ctx(REPLContext):
    uniq: Uniq
    name_cache: NameCache
    mods: dict[str, Module]
    _next_id: int

    def __init__(self):
        self.uniq = Uniq(BUILTIN_ENDS)
        self.name_cache = NameCacheImpl()
        self.mods = {}
        self._next_id = 0

    def load(self, name: str) -> Module:
        return self.mods[name]

    def next_replmod_id(self) -> int:
        next_id = self._next_id
        self._next_id += 1
        return next_id

    def load_module(self, name: str, file: Path) -> Module:
        text = file.read_text(encoding="utf-8")
        return pipeline.execute(self, name, str(file), text)


class FakeCtx(EvalCtx, TyLookup):
    ctx: Ctx
    tythings: dict[Name, TyThing]
    mod_insts: dict[str, dict[Name, Val]]
    _core_extra: CoreBuilderExtra
    _evaluator: Evaluator

    def __init__(self):
        self.ctx = Ctx()
        self.tythings: dict[Name, TyThing] = {}
        self.mod_insts: dict[str, dict[Name, Val]] = {}
        self._core_extra = CoreBuilderExtra(self)
        self._evaluator = Evaluator(self)

    @staticmethod
    async def create():
        ctx = FakeCtx()
        # setup
        mod = ctx.ctx.load_module("builtins", Path(systemf.__file__).parent / "builtins.sf")
        ctx.ctx.mods["builtins"] = mod
        _primops = _builtins_primops()
        mod_inst = mk_mod_inst(ctx.ctx.load("builtins"), lambda n, t: _primops[n.surface])
        ctx.mod_insts["builtins"] = await ctx._evaluator.eval_mod(mod, mod_inst)
        return ctx

    @property
    @override
    def core_extra(self) -> CoreBuilderExtra:
        return self._core_extra

    @override
    async def lookup_gbl(self, name: Name) -> Val:
        return self.mod_insts[name.mod][name]
    
    @override
    def lookup(self, name: Name) -> TyThing:
        thing = self.ctx.load(name.mod).lookup_tything(name)
        assert thing, f"Name {name} not found in module {name.mod}"
        return thing
    
    @property
    def evaluator(self) -> Evaluator:
        return self._evaluator
    
    async def add_mod(self, mod: Module):
        self.ctx.mods[mod.name] = mod
        def _raise(n, t):
            raise Exception("no primops")
        mod_inst = mk_mod_inst(self.ctx.load(mod.name), _raise)
        self.mod_insts[mod.name] = await self._evaluator.eval_mod(mod, mod_inst)


# =============================================================================
# Core expression evaluation (via _eval_expr)
# =============================================================================

async def test_eval_lit():
    ev = (await FakeCtx.create()).evaluator
    result = await ev._eval_expr(CoreLit(LitInt(42)), pmap())
    assert isinstance(result, VLit)
    assert result.lit == LitInt(42)


async def test_eval_lambda():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 1, TyInt())
    lam = CoreLam(x, CoreVar(x))
    result = await ev._eval_expr(lam, pmap())
    assert isinstance(result, VClosure)
    assert result.param.name.unique == x.name.unique


async def test_eval_app():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 1, TyInt())
    lam = CoreLam(x, CoreVar(x))
    app = CoreApp(lam, CoreLit(LitInt(99)))
    result = await ev._eval_expr(app, pmap())
    assert result == VLit(LitInt(99))


async def test_eval_let_nonrec():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 1, TyInt())
    let_expr = CoreLet(NonRec(x, CoreLit(LitInt(7))), CoreVar(x))
    result = await ev._eval_expr(let_expr, pmap())
    assert result == VLit(LitInt(7))


async def test_eval_let_rec_guarded():
    r"""Recursive binding guarded by lambda: let rec f = \x -> f x in f."""
    ev = (await FakeCtx.create()).evaluator
    f = _id("Test", "f", 1, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 2, TyInt())
    body = CoreLam(x, CoreApp(CoreVar(f), CoreVar(x)))
    expr = CoreLet(Rec([(f, body)]), CoreVar(f))
    result = await ev._eval_expr(expr, pmap())
    assert isinstance(result, VClosure)


async def test_eval_ty_lam_ty_app_erasure():
    """Type abstractions and applications are erased at runtime."""
    ev = (await FakeCtx.create()).evaluator
    a = BoundTv(_name("Test", "a", 3))
    x = _id("Test", "x", 4, TyInt())
    tlam = CoreTyLam(a, CoreLam(x, CoreVar(x)))
    tapp = CoreTyApp(tlam, TyInt())
    app = CoreApp(tapp, CoreLit(LitInt(5)))
    result = await ev._eval_expr(app, pmap())
    assert isinstance(result, VLit)
    assert result == VLit(LitInt(5))


# =============================================================================
# Case expressions
# =============================================================================

async def test_eval_case_data_alt():
    ev = (await FakeCtx.create()).evaluator
    s = _id("Test", "s", 50, TyInt())
    case_expr = CoreCase(
        scrut=CoreVar(Id(BUILTIN_TRUE, TyInt())),
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), CoreLit(LitInt(1))),
            (DataAlt(con=BUILTIN_FALSE, tag=FALSE_TAG, vars=[]), CoreLit(LitInt(0))),
            (DefaultAlt(), CoreLit(LitInt(-1))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(1))


async def test_eval_case_default_alt():
    ev = (await FakeCtx.create()).evaluator
    s = _id("Test", "s", 51, TyInt())
    case_expr = CoreCase(
        scrut=CoreVar(Id(BUILTIN_LIST_NIL, TyInt())),
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=99, vars=[]), CoreLit(LitInt(1))),
            (DefaultAlt(), CoreLit(LitInt(42))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(42))


async def test_eval_case_cons_pattern():
    """Pattern match on Cons with bound variables."""
    ev = (await FakeCtx.create()).evaluator
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    # scrut = Cons 1 Nil
    scrut = CoreApp(
        CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))),
        CoreVar(nil_id),
    )
    s = _id("Test", "s", 52, TyInt())
    x = _id("Test", "x", 53, TyInt())
    xs = _id("Test", "xs", 54, TyInt())
    case_expr = CoreCase(
        scrut=scrut,
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_LIST_CONS, tag=CONS_TAG, vars=[x, xs]), CoreVar(x)),
            (DataAlt(con=BUILTIN_LIST_NIL, tag=NIL_TAG, vars=[]), CoreLit(LitInt(0))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert isinstance(result, VLit)
    assert result == VLit(LitInt(1))


# =============================================================================
# Builtin resolution via CoreVar fallback
# =============================================================================

async def test_builtin_int_plus():
    ev = (await FakeCtx.create()).evaluator
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    expr = CoreApp(
        CoreApp(CoreVar(plus_id), CoreLit(LitInt(1))),
        CoreLit(LitInt(2)),
    )
    result = await ev._eval_expr(expr, pmap())
    assert isinstance(result, VLit)
    assert result == VLit(LitInt(3))


async def test_builtin_int_minus():
    ev = (await FakeCtx.create()).evaluator
    minus_id = Id(BUILTIN_INT_MINUS, TyInt())
    expr = CoreApp(
        CoreApp(CoreVar(minus_id), CoreLit(LitInt(10))),
        CoreLit(LitInt(3)),
    )
    result = await ev._eval_expr(expr, pmap())
    assert isinstance(result, VLit)
    assert result == VLit(LitInt(7))


async def test_builtin_int_eq():
    ev = (await FakeCtx.create()).evaluator
    eq_id = Id(BUILTIN_INT_EQ, TyInt())
    true_expr = CoreApp(
        CoreApp(CoreVar(eq_id), CoreLit(LitInt(5))),
        CoreLit(LitInt(5)),
    )
    false_expr = CoreApp(
        CoreApp(CoreVar(eq_id), CoreLit(LitInt(5))),
        CoreLit(LitInt(6)),
    )
    assert isinstance(await ev._eval_expr(true_expr, pmap()), VData)
    assert (await ev._eval_expr(true_expr, pmap())) == TRUE_VAL
    assert isinstance(await ev._eval_expr(false_expr, pmap()), VData)
    assert (await ev._eval_expr(false_expr, pmap())) == FALSE_VAL


async def test_builtin_string_concat():
    ev = (await FakeCtx.create()).evaluator
    concat_id = Id(BUILTIN_STRING_CONCAT, TyInt())
    expr = CoreApp(
        CoreApp(CoreVar(concat_id), CoreLit(LitString("hello"))),
        CoreLit(LitString(" world")),
    )
    result = await ev._eval_expr(expr, pmap())
    assert isinstance(result, VLit)
    assert result == VLit(LitString("hello world"))


async def test_builtin_bool_constructors():
    ctx = await FakeCtx.create()
    ev = ctx.evaluator
    _, _, true_ty = lookup_data_con(ctx, BUILTIN_TRUE)
    true_id = Id(BUILTIN_TRUE, true_ty)
    _, _, false_ty = lookup_data_con(ctx, BUILTIN_FALSE)
    false_id = Id(BUILTIN_FALSE, false_ty)
    assert (await ev._eval_expr(CoreVar(true_id), pmap())) == TRUE_VAL
    assert (await ev._eval_expr(CoreVar(false_id), pmap())) == FALSE_VAL


async def test_builtin_list_nil():
    ev = (await FakeCtx.create()).evaluator
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    result = await ev._eval_expr(CoreVar(nil_id), pmap())
    assert isinstance(result, VData)
    assert result == NIL_VAL


async def test_builtin_partial_saturation():
    """Cons partially applied, then fully applied."""
    ev = (await FakeCtx.create()).evaluator
    # FIX: check test_builtin_bool_constructors and fix
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    # Cons 1 -> VPartial
    p1 = await ev._eval_expr(CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))), pmap())
    assert isinstance(p1, VPartial)
    assert p1.done == [VLit(LitInt(1))]
    # (Cons 1) Nil -> VData
    full = await ev._eval_expr(
        CoreApp(CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))), CoreVar(nil_id)),
        pmap(),
    )
    # FIX: structural equality, use just ==
    assert isinstance(full, VData)
    assert full.tag == CONS_TAG


# =============================================================================
# Module loading via lookup_gbl / eval_mod
# =============================================================================

async def test_eval_mod_nonrec():
    # NOTE: take this as an example
    a = Id(_name("M", "a", BUILTIN_ENDS + 10), TyInt())
    b = Id(_name("M", "b", BUILTIN_ENDS + 11), TyInt())
    bindings: list[Binding] = [
        NonRec(a, CoreLit(LitInt(1))),
        NonRec(b, CoreLit(LitInt(2))),
    ]
    ctx = await FakeCtx.create()
    await ctx.add_mod(Module.create("M",
        [(a.name, AnId.create(a)), (b.name, AnId.create(b))],
        bindings
    ))
    assert await ctx.lookup_gbl(a.name) == VLit(LitInt(1))
    assert await ctx.lookup_gbl(b.name) == VLit(LitInt(2))


async def test_eval_mod_rec_single_guarded():
    f = _id("M", "f", BUILTIN_ENDS + 20, TyFun(TyInt(), TyInt()))
    x = _id("M", "x", BUILTIN_ENDS + 21, TyInt())
    lam = CoreLam(x, CoreApp(CoreVar(f), CoreVar(x)))
    bindings: list[Binding] = [Rec([(f, lam)])]
    ctx = await FakeCtx.create()
    await ctx.add_mod(Module.create("M", [(f.name, AnId.create(f))], bindings))
    result = await ctx.lookup_gbl(f.name)
    assert isinstance(result, VClosure)


async def test_eval_mod_rec_multi_mutual():
    """Mutual recursion with two functions."""
    f = _id("M", "f", BUILTIN_ENDS + 30, TyFun(TyInt(), TyInt()))
    g = _id("M", "g", BUILTIN_ENDS + 31, TyFun(TyInt(), TyInt()))
    x = _id("M", "x", BUILTIN_ENDS + 32, TyInt())
    f_lam = CoreLam(x, CoreApp(CoreVar(g), CoreVar(x)))
    g_lam = CoreLam(x, CoreApp(CoreVar(f), CoreVar(x)))
    bindings: list[Binding] = [Rec([(f, f_lam), (g, g_lam)])]
    ctx = await FakeCtx.create()
    await ctx.add_mod(Module.create("M",
        [(f.name, AnId.create(f)), (g.name, AnId.create(g))],
        bindings,
    ))
    assert isinstance(await ctx.lookup_gbl(f.name), VClosure)
    assert isinstance(await ctx.lookup_gbl(g.name), VClosure)


async def test_eval_mod_raises_on_missing_module():
    """Lookup on an unknown module raises."""
    ctx = await FakeCtx.create()
    with pytest.raises(KeyError):
        await ctx.lookup_gbl(_name("M", "foo", BUILTIN_ENDS + 99))


async def test_eval_mod_cyclic_raises():
    """Evaluating a module that references an unloaded module raises."""
    a_name = _name("A", "x", BUILTIN_ENDS + 50)
    b_name = _name("B", "y", BUILTIN_ENDS + 51)
    bindings_a: list[Binding] = [NonRec(Id(a_name, TyInt()), CoreVar(Id(b_name, TyInt())))]
    ctx = await FakeCtx.create()
    with pytest.raises(KeyError):
        await ctx.add_mod(Module.create("A",
            [(a_name, AnId.create(Id(a_name, TyInt())))],
            bindings_a,
        ))


# =============================================================================
# Non-polymorphic mutual recursive functions (applied)
# =============================================================================

async def test_mutual_rec_functions_applied():
    """
    f = \n -> if n == 0 then 1 else g (n - 1)
    g = \n -> if n == 0 then 2 else f (n - 1)
    f 0 -> 1
    f 1 -> g 0 -> 2
    """
    f = _id("M", "f", BUILTIN_ENDS + 60, TyFun(TyInt(), TyInt()))
    g = _id("M", "g", BUILTIN_ENDS + 61, TyFun(TyInt(), TyInt()))
    n = _id("M", "n", BUILTIN_ENDS + 62, TyInt())
    eq_id = Id(BUILTIN_INT_EQ, TyInt())
    minus_id = Id(BUILTIN_INT_MINUS, TyInt())

    zero = CoreLit(LitInt(0))
    one = CoreLit(LitInt(1))
    two = CoreLit(LitInt(2))

    # n == 0
    n_eq_0 = CoreApp(CoreApp(CoreVar(eq_id), CoreVar(n)), zero)
    # n - 1
    n_minus_1 = CoreApp(CoreApp(CoreVar(minus_id), CoreVar(n)), one)

    s = _id("M", "s", BUILTIN_ENDS + 63, TyInt())
    # f body: case (n == 0) of True -> 1; _ -> g (n - 1)
    f_body = CoreCase(
        scrut=n_eq_0,
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), one),
            (DefaultAlt(), CoreApp(CoreVar(g), n_minus_1)),
        ],
    )
    # g body: case (n == 0) of True -> 2; _ -> f (n - 1)
    g_body = CoreCase(
        scrut=n_eq_0,
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), two),
            (DefaultAlt(), CoreApp(CoreVar(f), n_minus_1)),
        ],
    )

    f_lam = CoreLam(n, f_body)
    g_lam = CoreLam(n, g_body)

    bindings: list[Binding] = [Rec([(f, f_lam), (g, g_lam)])]

    ctx = await FakeCtx.create()
    await ctx.add_mod(Module.create("M",
        [(f.name, AnId.create(f)), (g.name, AnId.create(g))],
        bindings,
    ))
    ev = ctx.evaluator

    # f 0 -> 1
    result_f0 = await ev._eval_expr(CoreApp(CoreVar(f), zero), pmap())
    assert isinstance(result_f0, VLit)
    assert result_f0.lit.value == 1

    # f 1 -> g 0 -> 2
    result_f1 = await ev._eval_expr(CoreApp(CoreVar(f), one), pmap())
    assert isinstance(result_f1, VLit)
    assert result_f1.lit.value == 2


# =============================================================================
# Primary API: eval_mod / lookup_gbl
# =============================================================================

async def test_eval_mod_primary_api():
    n = _name("M", "answer", BUILTIN_ENDS + 70)
    bindings: list[Binding] = [NonRec(Id(n, TyInt()), CoreLit(LitInt(42)))]
    ctx = await FakeCtx.create()
    await ctx.add_mod(Module.create("M",
        [(n, AnId.create(Id(n, TyInt())))],
        bindings,
    ))
    result = await ctx.lookup_gbl(n)
    assert isinstance(result, VLit)
    assert result.lit.value == 42


# =============================================================================
# Cross-module references
# =============================================================================

async def test_cross_module_reference():
    """Module B references a name from module A; A must be loaded first."""
    a_name = _name("A", "foo", BUILTIN_ENDS + 100)
    b_name = _name("B", "bar", BUILTIN_ENDS + 101)

    bindings_a: list[Binding] = [NonRec(Id(a_name, TyInt()), CoreLit(LitInt(100)))]
    bindings_b: list[Binding] = [NonRec(Id(b_name, TyInt()), CoreVar(Id(a_name, TyInt())))]

    ctx = await FakeCtx.create()
    await ctx.add_mod(Module.create("A",
        [(a_name, AnId.create(Id(a_name, TyInt())))],
        bindings_a,
    ))
    await ctx.add_mod(Module.create("B",
        [(b_name, AnId.create(Id(b_name, TyInt())))],
        bindings_b,
    ))
    result = await ctx.lookup_gbl(b_name)
    assert isinstance(result, VLit)
    assert result.lit.value == 100


# =============================================================================
# Trap / self-reference edge cases
# =============================================================================

async def test_single_rec_unguarded_self_reference_raises():
    """
    A monomorphic single-binding Rec with an unguarded self-reference
    (e.g. f = f) is non-productive and must raise.
    """
    f = _id("M", "f", BUILTIN_ENDS + 110, TyInt())
    bindings: list[Binding] = [Rec([(f, CoreVar(f))])]
    ctx = await FakeCtx.create()
    with pytest.raises(Exception, match="uninitialized letrec trap"):
        await ctx.add_mod(Module.create("M",
            [(f.name, AnId.create(f))],
            bindings,
        ))


async def test_multi_rec_unguarded_mutual_reference_raises():
    """
    Mutual Rec where the first RHS immediately forces the second binder
    is non-productive and must raise.
    """
    f = _id("M", "f", BUILTIN_ENDS + 111, TyInt())
    g = _id("M", "g", BUILTIN_ENDS + 112, TyInt())
    bindings: list[Binding] = [
        Rec([(f, CoreVar(g)), (g, CoreLit(LitInt(1)))])
    ]
    ctx = await FakeCtx.create()
    with pytest.raises(Exception, match="uninitialized letrec trap"):
        await ctx.add_mod(Module.create("M",
            [(f.name, AnId.create(f)), (g.name, AnId.create(g))],
            bindings,
        ))


# =============================================================================
# VPartial (primops are VPartial)
# =============================================================================

async def test_primops_are_vpartial():
    """Primitive operations should resolve to VPartial."""
    ctx = await FakeCtx.create()
    result = await ctx.lookup_gbl(BUILTIN_INT_PLUS)
    assert isinstance(result, VPartial)
    assert result.name == "int_plus"
    assert result.arity == 2
    assert result.done == []


# =============================================================================
# Ported from elab2: variable shadowing, closures, church encodings
# =============================================================================

async def test_eval_shadow():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 200, TyInt())
    x2 = _id("Test", "x", 201, TyInt())
    inner = CoreLam(x2, CoreVar(x2))
    outer = CoreLam(x, inner)
    t = CoreApp(CoreApp(outer, CoreLit(LitInt(1))), CoreLit(LitInt(2)))
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(2))


async def test_eval_closure_captures_env():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 202, TyInt())
    y = _id("Test", "y", 203, TyInt())
    outer = CoreLam(x, CoreLam(y, CoreVar(x)))
    t = CoreApp(outer, CoreLit(LitInt(10)))
    result = await ev._eval_expr(t, pmap())
    assert isinstance(result, VClosure)


async def test_eval_apply_returned_closure():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 204, TyInt())
    y = _id("Test", "y", 205, TyInt())
    outer = CoreLam(x, CoreLam(y, CoreVar(x)))
    t = CoreApp(CoreApp(outer, CoreLit(LitInt(10))), CoreLit(LitInt(20)))
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(10))


async def test_eval_nested_application():
    ev = (await FakeCtx.create()).evaluator
    f = _id("Test", "f", 206, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 207, TyInt())
    y = _id("Test", "y", 208, TyInt())
    apply_f = CoreLam(f, CoreLam(x, CoreApp(CoreVar(f), CoreVar(x))))
    id_fn = CoreLam(y, CoreVar(y))
    t = CoreApp(CoreApp(apply_f, id_fn), CoreLit(LitInt(7)))
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(7))


async def test_eval_church_true():
    ev = (await FakeCtx.create()).evaluator
    t_var = _id("Test", "t", 209, TyInt())
    f_var = _id("Test", "f", 210, TyInt())
    church_true = CoreLam(t_var, CoreLam(f_var, CoreVar(t_var)))
    expr = CoreApp(CoreApp(church_true, CoreLit(LitInt(1))), CoreLit(LitInt(0)))
    result = await ev._eval_expr(expr, pmap())
    assert result == VLit(LitInt(1))


async def test_eval_church_false():
    ev = (await FakeCtx.create()).evaluator
    t_var = _id("Test", "t", 211, TyInt())
    f_var = _id("Test", "f", 212, TyInt())
    church_false = CoreLam(t_var, CoreLam(f_var, CoreVar(f_var)))
    expr = CoreApp(CoreApp(church_false, CoreLit(LitInt(1))), CoreLit(LitInt(0)))
    result = await ev._eval_expr(expr, pmap())
    assert result == VLit(LitInt(0))


async def test_eval_omega_like():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 213, TyInt())
    id_fn = CoreLam(x, CoreVar(x))
    x2 = _id("Test", "x", 214, TyInt())
    id_fn2 = CoreLam(x2, CoreVar(x2))
    t = CoreApp(id_fn, id_fn2)
    result = await ev._eval_expr(t, pmap())
    assert isinstance(result, VClosure)


async def test_eval_deep_nesting():
    ev = (await FakeCtx.create()).evaluator
    a = _id("Test", "a", 215, TyInt())
    b = _id("Test", "b", 216, TyInt())
    c = _id("Test", "c", 217, TyInt())
    nested = CoreLam(a, CoreLam(b, CoreLam(c, CoreVar(a))))
    t = CoreApp(
        CoreApp(CoreApp(nested, CoreLit(LitInt(1))), CoreLit(LitInt(2))),
        CoreLit(LitInt(3)),
    )
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(1))


# =============================================================================
# Ported from elab2: let patterns
# =============================================================================

async def test_eval_let_in_body():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 220, TyInt())
    y = _id("Test", "y", 221, TyInt())
    inner = CoreLet(NonRec(y, CoreLit(LitInt(2))), CoreVar(x))
    t = CoreLet(NonRec(x, CoreLit(LitInt(1))), inner)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(1))


async def test_eval_let_shadow():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 222, TyInt())
    x2 = _id("Test", "x", 223, TyInt())
    inner = CoreLet(NonRec(x2, CoreLit(LitInt(2))), CoreVar(x2))
    t = CoreLet(NonRec(x, CoreLit(LitInt(1))), inner)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(2))


async def test_eval_let_with_lambda():
    ev = (await FakeCtx.create()).evaluator
    f = _id("Test", "f", 224, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 225, TyInt())
    id_fn = CoreLam(x, CoreVar(x))
    t = CoreLet(NonRec(f, id_fn), CoreApp(CoreVar(f), CoreLit(LitInt(42))))
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(42))


async def test_eval_let_expr_uses_outer():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 226, TyInt())
    y = _id("Test", "y", 227, TyInt())
    inner = CoreLet(NonRec(y, CoreVar(x)), CoreVar(y))
    t = CoreLet(NonRec(x, CoreLit(LitInt(10))), inner)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(10))


async def test_eval_let_recursive_factorial():
    r"""let rec f n = case n of 0 -> 1; _ -> * n (f (- n 1)) in f 5 => 120"""
    ev = (await FakeCtx.create()).evaluator
    f = _id("Test", "f", 228, TyFun(TyInt(), TyInt()))
    n = _id("Test", "n", 229, TyInt())
    s = _id("Test", "s", 230, TyInt())
    minus_id = Id(BUILTIN_INT_MINUS, TyInt())
    mul_id = Id(BUILTIN_INT_MULTIPLY, TyInt())
    n_minus_1 = CoreApp(CoreApp(CoreVar(minus_id), CoreVar(n)), CoreLit(LitInt(1)))
    f_body = CoreCase(
        scrut=CoreVar(n),
        var=s,
        res_ty=TyInt(),
        alts=[
            (LitAlt(LitInt(0)), CoreLit(LitInt(1))),
            (DefaultAlt(), CoreApp(
                CoreApp(CoreVar(mul_id), CoreVar(n)),
                CoreApp(CoreVar(f), n_minus_1),
            )),
        ],
    )
    lam = CoreLam(n, f_body)
    t = CoreLet(Rec([(f, lam)]), CoreApp(CoreVar(f), CoreLit(LitInt(5))))
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(120))


# =============================================================================
# Ported from elab2: case expressions (lit, data, fallthrough, no-match)
# =============================================================================

async def test_eval_case_lit_second():
    ev = (await FakeCtx.create()).evaluator
    s = _id("Test", "s", 240, TyInt())
    case_expr = CoreCase(
        scrut=CoreLit(LitInt(2)),
        var=s,
        res_ty=TyInt(),
        alts=[
            (LitAlt(LitInt(1)), CoreLit(LitInt(10))),
            (LitAlt(LitInt(2)), CoreLit(LitInt(20))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(20))


async def test_eval_case_data_with_fields_second():
    ev = (await FakeCtx.create()).evaluator
    a = _id("Test", "a", 241, TyInt())
    b = _id("Test", "b", 242, TyInt())
    s = _id("Test", "s", 243, TyInt())
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    scrut = CoreApp(CoreApp(CoreVar(pair_id), CoreLit(LitInt(3))), CoreLit(LitInt(4)))
    case_expr = CoreCase(
        scrut=scrut,
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_PAIR_MKPAIR, tag=MKPAIR_TAG, vars=[a, b]), CoreVar(b)),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(4))


async def test_eval_case_nested_data():
    ev = (await FakeCtx.create()).evaluator
    a = _id("Test", "a", 244, TyInt())
    b = _id("Test", "b", 245, TyInt())
    x = _id("Test", "x", 246, TyInt())
    s = _id("Test", "s", 247, TyInt())
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    pair_val = CoreApp(
        CoreApp(CoreVar(pair_id), CoreLit(LitInt(10))),
        CoreLit(LitInt(20)),
    )
    case_expr = CoreCase(
        scrut=CoreVar(x),
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_PAIR_MKPAIR, tag=MKPAIR_TAG, vars=[a, b]), CoreVar(a)),
        ],
    )
    t = CoreLet(NonRec(x, pair_val), case_expr)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(10))


async def test_eval_case_data_fallthrough():
    ev = (await FakeCtx.create()).evaluator
    h = _id("Test", "h", 248, TyInt())
    t_var = _id("Test", "t", 249, TyInt())
    s = _id("Test", "s", 250, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    case_expr = CoreCase(
        scrut=CoreVar(nil_id),
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_LIST_CONS, tag=CONS_TAG, vars=[h, t_var]), CoreVar(h)),
            (DataAlt(con=BUILTIN_LIST_NIL, tag=NIL_TAG, vars=[]), CoreLit(LitInt(0))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(0))


async def test_eval_case_no_match():
    ev = (await FakeCtx.create()).evaluator
    s = _id("Test", "s", 251, TyInt())
    case_expr = CoreCase(
        scrut=CoreLit(LitInt(3)),
        var=s,
        res_ty=TyInt(),
        alts=[
            (LitAlt(LitInt(1)), CoreLit(LitInt(10))),
            (LitAlt(LitInt(2)), CoreLit(LitInt(20))),
        ],
    )
    with pytest.raises(Exception, match="no matching case"):
        await ev._eval_expr(case_expr, pmap())


# =============================================================================
# Ported from elab2: data constructors (nested cons, nested pair)
# =============================================================================

async def test_eval_cons_nested():
    ev = (await FakeCtx.create()).evaluator
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    inner = CoreApp(
        CoreApp(CoreVar(cons_id), CoreLit(LitInt(2))),
        CoreVar(nil_id),
    )
    outer = CoreApp(CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))), inner)
    result = await ev._eval_expr(outer, pmap())
    assert isinstance(result, VData)
    assert result.tag == CONS_TAG
    assert result.vals[0] == VLit(LitInt(1))
    assert isinstance(result.vals[1], VData)
    assert result.vals[1].tag == CONS_TAG


async def test_eval_pair_nested():
    ev = (await FakeCtx.create()).evaluator
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    inner = CoreApp(
        CoreApp(CoreVar(pair_id), CoreLit(LitInt(1))),
        CoreLit(LitInt(2)),
    )
    outer = CoreApp(CoreApp(CoreVar(pair_id), inner), CoreLit(LitInt(3)))
    result = await ev._eval_expr(outer, pmap())
    assert isinstance(result, VData)
    assert result.tag == MKPAIR_TAG
    assert isinstance(result.vals[0], VData)
    assert result.vals[0].vals[0] == VLit(LitInt(1))
    assert result.vals[0].vals[1] == VLit(LitInt(2))
    assert result.vals[1] == VLit(LitInt(3))


# =============================================================================
# Ported from elab2: ifte (case on bool)
# =============================================================================

async def test_eval_ifte_true():
    ev = (await FakeCtx.create()).evaluator
    s = _id("Test", "s", 260, TyInt())
    true_id = Id(BUILTIN_TRUE, TyInt())
    case_expr = CoreCase(
        scrut=CoreVar(true_id),
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), CoreLit(LitInt(1))),
            (DefaultAlt(), CoreLit(LitInt(0))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(1))


async def test_eval_ifte_false():
    ev = (await FakeCtx.create()).evaluator
    s = _id("Test", "s", 261, TyInt())
    false_id = Id(BUILTIN_FALSE, TyInt())
    case_expr = CoreCase(
        scrut=CoreVar(false_id),
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), CoreLit(LitInt(1))),
            (DefaultAlt(), CoreLit(LitInt(0))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(0))


async def test_eval_ifte_nested():
    ev = (await FakeCtx.create()).evaluator
    s1 = _id("Test", "s1", 262, TyInt())
    s2 = _id("Test", "s2", 263, TyInt())
    true_id = Id(BUILTIN_TRUE, TyInt())
    false_id = Id(BUILTIN_FALSE, TyInt())
    inner_case = CoreCase(
        scrut=CoreVar(false_id),
        var=s2,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), CoreLit(LitInt(1))),
            (DefaultAlt(), CoreLit(LitInt(2))),
        ],
    )
    outer_case = CoreCase(
        scrut=CoreVar(true_id),
        var=s1,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), inner_case),
            (DefaultAlt(), CoreLit(LitInt(3))),
        ],
    )
    result = await ev._eval_expr(outer_case, pmap())
    assert result == VLit(LitInt(2))


async def test_eval_ifte_with_exprs():
    ev = (await FakeCtx.create()).evaluator
    b = _id("Test", "b", 264, TyInt())
    s = _id("Test", "s", 265, TyInt())
    true_id = Id(BUILTIN_TRUE, TyInt())
    mkunit_id = Id(BUILTIN_MK_UNIT, TyInt())
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    pair_val = CoreApp(
        CoreApp(CoreVar(pair_id), CoreLit(LitInt(1))),
        CoreLit(LitInt(2)),
    )
    case_expr = CoreCase(
        scrut=CoreVar(b),
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_TRUE, tag=TRUE_TAG, vars=[]), pair_val),
            (DefaultAlt(), CoreVar(mkunit_id)),
        ],
    )
    t = CoreLet(NonRec(b, CoreVar(true_id)), case_expr)
    result = await ev._eval_expr(t, pmap())
    assert isinstance(result, VData)
    assert result.tag == MKPAIR_TAG
    assert result.vals == [VLit(LitInt(1)), VLit(LitInt(2))]


# =============================================================================
# Ported from elab2: case on list (head/tail destructuring)
# =============================================================================

async def test_eval_case_cons_head():
    ev = (await FakeCtx.create()).evaluator
    h = _id("Test", "h", 270, TyInt())
    t_var = _id("Test", "t", 271, TyInt())
    s = _id("Test", "s", 272, TyInt())
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    scrut = CoreApp(
        CoreApp(CoreVar(cons_id), CoreLit(LitInt(42))),
        CoreVar(nil_id),
    )
    case_expr = CoreCase(
        scrut=scrut,
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_LIST_CONS, tag=CONS_TAG, vars=[h, t_var]), CoreVar(h)),
            (DataAlt(con=BUILTIN_LIST_NIL, tag=NIL_TAG, vars=[]), CoreLit(LitInt(0))),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(42))


async def test_eval_case_cons_tail():
    ev = (await FakeCtx.create()).evaluator
    h = _id("Test", "h", 273, TyInt())
    t_var = _id("Test", "t", 274, TyInt())
    s = _id("Test", "s", 275, TyInt())
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    scrut = CoreApp(
        CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))),
        CoreVar(nil_id),
    )
    case_expr = CoreCase(
        scrut=scrut,
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_LIST_CONS, tag=CONS_TAG, vars=[h, t_var]), CoreVar(t_var)),
            (DataAlt(con=BUILTIN_LIST_NIL, tag=NIL_TAG, vars=[]), CoreVar(nil_id)),
        ],
    )
    result = await ev._eval_expr(case_expr, pmap())
    assert isinstance(result, VData)
    assert result.tag == NIL_TAG


# =============================================================================
# Ported from elab2: primops in let
# =============================================================================

async def test_eval_primop_in_let():
    ev = (await FakeCtx.create()).evaluator
    x = _id("Test", "x", 280, TyInt())
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    mul_id = Id(BUILTIN_INT_MULTIPLY, TyInt())
    x_val = CoreApp(CoreApp(CoreVar(plus_id), CoreLit(LitInt(1))), CoreLit(LitInt(2)))
    body = CoreApp(CoreApp(CoreVar(mul_id), CoreVar(x)), CoreLit(LitInt(10)))
    t = CoreLet(NonRec(x, x_val), body)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(30))


# =============================================================================
# Ported from elab2: partial application
# =============================================================================

async def test_eval_partial_primop_via_let():
    ev = (await FakeCtx.create()).evaluator
    add1 = _id("Test", "add1", 290, TyFun(TyInt(), TyInt()))
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    add1_val = CoreApp(CoreVar(plus_id), CoreLit(LitInt(1)))
    body = CoreApp(CoreVar(add1), CoreLit(LitInt(2)))
    t = CoreLet(NonRec(add1, add1_val), body)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(3))


async def test_eval_partial_primop_passed_to_lambda():
    ev = (await FakeCtx.create()).evaluator
    f = _id("Test", "f", 291, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 292, TyInt())
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    lam = CoreLam(f, CoreApp(CoreVar(f), CoreLit(LitInt(5))))
    arg = CoreApp(CoreVar(plus_id), CoreLit(LitInt(3)))
    t = CoreApp(lam, arg)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(8))


async def test_eval_partial_data_via_let():
    ev = (await FakeCtx.create()).evaluator
    mkpair = _id("Test", "mkpair", 293, TyInt())
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    mkpair_val = CoreApp(CoreVar(pair_id), CoreLit(LitInt(1)))
    body = CoreApp(CoreVar(mkpair), CoreLit(LitInt(2)))
    t = CoreLet(NonRec(mkpair, mkpair_val), body)
    result = await ev._eval_expr(t, pmap())
    assert isinstance(result, VData)
    assert result.tag == MKPAIR_TAG
    assert result.vals == [VLit(LitInt(1)), VLit(LitInt(2))]


async def test_eval_partial_data_in_case():
    ev = (await FakeCtx.create()).evaluator
    a = _id("Test", "a", 294, TyInt())
    b = _id("Test", "b", 295, TyInt())
    mk = _id("Test", "mk", 296, TyInt())
    s = _id("Test", "s", 297, TyInt())
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    mk_val = CoreApp(CoreVar(pair_id), CoreLit(LitInt(10)))
    app_mk = CoreApp(CoreVar(mk), CoreLit(LitInt(20)))
    case_body = CoreCase(
        scrut=app_mk,
        var=s,
        res_ty=TyInt(),
        alts=[
            (DataAlt(con=BUILTIN_PAIR_MKPAIR, tag=MKPAIR_TAG, vars=[a, b]),
             CoreApp(CoreApp(CoreVar(plus_id), CoreVar(a)), CoreVar(b))),
        ],
    )
    t = CoreLet(NonRec(mk, mk_val), case_body)
    result = await ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(30))


async def test_eval_partial_data_passed_to_lambda():
    ev = (await FakeCtx.create()).evaluator
    f = _id("Test", "f", 298, TyFun(TyInt(), TyInt()))
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    lam = CoreLam(f, CoreApp(CoreVar(f), CoreLit(LitInt(99))))
    arg = CoreApp(CoreVar(cons_id), CoreLit(LitInt(1)))
    t = CoreApp(lam, arg)
    result = await ev._eval_expr(t, pmap())
    assert isinstance(result, VData)
    assert result.tag == CONS_TAG
    assert result.vals == [VLit(LitInt(1)), VLit(LitInt(99))]
