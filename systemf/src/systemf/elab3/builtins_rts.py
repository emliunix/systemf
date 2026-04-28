"""Runtime support for builtin primitive operations.

This module provides pure function implementations.  The REPL layer
is responsible for wrapping them in ``VPartial`` and registering them
via ``REPLContext.get_primop``.

Bool (``&&``, ``||``, ``not``) are NOT primops — they are regular
SystemF functions defined in ``builtins.sf`` using ``case``.
"""

from typing import Callable, cast

from .types.val import VLit, VPrim, Val
from .types.ty import LitInt, LitString

from . import builtins as bi


# --- helpers ---

def _expect_int(v: Val) -> int:
    match v:
        case VLit(lit=LitInt(value=n)):
            return n
    raise Exception(f"expected int, got {v}")


def _expect_string(v: Val) -> str:
    match v:
        case VLit(lit=LitString(value=s)):
            return s
    raise Exception(f"expected string, got {v}")


# --- primop implementations (pure computation, no constructors) ---

def int_plus(args: list[Val]) -> Val:
    a, b = args
    return VLit(LitInt(_expect_int(a) + _expect_int(b)))


def int_minus(args: list[Val]) -> Val:
    a, b = args
    return VLit(LitInt(_expect_int(a) - _expect_int(b)))


def int_multiply(args: list[Val]) -> Val:
    a, b = args
    return VLit(LitInt(_expect_int(a) * _expect_int(b)))


def int_divide(args: list[Val]) -> Val:
    a, b = args
    return VLit(LitInt(_expect_int(a) // _expect_int(b)))


def string_concat(args: list[Val]) -> Val:
    a, b = args
    return VLit(LitString(_expect_string(a) + _expect_string(b)))


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


# --- int-relational primops (return True/False, received from caller) ---

def mk_int_eq(true_val: Val, false_val: Val) -> Callable[[list[Val]], Val]:
    def _int_eq(args: list[Val]) -> Val:
        a, b = args
        return true_val if _expect_int(a) == _expect_int(b) else false_val
    return _int_eq


def mk_int_neq(true_val: Val, false_val: Val) -> Callable[[list[Val]], Val]:
    def _int_neq(args: list[Val]) -> Val:
        a, b = args
        return true_val if _expect_int(a) != _expect_int(b) else false_val
    return _int_neq


def mk_int_lt(true_val: Val, false_val: Val) -> Callable[[list[Val]], Val]:
    def _int_lt(args: list[Val]) -> Val:
        a, b = args
        return true_val if _expect_int(a) < _expect_int(b) else false_val
    return _int_lt


def mk_int_gt(true_val: Val, false_val: Val) -> Callable[[list[Val]], Val]:
    def _int_gt(args: list[Val]) -> Val:
        a, b = args
        return true_val if _expect_int(a) > _expect_int(b) else false_val
    return _int_gt


def mk_int_le(true_val: Val, false_val: Val) -> Callable[[list[Val]], Val]:
    def _int_le(args: list[Val]) -> Val:
        a, b = args
        return true_val if _expect_int(a) <= _expect_int(b) else false_val
    return _int_le


def mk_int_ge(true_val: Val, false_val: Val) -> Callable[[list[Val]], Val]:
    def _int_ge(args: list[Val]) -> Val:
        a, b = args
        return true_val if _expect_int(a) >= _expect_int(b) else false_val
    return _int_ge
