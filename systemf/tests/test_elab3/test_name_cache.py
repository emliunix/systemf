from systemf.elab3.types.ty import Name
from systemf.elab3.name_gen import NameCacheImpl
from systemf.elab3.builtins import BUILTIN_BOOL, BUILTIN_LIST, BUILTIN_LIST_CONS


def test_builtin_lookup():
    cache = NameCacheImpl()
    n = cache.get("builtins", "Bool")
    assert n == BUILTIN_BOOL


def test_unknown_returns_none():
    cache = NameCacheImpl()
    n = cache.get("M", "foo")
    assert n is None


def test_put_and_get():
    cache = NameCacheImpl()
    name = Name(mod="M", surface="foo", unique=9999)
    cache.put(name)
    assert cache.get("M", "foo") == name


def test_put_all():
    cache = NameCacheImpl()
    names = [
        Name(mod="M", surface="a", unique=9001),
        Name(mod="M", surface="b", unique=9002),
    ]
    cache.put_all(names)
    assert cache.get("M", "a") == names[0]
    assert cache.get("M", "b") == names[1]


def test_builtins_prepopulated():
    cache = NameCacheImpl()
    assert cache.get("builtins", "Bool") == BUILTIN_BOOL
    assert cache.get("builtins", "List") == BUILTIN_LIST
    assert cache.get("builtins", "Cons") == BUILTIN_LIST_CONS
