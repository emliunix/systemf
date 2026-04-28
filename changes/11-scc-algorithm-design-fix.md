# SCC Algorithm Design Improvements

## Facts

### Current Implementation Issues
The SCC module was just committed (change 10), but has design issues:

1. **Key type confusion**: Node.key was `int` but should be generic `K` to match user-facing keys
2. **O(n) lookup**: `find_node_by_key()` did linear search instead of dict lookup
3. **No duplicate detection**: Duplicate input keys were silently dropped
4. **Missing `__future__` import**: Inconsistent with other modules

### What Needs to Change
- Properly use generic type K for user-facing keys throughout
- Build dict[K, int] mapping for O(1) lookup
- Raise DuplicateKeyError for duplicate keys
- Add `from __future__ import annotations`
- Return tuple from build_graph to expose mapping

## Design

### New Algorithm Structure

```python
# Input: list of (payload, def_key: K, uses_keys: list[K])
# Key K must be hashable

# Step 1: Build mapping
key_to_idx: dict[K, int] = {def_key: i for i, (payload, def_key, uses) in enumerate(bindings)}
# ↑ Checks for duplicates

# Step 2: Build nodes with user keys
nodes: list[Node[K, T]] = []
for payload, def_key, uses in bindings:
    edges = [use for use in uses if use in key_to_idx]
    nodes.append(Node(key=def_key, payload=payload, edges=edges))

# Step 3: Run Tarjan's on internal indices
# - Use dict[int, Node] for O(1) node lookup
# - Convert user keys to internal indices for algorithm
# - Return SCCs with user-facing keys preserved

# Step 4: Output BindingGroups
```

### Key Changes

1. **Node type**: `key: K`, `edges: list[K]` (user-facing)
2. **Internal mapping**: `key_to_idx: dict[K, int]` (K → 0,1,2...)
3. **Error handling**: `DuplicateKeyError` on duplicate input
4. **Performance**: O(1) node lookup via dict, O(V+E) SCC algorithm

## Why It Works

- **Generic K**: Type-safe for any hashable key (str, Name, etc.)
- **Internal indices**: Tarjan's algorithm needs sequential ints, but user gets back K
- **Dict mapping**: O(1) lookup instead of O(n) linear search
- **Error detection**: Fails fast on duplicate keys rather than silent corruption

## Files

- **Modify**: `systemf/src/systemf/elab3/scc.py` - Complete rewrite with proper design

## Verification

Run manual verification:
```bash
cd systemf && python3 tests/test_elab3/verify_scc.py
```

Expected: All 6 tests pass with improved design.
