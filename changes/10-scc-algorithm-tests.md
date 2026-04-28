# SCC Algorithm Fix and Unit Tests

## Facts

### Current State
- File: `systemf/src/systemf/elab3/scc.py` contains SCC (Strongly Connected Components) analysis algorithm
- The algorithm implements Tarjan's algorithm for detecting mutually recursive binding groups
- Current code has LSP errors: missing `find_node_by_key` function, undefined `Binding` type, missing `Any` import
- No unit tests exist for this standalone module

### Algorithm Purpose
The SCC module finds recursive groups in bindings:
- Input: List of bindings with their definitions and uses
- Process: Build dependency graph → Find SCCs → Output ordered groups
- Output: Topologically sorted binding groups with recursion flags

### Key Types
- `Node[K, T]`: Graph node with integer key, generic payload, integer edge list
- `SCC`: Component containing nodes with cyclic flag
- `BindingGroup`: Final output with payloads and recursion flag

## Design

### Changes Required

1. **Fix scc.py LSP errors**:
   - Add `from typing import Any`
   - Add `find_node_by_key()` helper function
   - Fix `Node` type to use `int` for key and edges (not generic K)
   - Fix `detect_recursive_groups()` signature to use correct input type
   - **Bug fix**: Remove incorrect `reversed()` call in `find_sccs()` - Tarjan's algorithm naturally produces topological order (dependencies first)

2. **Create comprehensive unit tests** (`systemf/tests/test_elab3/test_scc.py`):
   - Test independent bindings (no recursion)
   - Test self-recursive bindings
   - Test mutual recursion (2-way, 3-way)
   - Test mixed scenarios
   - Test topological ordering correctness

### Test Cases

```python
# Case 1: Independent bindings
bindings = [
    ("x = 1", "x", []),
    ("y = 2", "y", []),
]
# Expected: Two separate non-recursive groups

# Case 2: Self-recursive
bindings = [
    ("fact n = if n==0 then 1 else n*fact(n-1)", "fact", ["fact"]),
]
# Expected: Single recursive group

# Case 3: Mutual recursion
bindings = [
    ("even n = if n==0 then True else odd(n-1)", "even", ["odd"]),
    ("odd n = if n==0 then False else even(n-1)", "odd", ["even"]),
]
# Expected: One recursive group with both bindings

# Case 4: Dependency chain
bindings = [
    ("z = x + y", "z", ["x", "y"]),
    ("y = 2", "y", []),
    ("x = 1", "x", []),
]
# Expected: [y, x, z] in that order (dependencies first)
```

## Why It Works

- **Generic types**: `K` for def/use keys, `T` for payloads allows reuse across different binding types
- **Integer keys**: Node keys are indices (0, 1, 2...) for O(1) lookup
- **Tarjan's algorithm**: O(V+E) complexity, produces reverse topological order
- **Cyclic detection**: Single-node with self-loop or multi-node = recursive

## Files

- **Modify**: `systemf/src/systemf/elab3/scc.py` - Fix errors and complete implementation
- **Create**: `systemf/tests/test_elab3/test_scc.py` - Unit tests for SCC algorithm

## Verification

Run tests:
```bash
uv run pytest systemf/tests/test_elab3/test_scc.py -v
```
