"""Runtime support for builtin primitive operations.

This module provides pure function implementations.  The REPL layer
is responsible for wrapping them in ``VPartial`` and registering them
via ``REPLContext.get_primop``.

Bool (``&&``, ``||``, ``not``) are NOT primops — they are regular
SystemF functions defined in ``builtins.sf`` using ``case``.
"""

from typing import cast

from .types.val import VLit, VPrim, Val
from .types.ty import LitInt, LitString

from . import builtins as bi


# --- primop implementations (pure computation, no constructors) ---

# The typechecker guarantees argument types, so we cast rather than
# defensively match.


def int_plus(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return VLit(LitInt(x + y))


def int_minus(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return VLit(LitInt(x - y))


def int_multiply(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return VLit(LitInt(x * y))


def int_divide(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return VLit(LitInt(x // y))


def string_concat(args: list[Val]) -> Val:
    a, b = args
    s = cast(LitString, cast(VLit, a).lit).value
    t = cast(LitString, cast(VLit, b).lit).value
    return VLit(LitString(s + t))


def error(args: list[Val]) -> Val:
    (a,) = args
    match a:
        case VLit(lit=LitString(value=s)):
            raise Exception(f"runtime error: {s}")
        case _:
            raise Exception(f"runtime error: {a!r}")
        

def set_ref(args: list[Val]) -> Val:
    ref, new_val = args
    cast(VPrim, ref).val[0] = new_val
    return bi.UNIT_VAL


def get_ref(args: list[Val]) -> Val:
    ref = args[0]
    match ref:
        case VPrim(val=[val]):
            return val
        case _: raise Exception(f"Invalid ref value: {ref}")


def mk_ref(args: list[Val]) -> Val:
    (initial,) = args
    return VPrim([initial])


# --- int-relational primops ---

# TRUE_VAL / FALSE_VAL are defined in builtins.py; the typechecker
# guarantees these are only called with Int arguments.


def int_eq(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return bi.TRUE_VAL if x == y else bi.FALSE_VAL


def int_neq(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return bi.TRUE_VAL if x != y else bi.FALSE_VAL


def int_lt(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return bi.TRUE_VAL if x < y else bi.FALSE_VAL


def int_gt(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return bi.TRUE_VAL if x > y else bi.FALSE_VAL


def int_le(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return bi.TRUE_VAL if x <= y else bi.FALSE_VAL


def int_ge(args: list[Val]) -> Val:
    a, b = args
    x = cast(LitInt, cast(VLit, a).lit).value
    y = cast(LitInt, cast(VLit, b).lit).value
    return bi.TRUE_VAL if x >= y else bi.FALSE_VAL
