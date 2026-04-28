# Change Plan: Add Unit Tests for ReaderEnv Lookup Behavior

## Facts

**Current state:**
1. `reader_env.py` has been refactored with new type-safe design (LocalRdrElt, ImportRdrElt)
2. `lookup()` filters by RdrName (QualName vs UnqualName)
3. `_filter_by_spec()` handles three cases:
   - QualName lookup: matches if alias == qual OR module_name == qual
   - UnqualName lookup: matches ImportRdrElt if any spec has is_qual=False
   - UnqualName lookup: always matches LocalRdrElt
4. `ImportSpec` has: module_name, alias, is_qual fields
5. No tests currently exist for ReaderEnv (validated in test directory)
6. The Name type (from types.py) has: surface (str), mod (str), unique (int) fields
7. Existing tests in test_elab3/ use simple pytest patterns with descriptive docstrings

**Test requirements:**
- Test lookup behavior, not internal implementation
- Cover qualified/unqualified access patterns
- Test alias-based and module-name-based qualified access
- Test that is_qual controls unqualified visibility

## Design

**Test file:** `systemf/tests/test_elab3/test_reader_env.py`

**Test cases (6 core lookup scenarios):**

1. **Test LocalRdrElt unqualified lookup**
   - Create LocalRdrElt with Name
   - Lookup UnqualName("foo") → should find it
   - Lookup QualName("M", "foo") → should NOT find it

2. **Test ImportRdrElt unqualified lookup with is_qual=False**
   - Create ImportRdrElt with is_qual=False
   - Lookup UnqualName("foo") → should find it
   - Lookup QualName("M", "foo") → should find it (by module_name)

3. **Test ImportRdrElt qualified-only with is_qual=True**
   - Create ImportRdrElt with is_qual=True
   - Lookup UnqualName("foo") → should NOT find it
   - Lookup QualName("M", "foo") → should find it

4. **Test alias-based qualified lookup**
   - Create ImportRdrElt with alias="Bar", module_name="Data.Foo"
   - Lookup QualName("Bar", "foo") → should find it (by alias)
   - Lookup QualName("Data.Foo", "foo") → should find it (by module_name)
   - Lookup QualName("Other", "foo") → should NOT find it

5. **Test empty environment**
   - Create empty ReaderEnv
   - Lookup UnqualName("anything") → returns empty list

6. **Test non-existent name**
   - Create env with name "foo"
   - Lookup UnqualName("bar") → returns empty list

## Why It Works

1. **Focused scope:** Tests only lookup behavior (the public API)
2. **No implementation testing:** Tests behavior (what comes back) not how it's done
3. **Coverage:** Tests all three filtering dimensions: unqualified, alias-qualified, module-qualified
4. **Simple:** Each test is small with clear setup/assert pattern
5. **Follows style:** Uses static factory methods (LocalRdrElt.create, ImportRdrElt.create)

## Files

**Add:**
- `systemf/tests/test_elab3/test_reader_env.py` - New test file

**No changes needed to:**
- `systemf/src/systemf/elab3/reader_env.py` - Tests against existing implementation
- `systemf/src/systemf/elab3/types.py` - Just need Name for test fixtures

## Test Style Guidelines

1. Use pytest (already in project)
2. Keep tests small and focused (one behavior per test)
3. Use descriptive test names and docstrings (following test_types.py pattern)
4. Create helper functions for repetitive setup (Name creation)
5. Follow existing test patterns in test_elab3/ directory

## Setup Requirements

Need to import from systemf.elab3:
- `reader_env`: ReaderEnv, LocalRdrElt, ImportRdrElt, ImportSpec, UnqualName, QualName
- `types`: Name

## Verification

After writing tests:
1. `cd systemf && python -m pytest tests/test_elab3/test_reader_env.py -v`
2. All tests should pass
3. If tests fail due to implementation bugs, note them and fix implementation first
