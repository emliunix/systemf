"""Tests for pp_val pretty printer."""

from systemf.elab3.types.protocols import TyLookup
from systemf.elab3.types.ty import TyConApp, Name
from systemf.elab3.types.tything import TyThing
from systemf.elab3.types.val import HasDoc, VPrim
from systemf.elab3.val_pp import pp_val


class MockTyLookup(TyLookup):
    def lookup(self, name: Name) -> TyThing:
        raise NotImplementedError("MockTyLookup.lookup should not be called")


class DocObj(HasDoc):
    def doc(self) -> str:
        return "some doc\nline 2 of the doc"


def test_pp_val_vprim_hasdoc():
    ctx = MockTyLookup()
    val = VPrim(DocObj())
    ty = TyConApp(Name("b", "SomePrimTy", 1, None), [])
    assert pp_val(ctx, val, ty) == (
        "-- some doc\n"
        "-- line 2 of the doc\n"
        "<prim> :: SomePrimTy"
    )


def test_pp_val_vprim_no_doc():
    ctx = MockTyLookup()
    val = VPrim(42)
    ty = TyConApp(Name("b", "Int", 1, None), [])
    assert pp_val(ctx, val, ty) == "<prim> :: Int"
