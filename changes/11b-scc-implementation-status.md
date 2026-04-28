# SCC Algorithm — Implementation Status

Follow-up to `changes/11-scc-algorithm-design-fix.md`. Documents what was actually implemented and current state.

## What Changed from Plan 11

1. **Topological ordering bug fixed**: Removed incorrect `reversed()` call in `find_sccs`. Tarjan's raw output already produces SCCs in dependency-first order when edges go from dependent→dependency.
2. **`BindingGroup` renamed to `SccGroup`** — more generic, not tied to "bindings".
3. **`detect_recursive_groups` renamed to `run_scc`** — more generic entry point.
4. **`SccGroup.bindings` typed as `list[T]`** instead of `list[Any]` (type safety fix from review).
5. **Removed unused `Any` import** from `scc.py`.
6. **`verify_scc.py` deleted** — was a workaround for not having pytest available. All tests now in `test_scc.py` using `~/.local/bin/uv run pytest`.
7. **`test_scc.py` rewritten** to match current API (generic string keys, `build_graph` returns tuple, `find_sccs` takes `key_to_idx`, `run_scc` entry point). 23 tests covering: empty, single, independent, chain, diamond, self-recursive, mutual 2-way, mutual 3-way, topological order, mixed, external use filtering, duplicate detection.

## Current API

```python
from systemf.elab3.scc import (
    DuplicateKeyError,
    Node,           # dataclass: key: K, payload: T, edges: list[K]
    SCC,            # dataclass: nodes: list[Node[K,T]], is_cyclic: bool
    SccGroup,       # dataclass: bindings: list[T], is_recursive: bool
    build_graph,    # (bindings) -> (dict[K,int], list[Node[K,T]])
    find_sccs,      # (key_to_idx, nodes) -> list[SCC[K,T]]
    process_output, # (sccs) -> list[SccGroup[T]]
    run_scc,        # (bindings) -> list[SccGroup[T]]   # full pipeline
)
```

## Current File State

| File | Status |
|------|--------|
| `systemf/src/systemf/elab3/scc.py` | Complete (163 lines) |
| `systemf/tests/test_elab3/test_scc.py` | Complete (23 tests, all pass) |
| `systemf/tests/test_elab3/verify_scc.py` | Deleted |

## Verification

```bash
~/.local/bin/uv run pytest systemf/tests/test_elab3/test_scc.py -v
```

Expected: 23 passed in ~0.1s

## Remaining

- Integration with `typecheck.py` (future work, separate change plan)
