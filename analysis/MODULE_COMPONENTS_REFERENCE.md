# Module System Components Reference

Components defined during module system design discussion.

## Core Data Structures

### HomePackageTable (HPT)

**Purpose:** Global table tracking all loaded modules.

**Responsibilities:**
- Store loaded module entries
- Detect circular imports (via in-progress tracking)
- Provide module lookup by name

**State:**
```python
modules: dict[str, ModuleEntry]     # Completed loads
in_progress: set[str]                # Currently loading (for cycle detection)
```

**Operations:**
- `get(name)` - Retrieve loaded module
- `start_loading(name)` - Mark import in-progress (raises on cycle)
- `finish_loading(name, entry)` - Store completed module

---

### ModuleEntry

**Purpose:** Runtime representation of a loaded module's contents.

**Responsibilities:**
- Store elaborated terms ready for execution
- Provide data constructor information
- Track source location for debugging

**Contents:**
```python
values: dict[Name, Term]         # Name -> elaborated core AST
                                  # These are executable, not just types
data_cons: dict[int, DataConInfo] # Unique -> constructor info
                                  # Used for pattern matching
source_path: str | None           # Original source file
```

**Distinction from GHC:** 
- GHC stores TyThings (types only)
- We store executable Terms (values)

---

### NameCache

**Purpose:** Ensure consistent unique IDs across module boundaries.

**Responsibilities:**
- Assign stable unique IDs to (module, name) pairs
- Persist across imports and elaboration sessions
- Enable O(1) name equality checks

**State:**
```python
cache: dict[tuple[str, str], int]  # (module, surface_name) -> unique
next_unique: int                    # Counter for new names
```

**Key Property:** 
Same (module, name) always returns same unique, regardless of when/where imported.

**Example:**
```python
cache.get("Data.Maybe", "fromJust")  # -> 42
cache.get("Data.Maybe", "fromJust")  # -> 42 (same!)
```

---

### Name

**Purpose:** Global identifier for a binding.

**Responsibilities:**
- Uniquely identify a value across all modules
- Enable O(1) equality comparison
- Carry module provenance for lookup

**Structure:**
```python
@dataclass
class Name:
    surface: str      # Human-readable: "fromJust"
    unique: int       # Globally unique ID from NameCache
    module: str       # Defining module: "Data.Maybe"
```

**Operations:**
- Equality: compare `unique` field (O(1))
- Hash: use `unique` (O(1))
- Display: use `surface` (for error messages)

---

### DataConInfo

**Purpose:** Runtime information about data constructors.

**Responsibilities:**
- Store constructor tag for pattern matching
- Track arity for partial application
- Link to human-readable name

**Structure:**
```python
@dataclass
class DataConInfo:
    name: str         # Human-readable: "Just"
    tag: int          # Unique ID (from NameCache)
    arity: int        # Number of arguments
```

**Usage:**
```python
# In pattern matching:
if scrutinee.tag == pattern_tag:
    # Match succeeded
```

---

## Runtime Values

### GlobalVar

**Purpose:** Reference to a top-level definition.

**Responsibilities:**
- Represent module-level binding references in core AST
- Enable cross-module value access

**Structure:**
```python
@dataclass
class GlobalVar(Term):
    name: Name        # Fully qualified global reference
```

**Resolution:**
```python
def eval_globalvar(hpt, global_var):
    entry = hpt.get(global_var.name.module)
    term = entry.values[global_var.name]
    return eval_term(term)
```

**Distinction from Var:**
- `Var` uses de Bruijn index (local variable)
- `GlobalVar` uses Name (module-level binding)

---

### Term (Core AST)

**Purpose:** Executable intermediate representation.

**Variants:**
- `Lit` - Integer literals
- `Var` - Local variables (de Bruijn)
- `GlobalVar` - Module-level references
- `Lam` - Lambda abstraction
- `App` - Function application
- `Let` - Non-recursive binding
- `LetRec` - Recursive bindings
- `Case` - Pattern matching

**Lifecycle:**
1. Parse surface syntax -> AST
2. Elaborate AST -> Term (type checking, name resolution)
3. Store Term in HPT
4. Evaluate Term -> Val (when GlobalVar resolved)

---

## Processing Flows

### Import Processing

**Purpose:** Load a module and its dependencies.

**Flow:**
```
import_module(hpt, cache, module_name)
    ↓
1. Check HPT - already loaded?
    ├─ Yes -> return cached entry
    └─ No -> continue
    ↓
2. Check in_progress - circular?
    ├─ Yes -> raise CircularImportError
    └─ No -> add to in_progress
    ↓
3. Load source file
    ↓
4. Parse to AST
    ↓
5. Process imports (recursive)
    ↓
6. Elaborate to ModuleEntry
    ↓
7. Store in HPT
    ↓
8. Remove from in_progress
```

**Key Invariant:**
Module is in `in_progress` from step 2 to step 8. Any attempt to import it during this window triggers cycle detection.

---

### Elaboration

**Purpose:** Transform surface AST to executable core Term.

**Inputs:**
- AST from parser
- HPT (for resolving imports)
- NameCache (for generating stable uniques)

**Outputs:**
- ModuleEntry with:
  - values: Name -> Term mappings
  - data_cons: constructor information

**Name Resolution:**
```python
# During elaboration:
def resolve_name(surface_name, current_module):
    if defined_locally(surface_name):
        return Name(surface_name, cache.get(current_module, surface_name), current_module)
    else:
        # Must be imported
        imported_from = find_import_source(surface_name)
        return Name(surface_name, cache.get(imported_from, surface_name), imported_from)
```

---

### GlobalVar Resolution (at runtime)

**Purpose:** Convert GlobalVar reference to runtime value.

**Flow:**
```
eval(GlobalVar(name), env, k)
    ↓
1. HPT lookup: entry = hpt.get(name.module)
    ↓
2. Term lookup: term = entry.values[name]
    ↓
3. Evaluate term to value
    ↓
4. Continue with value
```

**Performance:**
- HPT lookup: O(1) hash
- Term lookup: O(1) hash by unique
- Total: O(1)

---

## State Management

### NameCache Lifecycle

**Lifetime:** Session-wide (or persistent)

**Usage Pattern:**
```python
# Create once
name_cache = NameCache()

# Pass to all elaboration
entry1 = elaborate(ast1, hpt, name_cache)
entry2 = elaborate(ast2, hpt, name_cache)

# Same names get same uniques
```

**Why Persistent:**
- Importing module A then B: names from A must keep same unique
- REPL: new inputs must reference existing names
- Pattern matching: constructor tags must match across modules

---

### HPT Lifecycle

**Lifetime:** Per session

**Usage Pattern:**
```python
hpt = HomePackageTable()

# File mode:
main_entry = import_module(hpt, cache, "Main")

# REPL mode:
import_module(hpt, cache, "Prelude")  # Base imports
repl_entry = create_repl_module(hpt, cache)
# ... add REPL inputs to repl_entry ...
```

---

## Relationships

```
NameCache (global, persistent)
    ├── provides uniques to ──> Elaboration
    ├── provides tags to ────> DataConInfo
    └── used by ─────────────> Name equality

HPT (per session)
    ├── contains ────────────> ModuleEntry
    ├── tracks ──────────────> in_progress (cycle detection)
    └── queried by ──────────> GlobalVar resolution

ModuleEntry (per loaded module)
    ├── contains ────────────> values: Name -> Term
    ├── contains ────────────> data_cons: Unique -> DataConInfo
    └── provides ────────────> Terms for evaluation

Term (core AST)
    ├── contains ────────────> GlobalVar (references other modules)
    ├── contains ────────────> Var (local variables)
    └── evaluated to ────────> Val

Name (identifier)
    ├── contains ────────────> unique (from NameCache)
    ├── used as key in ──────> ModuleEntry.values
    └── compared via ────────> unique field
```

## Invariants

1. **Unique Stability:** Same (module, surface) → same unique
2. **Cycle Freedom:** in_progress check prevents circular imports
3. **Term Immutability:** Once stored in HPT, Term never changes
4. **Name Resolution:** Every GlobalVar resolves to some ModuleEntry.values entry
5. **Tag Uniqueness:** DataConInfo.tag is unique across all constructors

## Open Design Questions

1. **Memory Management:** When to evict from HPT?
2. **Recompilation:** How to detect stale modules?
3. **Parallel Imports:** Can we load independent modules concurrently?
4. **REPL Context:** How to handle incremental REPL module updates?
