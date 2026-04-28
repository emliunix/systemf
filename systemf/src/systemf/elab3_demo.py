"""
Elab3 e2e demo: load modules via REPL, evaluate expressions via REPLSession.

Usage:
    cd systemf && uv run python -m systemf.elab3_demo
"""

from pathlib import Path

from systemf.elab3.repl import REPL
from systemf.elab3.val_pp import pp_val
from systemf.elab3.types import core
from systemf.elab3.types.ast import ImportDecl
from systemf.elab3.types.core_pp import pp_core
from systemf.elab3.types.val import VLit, VData, Val
from systemf.elab3.types.ty import LitInt, LitString


def main() -> None:
    demo_dir = Path(__file__).parent.resolve()
    search_path = str(demo_dir)

    # 1. Construct REPLContext
    ctx = REPL(search_paths=[search_path])
    print("=== Module loading ===\n")

    # 2. Load builtins first (so demo can import it)
    builtins_mod = ctx.load("builtins")
    print(f"Loaded builtins module: {builtins_mod.name}")
    print(f"  Exports: {[n.surface for n in builtins_mod.exports]}")

    # 3. Load demo module
    demo_mod = ctx.load("demo")
    print(f"\nLoaded demo module: {demo_mod.name}")
    print(f"  Exports: {[n.surface for n in demo_mod.exports]}")
    print(f"  TyThings: {[n.surface for n, _ in demo_mod.tythings]}")

    # 4. Core terms (typechecked, not yet evaluated)
    print(f"\n  Core terms (vals):")
    for binding in demo_mod.bindings:
        print(f"\n    {pp_binding_name(binding)}:")
        for line in pp_binding(binding).split("\n"):
            print(f"      {line}")

    # === e2e evaluation ===

    session = ctx.new_session()
    session.cmd_import(ImportDecl("demo", False, None, None, None))

    print("\n\n=== e2e evaluation ===\n")

    def check(expr: str, expected_val: Val, msg: str | None = None):
        match session.eval(expr):
            case (val, ty):
                assert val == expected_val, f"for {expr}: expected {expected_val}, got {val}"
                label = msg or expr
                print(f">> {label}")
                print(f"  {pp_val(session, val, ty)}  ✓")
            case None:
                assert False, f"for {expr}: eval returned None"
            case _:
                assert False, f"for {expr}: eval returned unexpected result"

    check("1", VLit(LitInt(1)))
    check("True", VData(0, []))
    check("id 42", VLit(LitInt(42)))
    check("1 + 2", VLit(LitInt(3)))
    check("const 1 2", VLit(LitInt(1)))
    check("not True", VData(1, []))
    check("not False", VData(0, []))
    check("compose (\\x -> x + 1) (\\x -> x * 2) 3", VLit(LitInt(7)))
    check("twice (\\x -> x + 1) 0", VLit(LitInt(2)))
    check('greet "world"', VLit(LitString("hello world")))
    check('greet "there"', VLit(LitString("hello there")))
    check("even 4", VData(0, []))
    check("even 3", VData(1, []))
    check("odd 3", VData(0, []))
    check("odd 4", VData(1, []))
    check("testConstMono", VLit(LitInt(1)))
    check("fromMaybe 0 (Just 42)", VLit(LitInt(42)))
    check("fromMaybe 0 Nothing", VLit(LitInt(0)))

    # Ref tests
    print("\n  --- Ref ---")
    check("get_ref (mk_ref 0)", VLit(LitInt(0)))
    check("let r = mk_ref 0 in let _ = set_ref r 42 in get_ref r", VLit(LitInt(42)))
    check("let r = mk_ref 0 in let _ = set_ref r 1 in let _ = set_ref r 2 in get_ref r", VLit(LitInt(2)))

    # Ref (Maybe a) — nullable ref
    print("\n  --- Ref (Maybe a) ---")
    check("get_ref (mk_ref Nothing)", VData(0, []),
          "nullable ref starts as Nothing")
    check(
        "let r = mk_ref Nothing in let _ = set_ref r (Just 42) in get_ref r",
        VData(1, [VLit(LitInt(42))]),
        "set nullable ref to Just 42",
    )
    check(
        "let r = mk_ref (Just 1) in let _ = set_ref r Nothing in get_ref r",
        VData(0, []),
        "clear a set ref back to Nothing",
    )
    check(
        "let r = mk_ref Nothing in let _ = set_ref r (Just 10) in fromMaybe 0 (get_ref r)",
        VLit(LitInt(10)),
        "fromMaybe on a Just ref",
    )
    check(
        "let r = mk_ref Nothing in fromMaybe 0 (get_ref r)",
        VLit(LitInt(0)),
        "fromMaybe on a Nothing ref",
    )

    print("\nAll e2e assertions passed.")


def pp_binding_name(b: core.Binding) -> str:
    match b:
        case core.NonRec(name, _):
            return name.name.surface
        case core.Rec(bindings):
            return ", ".join(name.name.surface for name, _ in bindings)
        case _:
            return "?"


def pp_binding(b: core.Binding) -> str:
    match b:
        case core.NonRec(name, expr):
            return f"{name} = {pp_core(expr)}"
        case core.Rec(bindings):
            binds_str = "\n".join(f"  {name} = {pp_core(expr)}" for name, expr in bindings)
            return f"rec {{\n{binds_str}\n}}"
        case _:
            return f"<unknown binding: {b}>"


if __name__ == "__main__":
    main()
