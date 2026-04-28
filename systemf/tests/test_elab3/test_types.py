from __future__ import annotations

from systemf.elab3.types.ty import (
    BoundTv, Id, LitInt, LitString, MetaTv, Name, Ref,
    TyConApp, TyForall, TyFun, TyInt, TyString, TyVar, subst_ty, zonk_type,
    get_meta_vars,
)
from systemf.elab3.types.tything import AnId, ATyCon, ACon, TyThing
from systemf.elab3.types.core import CoreLet, CoreLit, CoreTm, CoreVar, NonRec, Rec
from systemf.elab3.builtins import BUILTIN_BOOL


def mk_name(surface: str, mod: str, unique: int) -> Name:
    return Name(mod=mod, surface=surface, unique=unique)


def mk_id(surface: str, mod: str, unique: int, ty: TyInt | TyVar = TyInt()) -> Id:
    return Id(name=mk_name(surface, mod, unique), ty=ty)


def test_anid_creation():
    name = mk_name("id", "Test", 1)
    ty = TyInt()
    anid = AnId.create(Id(name=name, ty=ty))
    assert anid.name == name
    assert anid.id.ty == ty


def test_atycon_creation():
    name = mk_name("Bool", "Builtin", 2)
    tycon = ATyCon(name=name, tyvars=[], constructors=[], metas=None)
    assert tycon.name == name
    assert tycon.tyvars == []
    assert tycon.constructors == []


def test_acon_creation():
    parent = mk_name("List", "Builtin", 4)
    con_name = mk_name("Cons", "Builtin", 100)
    acon = ACon(
        name=con_name,
        tag=0,
        arity=2,
        field_types=[],
        parent=parent,
        metas=None,
    )
    assert acon.parent == parent
    assert acon.tag == 0
    assert acon.arity == 2


def test_corelet_nonrec():
    x_id = mk_id("x", "Test", 1)
    body = CoreVar(id=x_id)
    expr = CoreLit(value=LitInt(value=42))
    let_expr = CoreLet(binding=NonRec(binder=x_id, expr=expr), body=body)
    assert isinstance(let_expr.binding, NonRec)
    assert let_expr.binding.binder == x_id


def test_corelet_rec():
    x_id = mk_id("x", "Test", 1)
    y_id = mk_id("y", "Test", 2)
    body = CoreVar(id=x_id)
    bindings: list[tuple[Id, CoreTm]] = [
        (x_id, CoreLit(value=LitInt(value=1))),
        (y_id, CoreLit(value=LitInt(value=2))),
    ]
    let_expr = CoreLet(binding=Rec(bindings=bindings), body=body)
    assert isinstance(let_expr.binding, Rec)
    assert len(let_expr.binding.bindings) == 2


# ---
# subst_ty — TyConApp case

def test_subst_ty_substitutes_args_in_tyconapp():
    """Variables in TyConApp args are substituted."""
    list_name = mk_name("List", "Builtin", 10)
    a = BoundTv(name=mk_name("a", "Test", 1))
    # List a  =>  subst [a -> Int]  =>  List Int
    ty = TyConApp(name=list_name, args=[a])
    res = subst_ty([a], [TyInt()], ty)
    assert res == TyConApp(name=list_name, args=[TyInt()])


def test_subst_ty_substitutes_multiple_args_in_tyconapp():
    """All args of a TyConApp are substituted."""
    either_name = mk_name("Either", "Builtin", 11)
    a = BoundTv(name=mk_name("a", "Test", 1))
    b = BoundTv(name=mk_name("b", "Test", 2))
    # Either a b  =>  subst [a -> Int, b -> String]  =>  Either Int String
    ty = TyConApp(name=either_name, args=[a, b])
    res = subst_ty([a, b], [TyInt(), TyString()], ty)
    assert res == TyConApp(name=either_name, args=[TyInt(), TyString()])


# ---
# subst_ty — ported from elab2 test_types.py

def test_subst_ty_replaces_vars_in_type():
    a = BoundTv(name=mk_name("a", "Test", 20))
    ty = TyFun(a, TyInt())
    res = subst_ty([a], [TyInt()], ty)
    assert res == TyFun(TyInt(), TyInt())


def test_subst_ty_respects_forall_shadowing():
    a = BoundTv(name=mk_name("a", "Test", 21))
    forall_ty = TyForall([a], TyFun(a, TyInt()))
    res = subst_ty([a], [TyInt()], forall_ty)
    assert res == forall_ty


def test_subst_ty_ignores_unrelated_vars():
    a = BoundTv(name=mk_name("a", "Test", 22))
    b = BoundTv(name=mk_name("b", "Test", 23))
    ty = TyFun(a, TyInt())
    res = subst_ty([b], [TyInt()], ty)
    assert res == ty


def test_subst_ty_substitutes_free_vars_in_nested_forall():
    a = BoundTv(name=mk_name("a", "Test", 24))
    b = BoundTv(name=mk_name("b", "Test", 25))
    forall_ty = TyForall([a], TyFun(b, a))
    res = subst_ty([b], [TyInt()], forall_ty)
    assert res == TyForall([a], TyFun(TyInt(), a))


def test_subst_ty_arg_forall():
    a = BoundTv(name=mk_name("a", "Test", 26))
    b = BoundTv(name=mk_name("b", "Test", 27))
    ty = TyFun(TyForall([b], TyFun(a, b)), TyFun(a, b))
    res = subst_ty([a], [TyInt()], ty)
    assert res == TyFun(TyForall([b], TyFun(TyInt(), b)), TyFun(TyInt(), b))


# ---
# quantify — ported from elab2 test_tyck.py

def test_quantify_replaces_meta_vars():
    from systemf.elab3.typecheck_expr import TypeChecker
    from systemf.elab3.types.ty import MetaTv
    from systemf.utils.uniq import Uniq

    class FakeCtx:
        def __init__(self):
            self.uniq = Uniq(100)

    class FakeTcCtx(TypeChecker):
        def __init__(self):
            ctx = FakeCtx()
            super().__init__(ctx, "Test", None, None)

        def lookup_gbl(self, name):
            raise KeyError(name)

    ctx = FakeTcCtx()
    m1 = ctx.make_meta()
    m2 = ctx.make_meta()
    ty = TyFun(m1, TyFun(TyInt(), m2))
    sks, tys = ctx.quantify([m1, m2], [ty])

    assert len(sks) == 2
    a, b = sks
    expected = TyForall([a, b], TyFun(a, TyFun(TyInt(), b)))
    assert tys[0] == expected
    # Meta refs should be set to skolems
    assert m1.ref.get() == a
    assert m2.ref.get() == b


# ---
# get_meta_vars — ported from elab2 test_types.py

def test_get_meta_vars_excludes_bound():
    m_bound = MetaTv(uniq=1, level=0, ref=Ref(TyInt()))
    m_free = MetaTv(uniq=2, level=0, ref=Ref(None))
    a = BoundTv(name=mk_name("a", "Test", 30))
    ty = TyFun(TyForall([a], a), m_free)
    result = get_meta_vars([ty])
    assert m_free in result