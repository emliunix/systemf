"""Tests for TcCtx infrastructure and type-level utilities.

Ported from elab2 non-term typecheck tests.
"""
import pytest

from systemf.elab3.tc_ctx import TcCtx, binders_of_ty
from systemf.elab3.types.ty import (
    BoundTv,
    MetaTv,
    Name,
    Ref,
    SkolemTv,
    Ty,
    TyConApp,
    TyForall,
    TyFun,
    TyInt,
    TyString,
    get_free_vars,
    get_meta_vars,
    zonk_type,
)
from systemf.elab3.types.tything import ACon, ATyCon, TyThing
from systemf.elab3.types.tc import Infer
from systemf.utils.uniq import Uniq


# =============================================================================
# Fake TcCtx for testing base class behaviour
# =============================================================================

class FakeCtx(TcCtx):
    def lookup_gbl(self, name: Name) -> TyThing:
        return ATyCon(name=name, tyvars=[], constructors=[], metas=None)


def _name(surface: str, unique: int, mod: str = "Test") -> Name:
    return Name(mod, surface, unique)


# =============================================================================
# TcCtx environment management
# =============================================================================

def test_extend_env_adds_and_removes():
    ctx = FakeCtx("Test", Uniq(1))
    n = _name("x", 10)
    thing = ATyCon(name=n, tyvars=[], constructors=[], metas=None)

    assert ctx.lookup_local(n) is None

    with ctx.extend_env([(n, thing)]):
        assert ctx.lookup_local(n) is thing

    assert ctx.lookup_local(n) is None


def test_push_level_increments_and_restores():
    ctx = FakeCtx("Test", Uniq(1))
    assert ctx.tc_level == 0

    with ctx.push_level():
        assert ctx.tc_level == 1
        with ctx.push_level():
            assert ctx.tc_level == 2
        assert ctx.tc_level == 1

    assert ctx.tc_level == 0


def test_lookup_local_vs_lookup():
    ctx = FakeCtx("Test", Uniq(1))
    local_n = _name("local", 10, "Test")
    gbl_n = _name("gbl", 20, "Other")
    thing = ATyCon(name=local_n, tyvars=[], constructors=[], metas=None)

    ctx.type_env[local_n] = thing

    assert ctx.lookup_local(local_n) is thing
    assert ctx.lookup(local_n) is thing

    # lookup on non-local falls back to lookup_gbl
    result = ctx.lookup(gbl_n)
    assert isinstance(result, ATyCon)


def test_lookup_raises_for_missing_local_in_same_module():
    ctx = FakeCtx("Test", Uniq(1))
    missing = _name("missing", 10, "Test")

    with pytest.raises(Exception, match="local name not found"):
        ctx.lookup(missing)


def test_lookup_tycon_returns_atycon():
    ctx = FakeCtx("Test", Uniq(1))
    n = _name("Bool", 10)
    tycon = ATyCon(name=n, tyvars=[], constructors=[], metas=None)
    ctx.type_env[n] = tycon

    assert ctx.lookup_tycon(n) is tycon


def test_lookup_tycon_raises_for_wrong_type():
    ctx = FakeCtx("Test", Uniq(1))
    n = _name("x", 10)
    con = ACon(name=n, tag=0, arity=0, field_types=[], parent=n, metas=None)
    ctx.type_env[n] = con

    with pytest.raises(Exception, match="Expected tycon"):
        ctx.lookup_tycon(n)


def test_lookup_datacon_returns_acon():
    ctx = FakeCtx("Test", Uniq(1))
    n = _name("True", 10)
    parent = _name("Bool", 11)
    con = ACon(name=n, tag=0, arity=0, field_types=[], parent=parent, metas=None)
    ctx.type_env[n] = con

    assert ctx.lookup_datacon(n) is con


def test_lookup_datacon_raises_for_wrong_type():
    ctx = FakeCtx("Test", Uniq(1))
    n = _name("Bool", 10)
    tycon = ATyCon(name=n, tyvars=[], constructors=[], metas=None)
    ctx.type_env[n] = tycon

    with pytest.raises(Exception, match="Expected datacon"):
        ctx.lookup_datacon(n)


# =============================================================================
# TcCtx variable creation
# =============================================================================

def test_make_meta_uses_current_level():
    ctx = FakeCtx("Test", Uniq(1))
    m = ctx.make_meta()
    assert isinstance(m, MetaTv)
    assert m.level == 0

    with ctx.push_level():
        m2 = ctx.make_meta()
        assert m2.level == 1

        m3 = ctx.make_meta(gv_lvl=5)
        assert m3.level == 5


def test_make_skolem_uses_current_level():
    ctx = FakeCtx("Test", Uniq(1))
    n = _name("a", 10)
    sk = ctx.make_skolem(n)
    assert isinstance(sk, SkolemTv)
    assert sk.level == 0

    with ctx.push_level():
        sk2 = ctx.make_skolem(n)
        assert sk2.level == 1

        sk3 = ctx.make_skolem(n, gv_lvl=3)
        assert sk3.level == 3


def test_make_skolem_with_callable_name():
    ctx = FakeCtx("Test", Uniq(1))
    sk = ctx.make_skolem(lambda i: f"sk{i}")
    assert isinstance(sk, SkolemTv)
    assert sk.name.surface.startswith("sk")


def test_make_infer_uses_current_level():
    ctx = FakeCtx("Test", Uniq(1))
    inf = ctx.make_infer()
    assert isinstance(inf, Infer)
    assert inf.lvl == 0

    with ctx.push_level():
        inf2 = ctx.make_infer()
        assert inf2.lvl == 1


# =============================================================================
# get_free_vars
# =============================================================================

def test_get_free_vars_excludes_bound():
    """get_free_vars returns only free variables, excluding nested forall bound vars."""
    a = BoundTv(name=_name("a", 1))
    b = BoundTv(name=_name("b", 2))
    sk = SkolemTv(name=_name("sk1", 3), uniq=3, level=0)

    # \forall a. a -> b -> sk1
    ty = TyForall([a], TyFun(a, TyFun(b, sk)))
    result = get_free_vars([ty])

    assert a not in result
    assert b in result
    assert sk in result


def test_get_free_vars_collects_across_multiple_types():
    a = BoundTv(name=_name("a", 1))
    b = BoundTv(name=_name("b", 2))
    ty1 = TyFun(a, TyInt())
    ty2 = TyFun(b, TyInt())

    result = get_free_vars([ty1, ty2])
    assert a in result
    assert b in result


# =============================================================================
# get_meta_vars
# =============================================================================

def test_get_meta_vars_returns_unbound_metas():
    """get_meta_vars returns only unbound meta variables."""
    m1 = MetaTv(uniq=1, level=0, ref=Ref())
    m2 = MetaTv(uniq=2, level=0, ref=Ref(TyInt()))
    ty = TyFun(m1, m2)

    result = get_meta_vars([ty])
    assert m1 in result
    assert m2 not in result


def test_get_meta_vars_excludes_bound_by_forall():
    """Meta vars inside a forall are still returned (they're not bound by forall)."""
    a = BoundTv(name=_name("a", 1))
    m = MetaTv(uniq=1, level=0, ref=Ref())
    ty = TyForall([a], TyFun(a, m))

    result = get_meta_vars([ty])
    assert m in result


# =============================================================================
# zonk_type
# =============================================================================

def test_zonk_type_resolves_bound_meta():
    """zonk_type follows meta refs to their final type."""
    m = MetaTv(uniq=1, level=0, ref=Ref(TyInt()))
    ty = TyFun(m, TyString())

    result = zonk_type(ty)
    assert result == TyFun(TyInt(), TyString())


def test_zonk_type_shortcircuits_chains():
    """zonk_type compresses long chains of meta variables."""
    m3 = MetaTv(uniq=3, level=0, ref=Ref(TyInt()))
    m1 = MetaTv(uniq=1, level=0, ref=Ref(m3))

    result = zonk_type(m1)
    assert result == TyInt()
    # Path compression: m1 should now point directly to Int
    assert m1.ref.get() == TyInt()


def test_zonk_type_leaves_unbound_meta():
    m = MetaTv(uniq=1, level=0, ref=Ref())
    result = zonk_type(m)
    assert result == m


def test_zonk_type_traverses_forall():
    a = BoundTv(name=_name("a", 1))
    m = MetaTv(uniq=2, level=0, ref=Ref(TyInt()))
    ty = TyForall([a], TyFun(a, m))

    result = zonk_type(ty)
    assert result == TyForall([a], TyFun(a, TyInt()))


# =============================================================================
# Type repr (ported from elab2 show_prec)
# =============================================================================

def test_ty_repr_int():
    assert repr(TyInt()) == "Int"


def test_ty_repr_string():
    assert repr(TyString()) == "String"


def test_ty_repr_fun():
    a = BoundTv(name=_name("a", 1))
    ty = TyFun(a, TyInt())
    assert repr(ty) == "a -> Int"


def test_ty_repr_fun_parens():
    """Function types inside higher precedence contexts get parentheses."""
    ty = TyFun(TyInt(), TyFun(TyInt(), TyInt()))
    assert repr(ty) == "Int -> Int -> Int"


def test_ty_repr_forall():
    a = BoundTv(name=_name("a", 1))
    ty = TyForall([a], TyFun(a, TyInt()))
    assert repr(ty) == "forall a. a -> Int"


def test_ty_repr_meta():
    m = MetaTv(uniq=42, level=0, ref=Ref())
    assert repr(m) == "?42"


def test_ty_repr_tyconapp():
    list_name = _name("List", 10)
    a = BoundTv(name=_name("a", 1))
    ty = TyConApp(name=list_name, args=[a])
    assert repr(ty) == "List a"


def test_ty_repr_skolem():
    sk = SkolemTv(name=_name("s", 1), uniq=1, level=0)
    assert repr(sk) == "$s"


# =============================================================================
# binders_of_ty
# =============================================================================

def test_binders_of_ty_collects_forall_vars():
    a = BoundTv(name=_name("a", 1))
    b = BoundTv(name=_name("b", 2))
    ty = TyForall([a, b], TyFun(a, b))

    result = binders_of_ty(ty)
    assert a in result
    assert b in result


def test_binders_of_ty_nested_forall():
    a = BoundTv(name=_name("a", 1))
    b = BoundTv(name=_name("b", 2))
    ty = TyForall([a], TyForall([b], TyFun(a, b)))

    result = binders_of_ty(ty)
    assert a in result
    assert b in result


def test_binders_of_ty_no_binders():
    ty = TyFun(TyInt(), TyInt())
    assert binders_of_ty(ty) == []
