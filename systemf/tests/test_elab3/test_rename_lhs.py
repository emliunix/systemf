"""Tests that Rename.new_lhs_name returns builtin Name constants for builtin names,
and allocates fresh unique IDs for user-defined names.
"""

from systemf.elab3.rename import Rename
from systemf.elab3.reader_env import ReaderEnv
from systemf.elab3.name_gen import NameGeneratorImpl, NameCacheImpl
from systemf.elab3.builtins import (
    BUILTIN_BOOL, BUILTIN_TRUE, BUILTIN_FALSE,
    BUILTIN_LIST, BUILTIN_LIST_CONS, BUILTIN_LIST_NIL,
    BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR,
    BUILTIN_UNIT, BUILTIN_MK_UNIT,
    BUILTIN_ENDS,
)
from systemf.elab3.types.ty import Name
from systemf.utils.ast_utils import structural_equals
from systemf.utils.uniq import Uniq


def _make_fake_ctx():
    _uniq = Uniq(BUILTIN_ENDS)
    _cache = NameCacheImpl()
    builtins = [
        BUILTIN_BOOL, BUILTIN_TRUE, BUILTIN_FALSE,
        BUILTIN_LIST, BUILTIN_LIST_CONS, BUILTIN_LIST_NIL,
        BUILTIN_PAIR, BUILTIN_PAIR_MKPAIR,
        BUILTIN_UNIT, BUILTIN_MK_UNIT,
    ]
    _cache.put_all(builtins)

    class FakeCtx:
        def __init__(self):
            self.uniq = _uniq
            self.name_cache = _cache

        def load(self, name: str):
            raise NotImplementedError

        def next_replmod_id(self) -> int:
            return 0

    return FakeCtx()


def mk_rename(mod_name: str = "builtins") -> Rename:
    ctx = _make_fake_ctx()
    return Rename(ctx, ReaderEnv.empty(), mod_name, NameGeneratorImpl(mod_name, ctx.uniq))


def test_new_lhs_name_builtin_bool():
    r = mk_rename("builtins")
    assert r.new_lhs_name("Bool", None) is BUILTIN_BOOL


def test_new_lhs_name_builtin_true():
    r = mk_rename("builtins")
    assert r.new_lhs_name("True", None) is BUILTIN_TRUE


def test_new_lhs_name_builtin_false():
    r = mk_rename("builtins")
    assert r.new_lhs_name("False", None) is BUILTIN_FALSE


def test_new_lhs_name_builtin_list():
    r = mk_rename("builtins")
    assert r.new_lhs_name("List", None) is BUILTIN_LIST


def test_new_lhs_name_builtin_cons():
    r = mk_rename("builtins")
    assert r.new_lhs_name("Cons", None) is BUILTIN_LIST_CONS


def test_new_lhs_name_builtin_nil():
    r = mk_rename("builtins")
    assert r.new_lhs_name("Nil", None) is BUILTIN_LIST_NIL


def test_new_lhs_name_builtin_pair():
    r = mk_rename("builtins")
    assert r.new_lhs_name("Pair", None) is BUILTIN_PAIR


def test_new_lhs_name_builtin_mkpair():
    r = mk_rename("builtins")
    assert r.new_lhs_name("MkPair", None) is BUILTIN_PAIR_MKPAIR


def test_new_lhs_name_user_defined_gets_fresh_unique():
    r = mk_rename("MyMod")
    n = r.new_lhs_name("Foo", None)
    assert structural_equals(n, Name(mod="MyMod", surface="Foo", unique=-1))
    assert n.unique >= BUILTIN_ENDS


def test_new_lhs_name_user_defined_stable_within_instance():
    r = mk_rename("MyMod")
    n1 = r.new_lhs_name("Foo", None)
    n2 = r.new_lhs_name("Foo", None)
    assert n1.unique == n2.unique


def test_new_lhs_name_user_defined_different_names_different_uniques():
    # Use a fresh module + Rename instance so both names are allocated by the same Uniq counter
    r = mk_rename("__test_diff_mod__")
    n1 = r.new_lhs_name("Alpha", None)
    n2 = r.new_lhs_name("Beta", None)
    assert n1.unique != n2.unique
