"""Tests for the full Rename.rename pass on module-level declarations.

Uses parse_program -> Rename.rename pipeline with a fake REPLContext.
Assertions use structural_equals to ignore generated unique IDs.
"""

import pytest

from systemf.elab3.rename import Rename
from systemf.elab3.reader_env import ReaderEnv
from systemf.elab3.name_gen import NameGeneratorImpl, NameCacheImpl
from systemf.elab3.builtins import BUILTIN_ENDS
from systemf.elab3.types.ty import Name, TyForall, TyFun, TyConApp, BoundTv, TyInt
from systemf.elab3.types.ast import AnnotName, RnPrimOpDecl, RnPrimTyDecl
from systemf.elab3.types.mod import Module
from systemf.elab3.types.tything import Metas
from systemf.surface.parser import parse_program
from systemf.utils.uniq import Uniq
from systemf.utils.ast_utils import structural_equals

_N = Name("TestMod", "a", 0, None)


def _rn_forall_ty(var_names, body):
    return TyForall([BoundTv(Name("TestMod", v, 0, None)) for v in var_names], body)


_EMPTY_MODULE = Module(
    name="builtins",
    tythings=[],
    bindings=[],
    exports=[],
    _tythings_map={},
)


def _make_rename(mod_name: str = "TestMod") -> Rename:
    _uniq = Uniq(BUILTIN_ENDS)
    _cache = NameCacheImpl()

    class FakeCtx:
        def __init__(self):
            self.uniq = _uniq
            self.name_cache = _cache

        def load(self, name: str):
            if name == "builtins":
                return _EMPTY_MODULE
            raise NotImplementedError(f"no module: {name}")

        def next_replmod_id(self) -> int:
            return 0

    ctx = FakeCtx()
    return Rename(ctx, ReaderEnv.empty(), mod_name, NameGeneratorImpl(mod_name, ctx.uniq))


def _rename_source(source: str, mod_name: str = "TestMod"):
    _imports, decls = parse_program(source)
    r = _make_rename(mod_name)
    result = r.rename([], decls)
    return result.rn_mod


def _prim_op(rn, idx: int = 0) -> RnPrimOpDecl:
    return rn.prim_op_decls[idx]


def _prim_op_metas(rn, idx: int = 0) -> Metas:
    return _prim_op(rn, idx).metas


# =============================================================================
# prim_op: basic rename
# =============================================================================


def test_rename_prim_op_simple():
    rn = _rename_source("prim_op foo :: Int -> Int")
    op = _prim_op(rn)
    assert isinstance(op.name, AnnotName)
    assert structural_equals(
        op.name.type_ann,
        TyFun(TyInt(), TyInt()),
    )


def test_rename_prim_op_forall():
    rn = _rename_source("prim_op id :: forall a. a -> a")
    op = _prim_op(rn)
    assert structural_equals(
        op.name.type_ann,
        _rn_forall_ty(["a"], TyFun(BoundTv(_N), BoundTv(_N))),
    )


def test_rename_prim_op_forall_multi():
    rn = _rename_source("prim_op const :: forall a b. a -> b -> a")
    op = _prim_op(rn)
    nb = Name("TestMod", "b", 0, None)
    assert structural_equals(
        op.name.type_ann,
        _rn_forall_ty(["a", "b"], TyFun(BoundTv(_N), TyFun(BoundTv(nb), BoundTv(_N)))),
    )


def test_rename_multiple_prim_ops():
    rn = _rename_source(
        "prim_op add :: Int -> Int -> Int\n"
        "prim_op sub :: Int -> Int -> Int"
    )
    assert len(rn.prim_op_decls) == 2
    assert rn.prim_op_decls[0].name.name.surface == "add"
    assert rn.prim_op_decls[1].name.name.surface == "sub"


# =============================================================================
# prim_op: pragma
# =============================================================================


def test_rename_prim_op_single_pragma():
    rn = _rename_source(
        "{-# LLM model=gpt-4 #-}\n"
        "prim_op translate :: String -> String"
    )
    assert _prim_op_metas(rn).pragma == {"LLM": "model=gpt-4"}


def test_rename_prim_op_multiple_pragmas():
    rn = _rename_source(
        "{-# LLM a llm pragma #-}\n"
        "{-# TEST a test pragma #-}\n"
        "prim_op my_op :: Int -> Int"
    )
    assert _prim_op_metas(rn).pragma == {"LLM": "a llm pragma", "TEST": "a test pragma"}


def test_rename_prim_op_no_pragma():
    rn = _rename_source("prim_op foo :: Int -> Int")
    assert _prim_op_metas(rn).pragma == {}


# =============================================================================
# prim_op: docstring (preceding)
# =============================================================================


def test_rename_prim_op_docstring_preceding():
    rn = _rename_source(
        "-- | This adds two ints\n"
        "prim_op add :: Int -> Int -> Int"
    )
    assert _prim_op_metas(rn).doc == "This adds two ints"


def test_rename_prim_op_no_docstring():
    rn = _rename_source("prim_op foo :: Int -> Int")
    assert _prim_op_metas(rn).doc is None


def test_rename_prim_op_multiline_docstring():
    rn = _rename_source(
        "-- | First line\n"
        "-- | Second line\n"
        "prim_op foo :: Int -> Int"
    )
    assert _prim_op_metas(rn).doc == "First line\nSecond line"


# =============================================================================
# prim_op: arg docs (following docstrings on type args, incl. return type)
# =============================================================================


def test_rename_prim_op_arg_docs():
    rn = _rename_source(
        "prim_op add :: Int -- ^ first arg\n"
        "             -> Int -- ^ second arg\n"
        "             -> Int -- ^ the result"
    )
    assert _prim_op_metas(rn).arg_docs == ["first arg", "second arg", "the result"]


def test_rename_prim_op_arg_docs_only_return_doc():
    rn = _rename_source(
        "prim_op unsafe :: Int -> Int -- ^ always crashes"
    )
    assert _prim_op_metas(rn).arg_docs == [None, "always crashes"]


def test_rename_prim_op_arg_docs_no_docs():
    rn = _rename_source("prim_op add :: Int -> Int -> Int")
    assert _prim_op_metas(rn).arg_docs == [None, None, None]


def test_rename_prim_op_arg_docs_with_forall():
    rn = _rename_source(
        "prim_op fmap :: forall a. a -- ^ the value\n"
        "              -> a -- ^ mapped"
    )
    assert _prim_op_metas(rn).arg_docs == ["the value", "mapped"]


# =============================================================================
# prim_ty
# =============================================================================


def test_rename_prim_ty_simple():
    rn = _rename_source("prim_type Int")
    assert len(rn.prim_ty_decls) == 1
    assert rn.prim_ty_decls[0].name.surface == "Int"


def test_rename_prim_ty_with_params():
    rn = _rename_source("prim_type Array a")
    pt = rn.prim_ty_decls[0]
    assert pt.name.surface == "Array"
    assert all(isinstance(tv, BoundTv) for tv in pt.tyvars)


# =============================================================================
# data declarations
# =============================================================================


def test_rename_data_simple():
    rn = _rename_source("data Color = Red | Green | Blue")
    d = rn.data_decls[0]
    assert d.name.surface == "Color"
    assert [c.name.surface for c in d.constructors] == ["Red", "Green", "Blue"]


def test_rename_data_with_fields():
    rn = _rename_source("data Pair a b = MkPair a b")
    d = rn.data_decls[0]
    assert d.name.surface == "Pair"
    assert len(d.tyvars) == 2
    con = d.constructors[0]
    assert con.name.surface == "MkPair"
    assert len(con.fields) == 2


# =============================================================================
# term declarations
# =============================================================================


def test_rename_term_annotated():
    rn = _rename_source(
        "id :: forall a. a -> a = \\x -> x"
    )
    assert len(rn.term_decls) == 1
    t = rn.term_decls[0]
    assert isinstance(t.name, AnnotName)
    assert t.name.name.surface == "id"


def test_rename_term_with_annotation_type():
    rn = _rename_source(
        "id :: forall a. a -> a = \\x -> x"
    )
    t = rn.term_decls[0]
    assert structural_equals(
        t.name.type_ann,
        _rn_forall_ty(["a"], TyFun(BoundTv(_N), BoundTv(_N))),
    )


# =============================================================================
# mixed declarations
# =============================================================================


def test_rename_mixed_decls():
    rn = _rename_source(
        "prim_type Int\n"
        "prim_op add :: Int -> Int -> Int\n"
        "data Bool = True | False\n"
        "const :: forall a. forall b. a -> b -> a = \\x y -> x"
    )
    assert len(rn.prim_ty_decls) == 1
    assert len(rn.prim_op_decls) == 1
    assert len(rn.data_decls) == 1
    assert len(rn.term_decls) == 1
