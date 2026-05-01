# ForkTapeStore Implementation Plan

## Phase 0: Preparation

### 0.1 Study Republic Tape Tests
- Locate republic test suite (cloned at `./republic`)
- Copy relevant tape store tests to `bub_sf/tests/store/`
- Understand the test patterns and assertions used
- Document which behaviors are essential vs implementation details

### 0.2 Define Blank Interface
- Create `bub_sf/src/bub_sf/store/types.py`
- Define `ForkTapeStore` class with method signatures but no implementation
- Methods:
  - `__init__(db_path: Path)`
  - `fork(source_name: str, target_name: str) → None`
  - `snapshot(source_name: str, target_name: str) → None`
  - `append(tape_name: str, entry: TapeEntry) → None`
  - `fetch_all(query: TapeQuery) → list[TapeEntry]`
  - `read(tape_name: str) → list[TapeEntry] | None`
  - `list_tapes() → list[str]`
  - `reset(tape_name: str) → None`
- All methods raise `NotImplementedError`

## Phase 1: Test Design

### 1.1 Write Test Specification
- Create `bub_sf/docs/store/tests.md`
- List all test cases with:
  - Test name
  - What it verifies
  - Why it matters (coverage reasoning)
  - Setup steps
  - Expected assertions

### 1.2 Test Categories

**Core Operations:**
- `test_append_to_root_tape`: Single tape, sequential entries
- `test_fetch_all_root_tape`: Read back what was appended
- `test_list_tapes`: Empty store, single tape, multiple tapes
- `test_reset_tape`: Clear entries, reset then append

**Fork Operations:**
- `test_fork_creates_child`: Fork metadata correctness
- `test_fork_shares_parent_entries`: Child sees parent history
- `test_fork_independent_appends`: Child writes don't affect parent
- `test_fork_parent_unchanged`: Parent reads remain same after fork
- `test_nested_fork`: Fork a fork, three-level tree
- `test_fork_at_empty_tape`: Fork before any entries

**Merged View:**
- `test_merged_view_monotonic_ids`: Entry IDs are continuous
- `test_merged_view_no_gaps`: No missing entry IDs in read
- `test_merged_view_correct_order`: Root before child entries
- `test_merged_view_with_anchors`: Anchor filtering on forked tape

**Snapshot:**
- `test_snapshot_creates_independent_copy`: No parent relationship
- `test_snapshot_preserves_entries`: All entries copied
- `test_snapshot_divergence`: Snapshot can be modified independently

**Edge Cases:**
- `test_fork_nonexistent_source`: Error handling
- `test_duplicate_tape_name`: Uniqueness constraint
- `test_read_empty_tape`: Returns empty list
- `test_fetch_with_kinds_filter`: Filter by entry kind on forked tape
- `test_fetch_with_limit`: Limit results on forked tape

## Phase 2: Test Implementation

### 2.1 Write Tests Against Blank Interface
- Create `bub_sf/tests/store/test_fork_tape_store.py`
- Implement all tests from Phase 1
- Tests should fail (NotImplementedError) at this stage
- Use pytest fixtures for store setup/teardown

### 2.2 Verify Test Coverage
- Run tests: `pytest bub_sf/tests/store/ -v`
- Confirm all tests fail as expected
- Review test quality: clear names, isolated, deterministic

## Phase 3: Core Implementation

### 3.1 SQLite Schema Setup
- Implement `_ensure_schema()` in ForkTapeStore
- Create `tapes` and `tape_entries` tables
- Create index on `tape_entries(tape_id, entry_id)`
- Enable WAL mode: `PRAGMA journal_mode = WAL`

### 3.2 Root Tape Operations
- Implement `append()` for root tapes
- Implement `read()` / `fetch_all()` for root tapes (no parent)
- Implement `list_tapes()` and `reset()`
- Run root-tape tests, fix until passing

### 3.3 Fork Metadata Operation
- Implement `fork()`:
  - Lookup source tape
  - Compute `parent_entry_id = next_entry_id - 1`
  - Compute `parents_cache` from source
  - Insert new tape row
- Test: `test_fork_creates_child` should pass

## Phase 4: Merged View Implementation

### 4.1 CTE-Based Read
- Implement `_fetch_with_cte()` for forked tapes without cache
- Use recursive CTE to resolve parent chain
- Union entries from ancestors up to fork points + leaf entries
- Order by depth DESC, entry_id ASC for monotonic view

### 4.2 Cached Read (Optimization)
- Implement `_fetch_with_cache()` using `parents_cache` JSON
- Parse JSON array into temporary table
- Union ancestor entries + leaf entries
- Order by ord, entry_id for monotonic view

### 4.3 Forked Tape Tests
- Run all fork-related tests
- Fix merged view ordering, entry ID continuity
- Ensure parent independence (writes don't leak)

## Phase 5: Snapshot and Full Interface

### 5.1 Snapshot Implementation
- Implement `snapshot()`:
  - Create root tape (no parent)
  - Copy all entries from source with same entry_ids
  - Set `next_entry_id` to match source

### 5.2 Query Filtering
- Implement `kinds()` filtering in `fetch_all`
- Implement `limit()` in `fetch_all`
- Implement `after_anchor()` / `last_anchor()` filtering

### 5.3 Complete Test Pass
- Run full test suite
- Fix remaining failures
- Verify edge cases (empty tapes, nonexistent tapes, etc.)

## Phase 6: Integration and Polish

### 6.1 Async Adapter
- Wrap sync store with `AsyncTapeStoreAdapter` if needed
- Ensure compatibility with republic's async interfaces

### 6.2 Performance Validation
- Benchmark: fork 1000-entry tape (should be <10ms)
- Benchmark: read merged 3-level fork (should be <50ms)
- Document performance characteristics

### 6.3 Documentation
- Update `core.md` with any design changes from implementation
- Add docstrings to all public methods
- Create usage examples

## Testing Strategy

### Test Pyramid
- **Unit tests** (80%): Store operations in isolation
- **Integration tests** (15%): Multiple operations combined
- **Property tests** (5%): Randomized fork trees, invariant checking

### Fixtures
```python
@pytest.fixture
def store(tmp_path):
    return ForkTapeStore(tmp_path / "test.db")

@pytest.fixture
def populated_store(store):
    store.append("main", TapeEntry.message({"role": "user", "content": "hello"}))
    store.append("main", TapeEntry.message({"role": "assistant", "content": "hi"}))
    return store
```

### Invariants to Verify
After every test that modifies state:
1. `next_entry_id` = max(entry_id) + 1 for each tape
2. Forked tape's merged view has no duplicate entry_ids
3. Forked tape's merged view entry_ids are strictly increasing
4. Parent tape entries unchanged after child append

## Definition of Done

- [ ] All tests pass (`pytest bub_sf/tests/store/ -v`)
- [ ] 100% method coverage on ForkTapeStore
- [ ] Fork operation < 10ms for any tape size
- [ ] Read operation O(N) where N = visible entries
- [ ] Documentation complete (`core.md`, docstrings)
- [ ] No TODOs or placeholder code
- [ ] Type hints on all public methods

## File Structure

```
bub_sf/
├── docs/
│   └── store/
│       ├── core.md          # This design doc
│       ├── plan.md          # This plan
│       └── tests.md         # Test specifications
├── src/
│   └── bub_sf/
│       └── store/
│           ├── __init__.py
│           ├── types.py      # TapeEntry, TapeQuery, etc.
│           └── fork_store.py # ForkTapeStore implementation
└── tests/
    └── store/
        ├── __init__.py
        └── test_fork_tape_store.py
```
