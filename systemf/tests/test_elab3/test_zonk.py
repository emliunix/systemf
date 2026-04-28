from __future__ import annotations
from systemf.elab3.types.ty import (
    BoundTv,
    MetaTv,
    Name,
    Ref,
    TyConApp,
    TyForall,
    TyFun,
    TyInt,
    TyString,
    zonk_type,
)
from systemf.elab3.builtins import BUILTIN_LIST


def test_zonk_unbound_meta():
    m = MetaTv(uniq=1, level=0, ref=Ref(None))
    result = zonk_type(m)
    assert result is m


def test_zonk_bound_meta():
    m = MetaTv(uniq=1, level=0, ref=Ref(TyInt()))
    result = zonk_type(m)
    assert result == TyInt()


def test_zonk_meta_chain():
    m3 = MetaTv(uniq=3, level=0, ref=Ref(TyInt()))
    m2 = MetaTv(uniq=2, level=0, ref=Ref(m3))
    m1 = MetaTv(uniq=1, level=0, ref=Ref(m2))
    result = zonk_type(m1)
    assert result == TyInt()


def test_zonk_path_compression():
    m2 = MetaTv(uniq=2, level=0, ref=Ref(TyInt()))
    m1 = MetaTv(uniq=1, level=0, ref=Ref(m2))
    result = zonk_type(m1)
    assert result == TyInt()


def test_zonk_function_type():
    m = MetaTv(uniq=1, level=0, ref=Ref(TyInt()))
    fun = TyFun(m, TyString())
    result = zonk_type(fun)
    assert result == TyFun(TyInt(), TyString())


def test_zonk_forall():
    m = MetaTv(uniq=1, level=0, ref=Ref(TyInt()))
    a = BoundTv(name=Name(mod="<local>", surface="a", unique=-1))
    forall_ty = TyForall(vars=[a], body=m)
    result = zonk_type(forall_ty)
    expected = TyForall(vars=[a], body=TyInt())
    assert result == expected


def test_zonk_nested_fun():
    m1 = MetaTv(uniq=1, level=0, ref=Ref(TyInt()))
    m2 = MetaTv(uniq=2, level=0, ref=Ref(TyString()))
    nested = TyFun(TyFun(m1, m2), m1)
    result = zonk_type(nested)
    expected = TyFun(TyFun(TyInt(), TyString()), TyInt())
    assert result == expected


def test_zonk_tycon_app():
    list_name = Name(mod="builtins", surface="List", unique=4)
    m = MetaTv(uniq=1, level=0, ref=Ref(TyInt()))
    list_ty = TyConApp(name=list_name, args=[m])
    result = zonk_type(list_ty)
    expected = TyConApp(name=list_name, args=[TyInt()])
    assert result == expected


def test_zonk_tycon_app_builtin_name():
    m = MetaTv(uniq=999, level=0, ref=Ref(TyInt()))
    list_ty = TyConApp(name=BUILTIN_LIST, args=[m])
    result = zonk_type(list_ty)
    expected = TyConApp(name=BUILTIN_LIST, args=[TyInt()])
    assert result == expected
