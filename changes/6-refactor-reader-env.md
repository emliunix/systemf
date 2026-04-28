# Change Plan: Refactor reader_env.py

## Facts

**Current state:**
1. `reader_env.py` has 220 lines with multiple design issues
2. Uses `field(default_factory=dict)` which violates our "explicit init" style rule
3. Has undefined variable bugs: `surface` on line 84, `hpt` on line 105
4. `RdrElt` uses `is_local: bool` + `import_specs: list` instead of sum types
5. `ImportSpec` has unnecessary `items` field (ImportList/HidingList/None)
6. `ReaderEnv` has too many methods: `empty()`, `from_module()`, `from_imports()`, `merge()`, `extend_local()`
7. Two files import from `reader_env.py`: `rename.py` and `repl.py`
8. No tests currently exist for ReaderEnv

**Design constraints:**
- Must follow GHC's GlobalRdrEnv design (validated in READER_ENV_EXPLORATION.md)
- Must support REPL shadowing semantics (old bindings become qualified-only)
- Must distinguish local vs imported bindings at type level (invariant enforcement)
- Must support lookup by `RdrName` (UnqualName | QualName)

## Design

**New type hierarchy:**

```python
# RdrElt split into two types (invariant: locals have no import_specs)
@dataclass(frozen=True)
class LocalRdrElt:
    name: Name
    
    @staticmethod
    def create(name: Name) -> LocalRdrElt: ...

@dataclass(frozen=True)
class ImportRdrElt:
    name: Name
    import_specs: list[ImportSpec]
    
    @staticmethod
    def create(name: Name, spec: ImportSpec) -> ImportRdrElt: ...

RdrElt = LocalRdrElt | ImportRdrElt

# Simplified ImportSpec (removed items field)
@dataclass(frozen=True)
class ImportSpec:
    module_name: str
    alias: str | None
    is_qual: bool

# RdrName (unchanged)
RdrName = QualName | UnqualName

@dataclass
class QualName:
    qual: str
    name: str

@dataclass
class UnqualName:
    name: str
```

**ReaderEnv API (minimal):**

```python
@dataclass(frozen=True)
class ReaderEnv:
    table: dict[str, list[RdrElt]]  # Just type annotation, no default_factory
    
    def __init__(self, elts: list[RdrElt]) -> None:
        """Build from list, merging same-Name elts."""
        ...
    
    def lookup(self, rdr_name: RdrName) -> list[RdrElt]:
        """Look up by RdrName, filtered by qual/unqual."""
        ...
    
    def merge(self, other: ReaderEnv) -> ReaderEnv:
        """Merge envs. Other shadows self."""
        ...
    
    def __add__(self, other: ReaderEnv) -> ReaderEnv:
        """Proxy to merge."""
        return self.merge(other)
    
    @staticmethod
    def empty() -> ReaderEnv:
        return ReaderEnv([])
```

**Helper functions (module level):**
- `merge_rdr_elts(a: RdrElt, b: RdrElt) -> RdrElt` - merge two elts for same Name
- `pick_unqual(elt: RdrElt) -> RdrElt | None` - filter for unqualified access
- `pick_qual(elt: RdrElt, module: str) -> RdrElt | None` - filter for qualified access
- `shadow_rdr_elt(elt: RdrElt, current_module: str) -> RdrElt | None` - convert to qualified-only

**Remove unused types:**
- `ImportList` (was for explicit import lists)
- `HidingList` (was for hiding imports)
- `_filter_exports()` helper (not needed at this level)

## Why It Works

1. **Type safety:** Split `LocalRdrElt`/`ImportRdrElt` enforces invariant at compile time
2. **Simplicity:** Removed unused features (import lists/hiding) - can add back later
3. **Explicit init:** No `field(default_factory)`, caller provides initial state
4. **Minimal API:** `__init__`, `lookup`, `merge`, `__add__`, `empty()` - everything else is functions
5. **GHC alignment:** Matches validated GlobalRdrEnv design from READER_ENV_EXPLORATION.md

## Files

**Modify:**
- `systemf/src/systemf/elab3/reader_env.py` - Complete rewrite

**Check for breakage:**
- `systemf/src/systemf/elab3/rename.py` - Uses `QualName`, `RdrName`, `ReaderEnv`, `UnqualName`
- `systemf/src/systemf/elab3/repl.py` - Uses `ReaderEnv`

## Migration Notes

**rename.py impact:**
- `QualName`, `RdrName`, `UnqualName` - unchanged
- `ReaderEnv` - construction changes from `ReaderEnv.empty()` (still works) or use `ReaderEnv([])`

**repl.py impact:**
- `ReaderEnv` import - just the type, no immediate breakage

Both files currently don't actively use ReaderEnv (just import it), so no immediate changes needed.
