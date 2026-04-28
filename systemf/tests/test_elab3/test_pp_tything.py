"""Tests for pp_tything pretty printer.

Uses assert == on exact string output to ensure source-accurate formatting.
"""

from systemf.elab3.types.ty import Name, Id, TyFun, TyForall, TyConApp, TyInt, BoundTv
from systemf.elab3.types.tything import AnId, ATyCon, ACon, APrimTy, Metas
from systemf.elab3.pp_tything import pp_tything

_a = BoundTv(Name("M", "a", 1, None))
_b = BoundTv(Name("M", "b", 2, None))
_list_n = Name("b", "List", 6, None)
_bool_n = Name("b", "Bool", 3, None)


# =============================================================================
# AnId: term binding
# =============================================================================


def test_pp_term_forall():
    n = Name("MyMod", "id", 99, None)
    ty = TyForall([_a], TyFun(_a, _a))
    assert pp_tything(AnId(n, Id(n, ty), False, None)) == (
        "id :: forall a. a -> a\n"
    )


def test_pp_term_no_forall():
    n = Name("M", "const", 50, None)
    ty = TyFun(TyInt(), TyInt())
    assert pp_tything(AnId(n, Id(n, ty), False, None)) == (
        "const :: Int -> Int\n"
    )


def test_pp_term_forall_multi_arg_docs():
    n = Name("M", "f", 50, None)
    ty = TyForall([_a, _b], TyFun(_a, TyFun(_b, _a)))
    metas = Metas(pragma={}, doc=None, arg_docs=["the a", "the b", "the result"])
    assert pp_tything(AnId(n, Id(n, ty), False, metas)) == (
        "f :: forall a b. a -- ^ the a\n"
        "    -> b -- ^ the b\n"
        "    -> a -- ^ the result\n"
    )


# =============================================================================
# AnId: primop
# =============================================================================


def test_pp_primop_no_metas():
    n = Name("b", "int_plus", 11, None)
    ty = TyFun(TyInt(), TyFun(TyInt(), TyInt()))
    assert pp_tything(AnId(n, Id(n, ty), True, None)) == (
        "prim_op int_plus :: Int -> Int -> Int\n"
    )


def test_pp_primop_pragma_doc_argdocs():
    n = Name("b", "int_plus", 11, None)
    ty = TyFun(TyInt(), TyFun(TyInt(), TyInt()))
    metas = Metas(
        pragma={"LLM": "model=gpt-4"},
        doc="Integer addition\nUse with care",
        arg_docs=["first", "second", "result"],
    )
    assert pp_tything(AnId(n, Id(n, ty), True, metas)) == (
        "-- | Integer addition\n"
        "-- | Use with care\n"
        "{-# LLM model=gpt-4 #-}\n"
        "prim_op int_plus :: Int -- ^ first\n"
        "    -> Int -- ^ second\n"
        "    -> Int -- ^ result\n"
    )


def test_pp_primop_partial_argdocs():
    n = Name("b", "int_plus", 11, None)
    ty = TyFun(TyInt(), TyInt())
    metas = Metas(pragma={}, doc=None, arg_docs=[None, "always crashes"])
    assert pp_tything(AnId(n, Id(n, ty), True, metas)) == (
        "prim_op int_plus :: Int\n"
        "    -> Int -- ^ always crashes\n"
    )


def test_pp_primop_multi_pragma():
    n = Name("M", "translate", 50, None)
    ty = TyFun(TyConApp(Name("b", "String", 99, None), []), TyConApp(Name("b", "String", 99, None), []))
    metas = Metas(
        pragma={"LLM": "model=gpt-4", "COST": "0.01"},
        doc="Translate text",
        arg_docs=[None, None],
    )
    assert pp_tything(AnId(n, Id(n, ty), True, metas)) == (
        "-- | Translate text\n"
        "{-# LLM model=gpt-4 #-}\n"
        "{-# COST 0.01 #-}\n"
        "prim_op translate :: String -> String\n"
    )


# =============================================================================
# ATyCon: data declarations
# =============================================================================


def test_pp_data_simple():
    assert pp_tything(ATyCon(_bool_n, [], [
        ACon(Name("b", "True", 4, None), 0, 0, [], _bool_n, None),
        ACon(Name("b", "False", 5, None), 1, 0, [], _bool_n, None),
    ], None)) == (
        "data Bool\n"
        "    = True\n"
        "    | False\n"
    )


def test_pp_data_with_params_and_fields():
    assert pp_tything(ATyCon(_list_n, [_a], [
        ACon(Name("b", "Nil", 8, None), 0, 0, [], _list_n, None),
        ACon(Name("b", "Cons", 7, None), 1, 2, [_a, TyConApp(_list_n, [_a])], _list_n, None),
    ], None)) == (
        "data List a\n"
        "    = Nil\n"
        "    | Cons a List a\n"
    )


def test_pp_data_no_constructors():
    n = Name("M", "Void", 50, None)
    assert pp_tything(ATyCon(n, [], [], None)) == (
        "data Void\n"
    )


# =============================================================================
# APrimTy
# =============================================================================


def test_pp_prim_type_with_params():
    assert pp_tything(APrimTy(Name("b", "Ref", 29, None), [_a], None)) == (
        "prim_type Ref a\n"
    )


def test_pp_prim_type_no_params():
    assert pp_tything(APrimTy(Name("b", "Int", 99, None), [], None)) == (
        "prim_type Int\n"
    )


# =============================================================================
# ACon standalone
# =============================================================================


def test_pp_acon():
    assert pp_tything(ACon(
        Name("b", "Cons", 7, None), 1, 2,
        [_a, TyConApp(_list_n, [_a])],
        _list_n,
        None,
    )) == (
        "Cons a List a\n"
    )
