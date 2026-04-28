"""Tests for elab3 CEK evaluator."""

import pytest

from systemf.elab3.builtins import (
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
)
from systemf.elab3.eval import (
    Evaluator,
    EvalCtx,
)
from systemf.elab3.core_extra import CoreBuilderExtra
from pyrsistent import pmap

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

class FakeCtx:
    """EvalCtx for tests.  Provides builtins; lazily evaluates user modules."""

    def __init__(self, modules: dict[str, list[Binding]] | None = None):
        self.mod_insts: dict[str, dict[Name, Val]] = {}
        self._modules_bindings = modules or {}
        self._evaling: dict[str, str | None] = {}
        self._populate_builtins()

    def _populate_builtins(self) -> None:
        from systemf.elab3 import builtins_rts as rts

        insts: dict[Name, Val] = {}

        # Data constructors — arity 0 → VData, arity > 0 → VPartial
        insts[BUILTIN_TRUE] = VData(TRUE_TAG, [])
        insts[BUILTIN_FALSE] = VData(FALSE_TAG, [])
        insts[BUILTIN_MK_UNIT] = VData(MKUNIT_TAG, [])
        insts[BUILTIN_LIST_NIL] = VData(NIL_TAG, [])
        insts[BUILTIN_LIST_CONS] = VPartial(
            BUILTIN_LIST_CONS.surface, 2, [],
            lambda args: VData(CONS_TAG, args),
        )
        insts[BUILTIN_PAIR_MKPAIR] = VPartial(
            BUILTIN_PAIR_MKPAIR.surface, 2, [],
            lambda args: VData(MKPAIR_TAG, args),
        )

        # Primitive operations
        true_val = insts[BUILTIN_TRUE]
        false_val = insts[BUILTIN_FALSE]

        def _reg(n: Name, arity: int, func):
            insts[n] = VPartial(n.surface, arity, [], func)

        _reg(BUILTIN_INT_PLUS, 2, rts.int_plus)
        _reg(BUILTIN_INT_MINUS, 2, rts.int_minus)
        _reg(BUILTIN_INT_MULTIPLY, 2, rts.int_multiply)
        _reg(BUILTIN_INT_DIVIDE, 2, rts.int_divide)
        _reg(BUILTIN_INT_EQ, 2, rts.mk_int_eq(true_val, false_val))
        _reg(BUILTIN_INT_NEQ, 2, rts.mk_int_neq(true_val, false_val))
        _reg(BUILTIN_INT_LT, 2, rts.mk_int_lt(true_val, false_val))
        _reg(BUILTIN_INT_GT, 2, rts.mk_int_gt(true_val, false_val))
        _reg(BUILTIN_INT_LE, 2, rts.mk_int_le(true_val, false_val))
        _reg(BUILTIN_INT_GE, 2, rts.mk_int_ge(true_val, false_val))
        _reg(BUILTIN_STRING_CONCAT, 2, rts.string_concat)
        _reg(BUILTIN_ERROR, 1, rts.error)

        self.mod_insts["builtins"] = insts

    @property
    def core_extra(self) -> CoreBuilderExtra:
        return CoreBuilderExtra(self)

    def lookup(self, name: Name) -> TyThing:
        # Minimal lookup for CoreBuilderExtra in tests
        from systemf.elab3.types.tything import ACon, ATyCon, AnId
        from systemf.elab3.types.ty import TyVar, TyConApp, TyForall, TyFun
        import functools
        
        if name == BUILTIN_PAIR_MKPAIR:
            from systemf.elab3.types.ty import BoundTv
            a = BoundTv(name=Name("builtins", "a", 1001))
            b = BoundTv(name=Name("builtins", "b", 1002))
            pair_tycon = ATyCon(
                name=BUILTIN_PAIR,
                tyvars=[a, b],
                constructors=[ACon(
                    name=BUILTIN_PAIR_MKPAIR,
                    tag=0,
                    arity=2,
                    field_types=[a, b],
                    parent=BUILTIN_PAIR,
                )],
            )
            return pair_tycon.constructors[0]
        if name == BUILTIN_PAIR:
            from systemf.elab3.types.ty import BoundTv
            a = BoundTv(name=Name("builtins", "a", 1001))
            b = BoundTv(name=Name("builtins", "b", 1002))
            return ATyCon(
                name=BUILTIN_PAIR,
                tyvars=[a, b],
                constructors=[ACon(
                    name=BUILTIN_PAIR_MKPAIR,
                    tag=0,
                    arity=2,
                    field_types=[a, b],
                    parent=BUILTIN_PAIR,
                )],
            )
        for mod in self.mod_insts.values():
            if name in mod:
                val = mod[name]
                if isinstance(val, VData):
                    # Return a synthetic AnId for data constructors
                    return AnId(name=name, id=Id(name=name, ty=TyConApp(BUILTIN_PAIR, [])))
        raise Exception(f"Name {name} not found")

    def _ensure_evaluated(self, mod_name: str) -> None:
        if mod_name in self.mod_insts:
            return
        if mod_name in self._evaling:
            raise Exception(
                f"Cyclic evaluation detected: {_build_chain(self._evaling, mod_name)}"
            )

        bindings_list = self._modules_bindings.get(mod_name)
        if bindings_list is None:
            raise Exception(f"module not found: {mod_name}")

        self._evaling[mod_name] = None
        try:
            ev = Evaluator(self)
            mod = Module(
                name=mod_name,
                tythings=[],
                bindings=bindings_list,
                exports=[],
                _tythings_map={},
            )
            mod_inst: dict[Name, Val] = {}
            mod_inst = ev.eval_mod(mod, mod_inst)
            self.mod_insts[mod_name] = mod_inst
        finally:
            del self._evaling[mod_name]

    def lookup_gbl(self, name: Name) -> Val:
        cached = self.mod_insts.get(name.mod, pmap()).get(name)
        if cached is not None:
            return cached
        self._ensure_evaluated(name.mod)
        return self.mod_insts[name.mod][name]


# =============================================================================
# Core expression evaluation (via _eval_expr)
# =============================================================================

def test_eval_lit():
    ev = Evaluator(FakeCtx())
    result = ev._eval_expr(CoreLit(LitInt(42)), pmap())
    assert isinstance(result, VLit)
    assert result.lit == LitInt(42)


def test_eval_lambda():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 1, TyInt())
    lam = CoreLam(x, CoreVar(x))
    result = ev._eval_expr(lam, pmap())
    assert isinstance(result, VClosure)
    assert result.param.name.unique == x.name.unique


def test_eval_app():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 1, TyInt())
    lam = CoreLam(x, CoreVar(x))
    app = CoreApp(lam, CoreLit(LitInt(99)))
    result = ev._eval_expr(app, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == 99


def test_eval_let_nonrec():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 1, TyInt())
    let_expr = CoreLet(NonRec(x, CoreLit(LitInt(7))), CoreVar(x))
    result = ev._eval_expr(let_expr, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == 7


def test_eval_let_rec_guarded():
    r"""Recursive binding guarded by lambda: let rec f = \x -> f x in f."""
    ev = Evaluator(FakeCtx())
    f = _id("Test", "f", 1, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 2, TyInt())
    body = CoreLam(x, CoreApp(CoreVar(f), CoreVar(x)))
    expr = CoreLet(Rec([(f, body)]), CoreVar(f))
    result = ev._eval_expr(expr, pmap())
    assert isinstance(result, VClosure)


def test_eval_ty_lam_ty_app_erasure():
    """Type abstractions and applications are erased at runtime."""
    ev = Evaluator(FakeCtx())
    a = BoundTv(_name("Test", "a", 3))
    x = _id("Test", "x", 4, TyInt())
    tlam = CoreTyLam(a, CoreLam(x, CoreVar(x)))
    tapp = CoreTyApp(tlam, TyInt())
    app = CoreApp(tapp, CoreLit(LitInt(5)))
    result = ev._eval_expr(app, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == 5


# =============================================================================
# Case expressions
# =============================================================================

def test_eval_case_data_alt():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == 1


def test_eval_case_default_alt():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(42))


def test_eval_case_cons_pattern():
    """Pattern match on Cons with bound variables."""
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == 1


# =============================================================================
# Builtin resolution via CoreVar fallback
# =============================================================================

def test_builtin_int_plus():
    ev = Evaluator(FakeCtx())
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    expr = CoreApp(
        CoreApp(CoreVar(plus_id), CoreLit(LitInt(1))),
        CoreLit(LitInt(2)),
    )
    result = ev._eval_expr(expr, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == 3


def test_builtin_int_minus():
    ev = Evaluator(FakeCtx())
    minus_id = Id(BUILTIN_INT_MINUS, TyInt())
    expr = CoreApp(
        CoreApp(CoreVar(minus_id), CoreLit(LitInt(10))),
        CoreLit(LitInt(3)),
    )
    result = ev._eval_expr(expr, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == 7


def test_builtin_int_eq():
    ev = Evaluator(FakeCtx())
    eq_id = Id(BUILTIN_INT_EQ, TyInt())
    true_expr = CoreApp(
        CoreApp(CoreVar(eq_id), CoreLit(LitInt(5))),
        CoreLit(LitInt(5)),
    )
    false_expr = CoreApp(
        CoreApp(CoreVar(eq_id), CoreLit(LitInt(5))),
        CoreLit(LitInt(6)),
    )
    assert isinstance(ev._eval_expr(true_expr, pmap()), VData)
    assert ev._eval_expr(true_expr, pmap()).tag == TRUE_TAG
    assert isinstance(ev._eval_expr(false_expr, pmap()), VData)
    assert ev._eval_expr(false_expr, pmap()).tag == FALSE_TAG


def test_builtin_string_concat():
    ev = Evaluator(FakeCtx())
    concat_id = Id(BUILTIN_STRING_CONCAT, TyInt())
    expr = CoreApp(
        CoreApp(CoreVar(concat_id), CoreLit(LitString("hello"))),
        CoreLit(LitString(" world")),
    )
    result = ev._eval_expr(expr, pmap())
    assert isinstance(result, VLit)
    assert result.lit.value == "hello world"


def test_builtin_bool_constructors():
    ev = Evaluator(FakeCtx())
    true_id = Id(BUILTIN_TRUE, TyInt())
    false_id = Id(BUILTIN_FALSE, TyInt())
    assert isinstance(ev._eval_expr(CoreVar(true_id), pmap()), VData)
    assert isinstance(ev._eval_expr(CoreVar(false_id), pmap()), VData)


def test_builtin_list_nil():
    ev = Evaluator(FakeCtx())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    result = ev._eval_expr(CoreVar(nil_id), pmap())
    assert isinstance(result, VData)
    assert result.tag == NIL_TAG


def test_builtin_partial_saturation():
    """Cons partially applied, then fully applied."""
    ev = Evaluator(FakeCtx())
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    # Cons 1 -> VPartial
    p1 = ev._eval_expr(CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))), pmap())
    assert isinstance(p1, VPartial)
    assert p1.done == [VLit(LitInt(1))]
    # (Cons 1) Nil -> VData
    full = ev._eval_expr(
        CoreApp(CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))), CoreVar(nil_id)),
        {},
    )
    assert isinstance(full, VData)
    assert full.tag == CONS_TAG


# =============================================================================
# Module loading via lookup_gbl / eval_mod
# =============================================================================

def test_eval_mod_nonrec():
    a = _name("M", "a", 10)
    b = _name("M", "b", 11)
    bindings: list[Binding] = [
        NonRec(Id(a, TyInt()), CoreLit(LitInt(1))),
        NonRec(Id(b, TyInt()), CoreLit(LitInt(2))),
    ]
    ctx = FakeCtx({"M": bindings})
    assert ctx.lookup_gbl(a) == VLit(LitInt(1))
    assert ctx.lookup_gbl(b) == VLit(LitInt(2))


def test_eval_mod_rec_single_guarded():
    f = _id("M", "f", 20, TyFun(TyInt(), TyInt()))
    x = _id("M", "x", 21, TyInt())
    lam = CoreLam(x, CoreApp(CoreVar(f), CoreVar(x)))
    bindings: list[Binding] = [Rec([(f, lam)])]
    ctx = FakeCtx({"M": bindings})
    result = ctx.lookup_gbl(f.name)
    assert isinstance(result, VClosure)


def test_eval_mod_rec_multi_mutual():
    """Mutual recursion with two functions."""
    f = _id("M", "f", 30, TyFun(TyInt(), TyInt()))
    g = _id("M", "g", 31, TyFun(TyInt(), TyInt()))
    x = _id("M", "x", 32, TyInt())
    f_lam = CoreLam(x, CoreApp(CoreVar(g), CoreVar(x)))
    g_lam = CoreLam(x, CoreApp(CoreVar(f), CoreVar(x)))
    bindings: list[Binding] = [Rec([(f, f_lam), (g, g_lam)])]
    ctx = FakeCtx({"M": bindings})
    assert isinstance(ctx.lookup_gbl(f.name), VClosure)
    assert isinstance(ctx.lookup_gbl(g.name), VClosure)


def test_eval_mod_raises_on_missing_module():
    """Lookup on an unknown module raises."""
    ctx = FakeCtx()
    with pytest.raises(Exception, match="module not found"):
        ctx.lookup_gbl(_name("M", "foo", 99))


def test_eval_mod_cyclic_raises():
    """Cross-module cycles are caught by the context."""
    a_name = _name("A", "x", 50)
    b_name = _name("B", "y", 51)

    bindings_a: list[Binding] = [NonRec(Id(a_name, TyInt()), CoreVar(Id(b_name, TyInt())))]
    bindings_b: list[Binding] = [NonRec(Id(b_name, TyInt()), CoreVar(Id(a_name, TyInt())))]

    ctx = FakeCtx({
        "A": bindings_a,
        "B": bindings_b,
    })
    with pytest.raises(Exception, match="Cyclic evaluation detected"):
        ctx.lookup_gbl(a_name)


# =============================================================================
# Non-polymorphic mutual recursive functions (applied)
# =============================================================================

def test_mutual_rec_functions_applied():
    """
    f = \n -> if n == 0 then 1 else g (n - 1)
    g = \n -> if n == 0 then 2 else f (n - 1)
    f 0 -> 1
    f 1 -> g 0 -> 2
    """
    f = _id("M", "f", 60, TyFun(TyInt(), TyInt()))
    g = _id("M", "g", 61, TyFun(TyInt(), TyInt()))
    n = _id("M", "n", 62, TyInt())
    eq_id = Id(BUILTIN_INT_EQ, TyInt())
    minus_id = Id(BUILTIN_INT_MINUS, TyInt())

    zero = CoreLit(LitInt(0))
    one = CoreLit(LitInt(1))
    two = CoreLit(LitInt(2))

    # n == 0
    n_eq_0 = CoreApp(CoreApp(CoreVar(eq_id), CoreVar(n)), zero)
    # n - 1
    n_minus_1 = CoreApp(CoreApp(CoreVar(minus_id), CoreVar(n)), one)

    s = _id("M", "s", 63, TyInt())
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

    ctx = FakeCtx({"M": bindings})
    ev = Evaluator(ctx)

    # f 0 -> 1
    result_f0 = ev._eval_expr(CoreApp(CoreVar(f), zero), pmap())
    assert isinstance(result_f0, VLit)
    assert result_f0.lit.value == 1

    # f 1 -> g 0 -> 2
    result_f1 = ev._eval_expr(CoreApp(CoreVar(f), one), pmap())
    assert isinstance(result_f1, VLit)
    assert result_f1.lit.value == 2


# =============================================================================
# Primary API: eval_mod / lookup_gbl
# =============================================================================

def test_eval_mod_primary_api():
    n = _name("M", "answer", 70)
    bindings: list[Binding] = [NonRec(Id(n, TyInt()), CoreLit(LitInt(42)))]
    ctx = FakeCtx({"M": bindings})
    result = ctx.lookup_gbl(n)
    assert isinstance(result, VLit)
    assert result.lit.value == 42


# =============================================================================
# Cross-module references
# =============================================================================

def test_cross_module_reference():
    """Module B references a name from module A; auto-loading kicks in."""
    a_name = _name("A", "foo", 100)
    b_name = _name("B", "bar", 101)

    bindings_a: list[Binding] = [NonRec(Id(a_name, TyInt()), CoreLit(LitInt(100)))]
    bindings_b: list[Binding] = [NonRec(Id(b_name, TyInt()), CoreVar(Id(a_name, TyInt())))]

    ctx = FakeCtx({
        "A": bindings_a,
        "B": bindings_b,
    })
    result = ctx.lookup_gbl(b_name)
    assert isinstance(result, VLit)
    assert result.lit.value == 100


# =============================================================================
# Trap / self-reference edge cases
# =============================================================================

def test_single_rec_unguarded_self_reference_raises():
    """
    A monomorphic single-binding Rec with an unguarded self-reference
    (e.g. f = f) is non-productive and must raise.
    """
    f = _id("M", "f", 110, TyInt())
    bindings: list[Binding] = [Rec([(f, CoreVar(f))])]
    ctx = FakeCtx({"M": bindings})
    with pytest.raises(Exception, match="uninitialized letrec trap"):
        ctx.lookup_gbl(f.name)


def test_multi_rec_unguarded_mutual_reference_raises():
    """
    Mutual Rec where the first RHS immediately forces the second binder
    is non-productive and must raise.
    """
    f = _id("M", "f", 111, TyInt())
    g = _id("M", "g", 112, TyInt())
    bindings: list[Binding] = [
        Rec([(f, CoreVar(g)), (g, CoreLit(LitInt(1)))])
    ]
    ctx = FakeCtx({"M": bindings})
    with pytest.raises(Exception, match="uninitialized letrec trap"):
        ctx.lookup_gbl(f.name)


# =============================================================================
# VPartial (primops are VPartial)
# =============================================================================

def test_primops_are_vpartial():
    """Primitive operations should resolve to VPartial."""
    ctx = FakeCtx()
    result = ctx.lookup_gbl(BUILTIN_INT_PLUS)
    assert isinstance(result, VPartial)
    assert result.name == "int_plus"
    assert result.arity == 2
    assert result.done == []


# =============================================================================
# Ported from elab2: variable shadowing, closures, church encodings
# =============================================================================

def test_eval_shadow():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 200, TyInt())
    x2 = _id("Test", "x", 201, TyInt())
    inner = CoreLam(x2, CoreVar(x2))
    outer = CoreLam(x, inner)
    t = CoreApp(CoreApp(outer, CoreLit(LitInt(1))), CoreLit(LitInt(2)))
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(2))


def test_eval_closure_captures_env():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 202, TyInt())
    y = _id("Test", "y", 203, TyInt())
    outer = CoreLam(x, CoreLam(y, CoreVar(x)))
    t = CoreApp(outer, CoreLit(LitInt(10)))
    result = ev._eval_expr(t, pmap())
    assert isinstance(result, VClosure)


def test_eval_apply_returned_closure():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 204, TyInt())
    y = _id("Test", "y", 205, TyInt())
    outer = CoreLam(x, CoreLam(y, CoreVar(x)))
    t = CoreApp(CoreApp(outer, CoreLit(LitInt(10))), CoreLit(LitInt(20)))
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(10))


def test_eval_nested_application():
    ev = Evaluator(FakeCtx())
    f = _id("Test", "f", 206, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 207, TyInt())
    y = _id("Test", "y", 208, TyInt())
    apply_f = CoreLam(f, CoreLam(x, CoreApp(CoreVar(f), CoreVar(x))))
    id_fn = CoreLam(y, CoreVar(y))
    t = CoreApp(CoreApp(apply_f, id_fn), CoreLit(LitInt(7)))
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(7))


def test_eval_church_true():
    ev = Evaluator(FakeCtx())
    t_var = _id("Test", "t", 209, TyInt())
    f_var = _id("Test", "f", 210, TyInt())
    church_true = CoreLam(t_var, CoreLam(f_var, CoreVar(t_var)))
    expr = CoreApp(CoreApp(church_true, CoreLit(LitInt(1))), CoreLit(LitInt(0)))
    result = ev._eval_expr(expr, pmap())
    assert result == VLit(LitInt(1))


def test_eval_church_false():
    ev = Evaluator(FakeCtx())
    t_var = _id("Test", "t", 211, TyInt())
    f_var = _id("Test", "f", 212, TyInt())
    church_false = CoreLam(t_var, CoreLam(f_var, CoreVar(f_var)))
    expr = CoreApp(CoreApp(church_false, CoreLit(LitInt(1))), CoreLit(LitInt(0)))
    result = ev._eval_expr(expr, pmap())
    assert result == VLit(LitInt(0))


def test_eval_omega_like():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 213, TyInt())
    id_fn = CoreLam(x, CoreVar(x))
    x2 = _id("Test", "x", 214, TyInt())
    id_fn2 = CoreLam(x2, CoreVar(x2))
    t = CoreApp(id_fn, id_fn2)
    result = ev._eval_expr(t, pmap())
    assert isinstance(result, VClosure)


def test_eval_deep_nesting():
    ev = Evaluator(FakeCtx())
    a = _id("Test", "a", 215, TyInt())
    b = _id("Test", "b", 216, TyInt())
    c = _id("Test", "c", 217, TyInt())
    nested = CoreLam(a, CoreLam(b, CoreLam(c, CoreVar(a))))
    t = CoreApp(
        CoreApp(CoreApp(nested, CoreLit(LitInt(1))), CoreLit(LitInt(2))),
        CoreLit(LitInt(3)),
    )
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(1))


# =============================================================================
# Ported from elab2: let patterns
# =============================================================================

def test_eval_let_in_body():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 220, TyInt())
    y = _id("Test", "y", 221, TyInt())
    inner = CoreLet(NonRec(y, CoreLit(LitInt(2))), CoreVar(x))
    t = CoreLet(NonRec(x, CoreLit(LitInt(1))), inner)
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(1))


def test_eval_let_shadow():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 222, TyInt())
    x2 = _id("Test", "x", 223, TyInt())
    inner = CoreLet(NonRec(x2, CoreLit(LitInt(2))), CoreVar(x2))
    t = CoreLet(NonRec(x, CoreLit(LitInt(1))), inner)
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(2))


def test_eval_let_with_lambda():
    ev = Evaluator(FakeCtx())
    f = _id("Test", "f", 224, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 225, TyInt())
    id_fn = CoreLam(x, CoreVar(x))
    t = CoreLet(NonRec(f, id_fn), CoreApp(CoreVar(f), CoreLit(LitInt(42))))
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(42))


def test_eval_let_expr_uses_outer():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 226, TyInt())
    y = _id("Test", "y", 227, TyInt())
    inner = CoreLet(NonRec(y, CoreVar(x)), CoreVar(y))
    t = CoreLet(NonRec(x, CoreLit(LitInt(10))), inner)
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(10))


def test_eval_let_recursive_factorial():
    r"""let rec f n = case n of 0 -> 1; _ -> * n (f (- n 1)) in f 5 => 120"""
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(120))


# =============================================================================
# Ported from elab2: case expressions (lit, data, fallthrough, no-match)
# =============================================================================

def test_eval_case_lit_second():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(20))


def test_eval_case_data_with_fields_second():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(4))


def test_eval_case_nested_data():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(10))


def test_eval_case_data_fallthrough():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(0))


def test_eval_case_no_match():
    ev = Evaluator(FakeCtx())
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
        ev._eval_expr(case_expr, pmap())


# =============================================================================
# Ported from elab2: data constructors (nested cons, nested pair)
# =============================================================================

def test_eval_cons_nested():
    ev = Evaluator(FakeCtx())
    cons_id = Id(BUILTIN_LIST_CONS, TyInt())
    nil_id = Id(BUILTIN_LIST_NIL, TyInt())
    inner = CoreApp(
        CoreApp(CoreVar(cons_id), CoreLit(LitInt(2))),
        CoreVar(nil_id),
    )
    outer = CoreApp(CoreApp(CoreVar(cons_id), CoreLit(LitInt(1))), inner)
    result = ev._eval_expr(outer, pmap())
    assert isinstance(result, VData)
    assert result.tag == CONS_TAG
    assert result.vals[0] == VLit(LitInt(1))
    assert isinstance(result.vals[1], VData)
    assert result.vals[1].tag == CONS_TAG


def test_eval_pair_nested():
    ev = Evaluator(FakeCtx())
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    inner = CoreApp(
        CoreApp(CoreVar(pair_id), CoreLit(LitInt(1))),
        CoreLit(LitInt(2)),
    )
    outer = CoreApp(CoreApp(CoreVar(pair_id), inner), CoreLit(LitInt(3)))
    result = ev._eval_expr(outer, pmap())
    assert isinstance(result, VData)
    assert result.tag == MKPAIR_TAG
    assert isinstance(result.vals[0], VData)
    assert result.vals[0].vals[0] == VLit(LitInt(1))
    assert result.vals[0].vals[1] == VLit(LitInt(2))
    assert result.vals[1] == VLit(LitInt(3))


# =============================================================================
# Ported from elab2: ifte (case on bool)
# =============================================================================

def test_eval_ifte_true():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(1))


def test_eval_ifte_false():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(0))


def test_eval_ifte_nested():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(outer_case, pmap())
    assert result == VLit(LitInt(2))


# =============================================================================
# Ported from elab2: case on list (head/tail destructuring)
# =============================================================================

def test_eval_case_cons_head():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert result == VLit(LitInt(42))


def test_eval_case_cons_tail():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(case_expr, pmap())
    assert isinstance(result, VData)
    assert result.tag == NIL_TAG


# =============================================================================
# Ported from elab2: primops in let
# =============================================================================

def test_eval_primop_in_let():
    ev = Evaluator(FakeCtx())
    x = _id("Test", "x", 280, TyInt())
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    mul_id = Id(BUILTIN_INT_MULTIPLY, TyInt())
    x_val = CoreApp(CoreApp(CoreVar(plus_id), CoreLit(LitInt(1))), CoreLit(LitInt(2)))
    body = CoreApp(CoreApp(CoreVar(mul_id), CoreVar(x)), CoreLit(LitInt(10)))
    t = CoreLet(NonRec(x, x_val), body)
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(30))


# =============================================================================
# Ported from elab2: partial application
# =============================================================================

def test_eval_partial_primop_via_let():
    ev = Evaluator(FakeCtx())
    add1 = _id("Test", "add1", 290, TyFun(TyInt(), TyInt()))
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    add1_val = CoreApp(CoreVar(plus_id), CoreLit(LitInt(1)))
    body = CoreApp(CoreVar(add1), CoreLit(LitInt(2)))
    t = CoreLet(NonRec(add1, add1_val), body)
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(3))


def test_eval_partial_primop_passed_to_lambda():
    ev = Evaluator(FakeCtx())
    f = _id("Test", "f", 291, TyFun(TyInt(), TyInt()))
    x = _id("Test", "x", 292, TyInt())
    plus_id = Id(BUILTIN_INT_PLUS, TyInt())
    lam = CoreLam(f, CoreApp(CoreVar(f), CoreLit(LitInt(5))))
    arg = CoreApp(CoreVar(plus_id), CoreLit(LitInt(3)))
    t = CoreApp(lam, arg)
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(8))


def test_eval_partial_data_via_let():
    ev = Evaluator(FakeCtx())
    mkpair = _id("Test", "mkpair", 293, TyInt())
    pair_id = Id(BUILTIN_PAIR_MKPAIR, TyInt())
    mkpair_val = CoreApp(CoreVar(pair_id), CoreLit(LitInt(1)))
    body = CoreApp(CoreVar(mkpair), CoreLit(LitInt(2)))
    t = CoreLet(NonRec(mkpair, mkpair_val), body)
    result = ev._eval_expr(t, pmap())
    assert isinstance(result, VData)
    assert result.tag == MKPAIR_TAG
    assert result.vals == [VLit(LitInt(1)), VLit(LitInt(2))]


def test_eval_partial_data_in_case():
    ev = Evaluator(FakeCtx())
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
    result = ev._eval_expr(t, pmap())
    assert result == VLit(LitInt(30))
