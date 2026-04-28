"""Tests for ReaderEnv lookup behavior."""

from systemf.elab3.reader_env import (
    ReaderEnv,
    LocalRdrElt,
    ImportRdrElt,
    ImportSpec,
    UnqualName,
    QualName,
)
from systemf.elab3.types import Name


def make_name(surface: str, mod: str, unique: int) -> Name:
    """Helper to create Name for tests.
    
    Name constructor: Name(mod, surface, unique)
    """
    return Name(mod, surface, unique)


# ---
# Test LocalRdrElt lookup

def test_local_rdr_elt_unqualified_lookup_finds_it():
    """Local bindings are accessible via unqualified name."""
    name = make_name("foo", "Test", 1)
    local_elt = LocalRdrElt.create(name)
    env = ReaderEnv.from_elts([local_elt])
    
    result = env.lookup(UnqualName("foo"))
    
    assert len(result) == 1
    assert result[0] == local_elt


def test_local_rdr_elt_qualified_lookup_not_found():
    """Local bindings are NOT accessible via qualified name."""
    name = make_name("foo", "Test", 1)
    local_elt = LocalRdrElt.create(name)
    env = ReaderEnv.from_elts([local_elt])
    
    result = env.lookup(QualName("Test", "foo"))
    
    assert len(result) == 0


# ---
# Test ImportRdrElt with is_qual=False

def test_import_rdr_elt_unqualified_allowed():
    """Import with is_qual=False is accessible via unqualified name."""
    name = make_name("foo", "Data.Maybe", 1)
    spec = ImportSpec(module_name="Data.Maybe", alias=None, is_qual=False)
    import_elt = ImportRdrElt.create(name, spec)
    env = ReaderEnv.from_elts([import_elt])
    
    result = env.lookup(UnqualName("foo"))
    
    assert len(result) == 1
    assert result[0] == import_elt


def test_import_rdr_elt_qualified_by_module_name():
    """Import with is_qual=False is accessible via module-qualified name."""
    name = make_name("foo", "Data.Maybe", 1)
    spec = ImportSpec(module_name="Data.Maybe", alias=None, is_qual=False)
    import_elt = ImportRdrElt.create(name, spec)
    env = ReaderEnv.from_elts([import_elt])
    
    result = env.lookup(QualName("Data.Maybe", "foo"))
    
    assert len(result) == 1
    assert result[0] == import_elt


# ---
# Test ImportRdrElt with is_qual=True

def test_import_rdr_elt_unqualified_not_allowed():
    """Import with is_qual=True is NOT accessible via unqualified name."""
    name = make_name("foo", "Data.Maybe", 1)
    spec = ImportSpec(module_name="Data.Maybe", alias=None, is_qual=True)
    import_elt = ImportRdrElt.create(name, spec)
    env = ReaderEnv.from_elts([import_elt])
    
    result = env.lookup(UnqualName("foo"))
    
    assert len(result) == 0


def test_import_rdr_elt_qualified_only_by_module_name():
    """Import with is_qual=True is accessible via qualified name."""
    name = make_name("foo", "Data.Maybe", 1)
    spec = ImportSpec(module_name="Data.Maybe", alias=None, is_qual=True)
    import_elt = ImportRdrElt.create(name, spec)
    env = ReaderEnv.from_elts([import_elt])
    
    result = env.lookup(QualName("Data.Maybe", "foo"))
    
    assert len(result) == 1
    assert result[0] == import_elt


# ---
# Test alias-based and module-based qualified lookup

def test_import_rdr_elt_qualified_by_alias():
    """Import with alias is accessible via alias-qualified name."""
    name = make_name("foo", "Data.List", 1)
    spec = ImportSpec(module_name="Data.List", alias="L", is_qual=False)
    import_elt = ImportRdrElt.create(name, spec)
    env = ReaderEnv.from_elts([import_elt])
    
    result_by_alias = env.lookup(QualName("L", "foo"))
    result_by_module = env.lookup(QualName("Data.List", "foo"))
    result_by_wrong = env.lookup(QualName("Wrong", "foo"))
    
    assert len(result_by_alias) == 1
    assert result_by_alias[0] == import_elt
    assert len(result_by_module) == 1
    assert result_by_module[0] == import_elt
    assert len(result_by_wrong) == 0


# ---
# Test edge cases

def test_empty_environment_lookup():
    """Lookup in empty environment returns empty list."""
    env = ReaderEnv.empty()
    
    result = env.lookup(UnqualName("anything"))
    
    assert len(result) == 0


def test_nonexistent_name_lookup():
    """Lookup of non-existent name returns empty list."""
    name = make_name("foo", "Test", 1)
    local_elt = LocalRdrElt.create(name)
    env = ReaderEnv.from_elts([local_elt])
    
    result = env.lookup(UnqualName("bar"))
    
    assert len(result) == 0
