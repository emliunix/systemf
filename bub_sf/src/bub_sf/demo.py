"""Demo: REPL with bub_sf extension loaded."""

from pathlib import Path

from systemf.elab3.repl import REPL
from systemf.elab3.types.ast import ImportDecl
from systemf.elab3.types.val import VLit
from systemf.elab3.types.ty import LitInt

from bub_sf.bub_ext import BubExt
from systemf.elab3.val_pp import pp_val


def main():
    bub_sf_dir = Path(__file__).parent.resolve()
    ctx = REPL(search_paths=[str(bub_sf_dir)], exts=[BubExt()])

    session = ctx.new_session()
    session.cmd_import(ImportDecl("bub", False, None, None, None))

    match session.eval('test_prim "test" 2'):
        case None:
            print("No result")
        case (val, ty):
            print(f"Result: {pp_val(session, val, ty)}")
            assert val == VLit(LitInt(1)), f"Expected 1, got {val}"
            print("Assertion passed")


if __name__ == "__main__":
    main()
