# Module System Design

**Last Updated:** 2026-03-29

A concrete spec for the systemf module system, derived from GHC analysis.
Exploration notes live at `upstream/ghc/analysis/MODULE_SYSTEM_DESIGN_SKETCH.md`.

## Core Types

### Name

Global identifier for a binding across all modules.

```python
@dataclass
class Name:
    """Globally unique identifier. Uses unique field for O(1) equality."""
    surface: str   # Human-readable: "fromJust"
    unique: int    # Globally unique ID from NameCache
    module: str    # Defining module: "Data.Maybe"
```

**Key property:** Compare via `unique` field (O(1)), display via `surface`.

#### Builtins with Fixed Uniques

Builtin types and primitives have **pre-allocated Uniques** to ensure consistency across sessions:

```python
BUILTIN_UNIQUES: dict[str, int] = {
    # Types
    "Int": 1,
    "Bool": 2,
    "String": 3,
    "List": 4,
    "Pair": 5,
    # Primitives
    "int_plus": 100,
    "int_minus": 101,
    "int_multiply": 102,
    "int_divide": 103,
    # ... etc
}
```

**Usage:** When creating Names for builtins, use the fixed unique instead of allocating from the counter. This ensures `Int` in module A and `Int` in module B are the same Name.

### TyThing

Tagged union representing "things" in the type environment. Simplified from GHC.

```python
@dataclass
class AnId:
    """Term-level binding: variable or function."""
    name: Name
    term: Term          # Elaborated core AST
    type_scheme: TypeScheme

@dataclass
class ATyCon:
    """Type constructor (data type or type synonym)."""
    name: Name
    arity: int
    constructors: list[DataConInfo]  # For data types

@dataclass
class ACon:
    """Data constructor."""
    name: Name
    tag: int            # Unique tag for pattern matching
    arity: int
    parent: Name        # The ATyCon this belongs to

TyThing = AnId | ATyCon | ACon
```

**Key question:** Do TyThings carry their Name redundantly?
- **Yes:** Each variant has a `name` field for direct access
- **TypeEnv keys by Name too:** So Name appears in both key and value
- **Why:** Convenience and provenance tracking

---

## Components

| systemf | GHC | Purpose |
|---------|-----|---------|
| `NameCache` | `NameCache` | Stable unique IDs for (module, name) pairs |
| `HPT` | `HomePackageTable` | Loaded module table |
| `Module` | `ModDetails` | Compilation result (values + types + data cons) |
| `ReaderEnv` | `GlobalRdrEnv` | Surface-name → list of GREs (resolution + ambiguity) |
| `GlobalRdrElt` | `GlobalRdrElt` | One binding: surface name → Name with provenance |
| `REPLSession` | `InteractiveContext` | REPL state |
| `TcEnv` | `TcGblEnv` | Elaboration environment |
| `elaborate` | `tcRnModule` | Renaming + typechecking |

---

## Shared State

These are effectful, session-scoped objects. Forked REPL sessions share them.

```python
class NameCache:
    """Stable unique IDs. Same (module, name) always returns same unique."""
    uniq: Uniq                          # counter
    names: dict[tuple[str, str], Name]  # (module, surface) -> Name

    def get(self, module: str, name: str) -> Name: ...

class HPT:
    """Loaded module table."""
    modules: dict[str, Module]

    def add(self, module: Module) -> None: ... # direct insert (REPL)
    def get(self, name: str) -> Module | None: ...
```

## Loading Protocol

Module loading is orchestrated by `REPL.load()`:

```
REPL.load(module_name)
    ↓
1. Check HPT - already loaded? -> return cached
2. Check REPL._loading - circular? -> raise error
3. Mark _loading.add(module_name)
4. Locate source file on REPL.search_paths
5. Read and parse to AST
6. Extract import declarations
7. For each import: REPL.load(import_name)  # Recursive
8. Build ReaderEnv from loaded modules' exports
9. elaborate(reader_env, ast, cache, hpt, module_name) -> outputs
10. Create Module from outputs
11. HPT.add(module)
12. _loading.remove(module_name)
13. Return module
```

**Key:** Only REPL coordinates loading because it owns the shared mutable state (HPT, NameCache, cycle detection set).

### Data Declaration Processing (2-Pass)

Data declarations require two-pass processing because data constructors reference the type constructor:

```
Pass 1: Process Type Constructors
  For each data declaration:
    - Allocate Name for TyCon via NameCache
    - Create ATyCon (arity from tyvars, empty constructors list)
    - Add to tythings list
    - Merge into ReaderEnv (as Local)

Pass 2: Process Data Constructors  
  For each constructor in data declarations:
    - Allocate Name for DataCon via NameCache
    - Parse field types (reference TyCons from Pass 1 via ReaderEnv)
    - Create ACon (tag, arity, parent=TyCon Name)
    - Add to tythings list
    - Merge into ReaderEnv (as Local)

Pass 3: Link Constructors to Type
  Group ACons by parent TyCon Name
  For each TyCon: update constructors list with its ACons
```

This works because:
- Pass 1 allocates all TyCon Names, making them available in ReaderEnv
- Pass 2 references TyCons by Name (already in ReaderEnv) when parsing field types
- Pass 3 wires the back-references (TyCon.constructors ← list of ACons)

## Surface AST Duplication

The elaborator uses its **own AST types** — it does NOT reuse the surface parser AST:

```python
# Surface parser (in systemf/surface/) - do NOT modify
# Our elaborator (in systemf/elab3/) - define separately

from systemf.elab3.ast import DataDecl, TermDecl  # Our types
# NOT: from systemf.surface.ast import ...        # Surface types
```

**Rationale:**
- Surface AST may change independently
- Elaborator needs additional fields (Name instead of string, etc.)
- Clean separation allows parser improvements without breaking elaboration

## Module (Compilation Result)

```python
@dataclass
class Module:
    """Complete compilation result. Stored in HPT."""
    name: str
    types: dict[Name, TypeScheme]   # Type signatures
    values: dict[Name, Term]        # Elaborated terms
    tythings: list[TyThing]         # All TyThings (redundant with types+values but convenient)
    exports: list[Name]             # AvailInfo: what's exported
    source_path: str | None
    
    def lookup_type(self, name: Name) -> TypeScheme | None: ...
    def lookup_value(self, name: Name) -> Term | None: ...
```

**Exports (AvailInfo):** List of Names this module makes available to importers. For now, simple list. Later can add `hiding` semantics, export specs, etc.

---

## ReaderEnv & Import Specifications

### ReaderEnv

Maps surface names (strings) to resolved internal Names. Corresponds to GHC's `GlobalRdrEnv`.

```python
ReaderEnv = dict[str, list[GlobalRdrElt]]
```

**Structure:** `string → [GlobalRdrElt]` where:
- Same string maps to a list of GREs (different Names with same surface name)
- Multiple GREs = shadowing or ambiguity (NOT the same Name imported twice)
- Resolution dispatches on list length: `[]` → not found, `[single]` → success, `[_, _, ...]` → ambiguity error

### GlobalRdrElt

```python
@dataclass
class GlobalRdrElt:
    """One binding of a surface name to an internal Name."""
    name: Name                    # Resolved Name (unique ID)
    gre_lcl: bool                 # True = locally defined (import bag empty)
    gre_imp: Bag[ImportSpec]      # How imported (Cons list, empty for locals)
```

**Key distinction:**
- `gre_lcl=True`, `gre_imp=empty`: locally defined top-level binding
- `gre_lcl=False`, `gre_imp=non-empty`: imported binding
- Same Name appearing via multiple import paths → merge import bags (O(1) via Cons)
- Different Names with same surface string → separate GREs in the list (shadowing)

### ImportSpec

Two-layer structure tracking how a Name entered scope:

```python
@dataclass
class ImportSpec:
    decl: ImpDeclSpec       # Shared per import declaration
    item: ImpItemSpec       # Per-name granularity

@dataclass
class ImpDeclSpec:
    """Shared context for an entire import declaration."""
    module_name: str        # Source module: "Data.Maybe"
    alias: str | None       # `as M` alias
    qualified: bool         # `qualified` keyword present?
    is_qual: bool           # After shadowNames: True = qualified-only access

type ImpItemSpec = ImpAll | ImpSome

@dataclass
class ImpAll:
    """No explicit import list: `import M`."""

@dataclass
class ImpSome:
    """Explicitly named: `import M (x, y)`."""
    name: str
```

### Import Bag (Cons List)

Import bags use persistent Cons linked lists for O(1) union:

```python
from systemf.utils.cons import Cons, cons

type Bag[T] = Cons[T] | None  # None = empty bag

def union_bags(a: Bag[T], b: Bag[T]) -> Bag[T]:
    if a is None: return b
    if b is None: return a
    return Cons(head=a, tail=b)
```

**Why Cons, not Python list?** Import bags are merged frequently (same name imported via multiple paths). Cons gives O(1) immutable merge vs O(n) list copy.

### Resolution Algorithm

For a surface name `x` in a given context (qualified/unqualified):

1. Look up `x` in ReaderEnv → `elts: list[GlobalRdrElt]`
2. Filter each Elt by accessibility:
   - `gre_lcl=True`: always accessible (local definition)
   - `gre_imp` non-empty: check if any ImportSpec matches context
     - Unqualified lookup: `is_qual=False` on the ImportSpec
     - Qualified lookup `M.x`: `alias == "M"` or `module_name == "M"` on ImpDeclSpec
3. **3-way dispatch:**
   - `[]` → "Not in scope: x"
   - `[elt]` → Success, resolve to `elt.name`
   - `[_, _, ...]` → "Ambiguous occurrence: x" — list candidates

### shadowNames

After each REPL input, previously defined names become qualified-only:

```python
def shadow_names(env: ReaderEnv, new_names: set[Name]) -> ReaderEnv:
    """Set is_qual=True on GREs not in new_names.

    Effect: old names accessible only via qualified syntax (Module.name).
    New names remain accessible both qualified and unqualified.
    """
    result: ReaderEnv = {}
    for surface, elts in env.items():
        result[surface] = [
            elt if elt.name in new_names else _qualify_only(elt)
            for elt in elts
        ]
    return result

def _qualify_only(elt: GlobalRdrElt) -> GlobalRdrElt:
    return GlobalRdrElt(
        name=elt.name,
        gre_lcl=elt.gre_lcl,
        gre_imp=map_bag(_set_is_qual, elt.gre_imp),
    )

def _set_is_qual(spec: ImportSpec) -> ImportSpec:
    return ImportSpec(
        decl=dataclasses.replace(spec.decl, is_qual=True),
        item=spec.item,
    )
```

**Why:** Mirrors GHC's `shadowNames` — old interactive bindings aren't deleted, they become qualified-only. This allows `Ghci3.x` to still reference a shadowed definition.

---

## REPL (Master Object)

The global orchestrator. Owns all shared mutable state and coordinates module loading.

```python
class REPL:
    """Owns shared state, creates sessions, orchestrates module loading.
    
    Contains NameCache which wraps the Uniq counter for generating unique IDs.
    """
    cache: NameCache      # Wraps Uniq counter for stable Name allocation
    hpt: HPT
    search_paths: list[str]
    _loading: set[str]  # Track in-progress loads for cycle detection

    def load(self, module_name: str) -> Module:
        """Load a module and its dependencies into HPT.
        
        Flow:
        1. Check HPT - already loaded? -> return cached
        2. Check _loading - circular? -> raise error
        3. Mark _loading.add(module_name)
        4. Locate source file on search_paths
        5. Read and parse to AST
        6. Extract import declarations from AST
        7. For each import: self.load(import_name)  # Recursive
        8. Build ReaderEnv from loaded modules' exports
        9. elaborate(reader_env, ast, self.cache, self.hpt, module_name) -> outputs
        10. Create Module from outputs
        11. self.hpt.add(module)
        12. _loading.remove(module_name)
        13. Return module
        """
        ...

    def new_session(self) -> REPLSession: ...
```

**Why REPL.load?** 
- Only REPL owns the shared mutable state (HPT, NameCache)
- Loading involves reading HPT (check cached), writing HPT (store result), using NameCache (create Names)
- REPLSession only elaborates its own module - it doesn't do global loads
- Cycle detection via `_loading` set prevents circular imports

---

## REPLSession (Forkable State)

Two-ReaderEnv design mirrors GHC's interactive context: one stable import environment, one growing interactive environment.

```python
class REPLSession:
    """Accumulates imports and bindings. Corresponds to InteractiveContext."""
    cache: NameCache              # Shared ref
    hpt: HPT                      # Shared ref
    import_env: ReaderEnv         # From explicit imports (stable after load)
    interactive_env: ReaderEnv    # From previous REPL inputs (grows, gets shadowed)
    tythings: list[TyThing]       # All definitions including shadowed (like ic_tythings)
    module_counter: int           # Counter for generating module names (1, 2, 3...)

    @property
    def current_module(self) -> str:
        return f"Ghci{self.module_counter}"

    def fork(self) -> REPLSession:
        """Fork this session - shares cache and hpt, copies interactive env."""
        return REPLSession(
            cache=self.cache,
            hpt=self.hpt,
            import_env=self.import_env,                  # Shared (immutable)
            interactive_env=dict(self.interactive_env),  # Copy
            tythings=list(self.tythings),
            module_counter=self.module_counter + 1
        )

    def eval_line(self, input: str) -> None:
        # 1. Parse input
        # 2. Shadow old interactive names
        new_names = extract_defined_names(ast)
        shadowed = shadow_names(self.interactive_env, new_names)
        # 3. Merge: shadowed interactive + imports -> enriched env
        enriched_env = plus_reader_env(shadowed, self.import_env)
        # 4. elaborate(enriched_env, ast, ...) -> outputs
        # 5. Update state
        self.tythings = outputs.tythings + self.tythings  # Prepend!
        self.interactive_env = extend_reader_env(
            self.interactive_env, outputs.tythings, gre_lcl=True
        )
        # 6. Add to HPT
        module = make_module(outputs, self.current_module, exports=[], source_path=None)
        self.hpt.add(module)
```

**Key design points:**
- `tythings` grows unboundedly (like `ic_tythings`) — ALL definitions including shadowed
- `import_env` is populated once during `REPL.load()` and never modified
- `interactive_env` accumulates and gets `shadow_names` applied per input
- Merge order: shadowed interactive env + import env (interactive shadows imports)

---

## Type Checking: Hybrid Lookup

After renaming, all AST references use `Unique` IDs. Type checking uses a hybrid lookup strategy:

**Local bindings** (let/lambda/case bindings within a term):
- Flat `dict[Unique, Type]` populated from the renamed AST
- Single-valued: no shadowing list (innermost binding wins)

**External names** (imports and top-level definitions):
- ReaderEnv lookup: surface name → Name (Unique)
- Then: Name → Type from Module.types or HPT
- Scoped: only names visible at the point of use

**Why hybrid?** The full set of imported names is potentially huge (transitive imports). ReaderEnv provides scoped visibility — only what's in scope, not everything. After resolution, flat dict by Unique is O(1).

---

## Invariants

1. **Unique stability:** Same (module, name) → same unique
2. **Name uniqueness:** No two distinct things share a Name
3. **TyThing/Name consistency:** Each TyThing's `name` field matches its key in TypeEnv
4. **is_local consistency:** `is_local=True` iff name's module == current_module
5. **Cycle freedom:** HPT detects circular imports
6. **Export completeness:** All exported Names exist in Module.types/values
7. **ReaderEnv list invariant:** GREs in each list have different Names (same Name → merged via bag union)
8. **shadowNames invariant:** After shadowing, old GREs have `is_qual=True` on all ImportSpecs
9. **Two-env separation:** import_env is immutable after load; only interactive_env grows and gets shadowed

---

## Open Questions

1. ~~**Dependency analysis:** How to group valbinds into SCCs for typechecking?~~ (RESOLVED - see Exploration Results)
2. **Export specifications:** `module M (foo, Bar(..))` syntax?

---

### NameCache Loading (Interface File Deserialization)

```

Interface files store `(Module, OccName)`, not Uniques.
The NameCache is which `get()` reconstructs Names:

1. Cache hit → return same Name object (same Unique, pointer identity)
2. Cache miss → allocate fresh Unique via global atomic counter, create Name, cache it

**No collision detection** — atomic counter guarantees global uniqueness.
**Same session guarantee** — same `(module, name)` always maps to same Unique.

```
Source: validated exploration `/tmp/NAMECACHE_LOADING_EXPLORATION_2026-03-28_TEMP.md`


### Dependency Analysis

**Validated:** 2026-03-28  
**Sources:** `GHC/Rename/Bind.hs`, `GHC/Tc/Gen/Bind.hs`, `GHC/Types/Basic.hs`, `GHC/Hs/Binds.hs`

This resolves the open question: "How to group valbinds into SCCs for typechecking?"

#### Core Transformation

During renaming, GHC transforms `ValBinds` (source order, no dependency analysis) into `HsValBindGroups` (dependency-analyzed SCCs). This happens via `depAnalBinds` in the renamer.

**Flow:**
```
ValBinds (source order)
    ↓ depAnalBinds (free var analysis)
HsValBindGroups (SCC order)
    ↓ typecheck each group
Typechecked bindings
```

**Key data structures:**

```haskell
-- GHC.Hs.Binds: After renaming, bindings are grouped into SCCs
-- HsValBindGroup = (RecFlag, LHsBinds)
-- HsValBindGroups = HsVBG [HsValBindGroup] [LSig]

data HsValBindGroups p
  = HsVBG [HsValBindGroup (GhcPass p)] [LSig GhcRn]

type instance HsValBindGroup GhcRn = (RecFlag, LHsBinds GhcRn)
```

**RecFlag** (from `GHC.Types.Basic`, NOT `Language.Haskell.Syntax.Binds`):
```haskell
data RecFlag = Recursive | NonRecursive
```

#### SCC Determination

Dependencies between bindings are detected via **free variable analysis**. Each binding records the `Name`s it uses, and the dependency graph is built with edges from a binding to the bindings it depends on.

**SCC to RecFlag mapping:**
```haskell
-- Acyclic (no mutual recursion) → NonRecursive
get_binds (AcyclicSCC (bind, _, _)) = (NonRecursive, [bind])

-- Cyclic (mutual recursion) → Recursive  
get_binds (CyclicSCC binds_w_dus)  = (Recursive, [b | (b,_,_) <- binds_w_dus])
```

#### Source Order vs Dependency Order

- **Source order:** Preserved *within* each SCC
- **Dependency order:** SCCs are topologically sorted (later bindings may depend on earlier ones)
- **Key invariant:** Within an SCC, bindings are in source order; across SCCs, dependencies flow forward

#### Two-Phase SCC Analysis

GHC performs SCC analysis **twice**:

1. **Renamer phase** (`depAnalBinds`): Initial grouping based on all free variables
2. **Typechecker phase** (`tc_rec_group`): For recursive groups, re-analyze omitting variables with type signatures (enables polymorphic recursion)

For systemf, implement phase 1 first. Phase 2 enables advanced features (polymorphic recursion) and can be added later.

#### For systemf Implementation

**Minimal viable approach:**
1. After parsing, collect all value bindings in a list (source order)
2. Build dependency graph using free variable analysis
3. Compute SCCs via standard algorithm (e.g., Tarjan's)
4. Output `[(RecFlag, [Binding])]` where:
   - Single-node acyclic SCC → `(NonRecursive, [binding])`
   - Multi-node or cyclic SCC → `(Recursive, [binding1, binding2, ...])`
5. Typecheck SCCs in order, with each group having access to previous groups' types

---


### TyThing Type Tree

From GHC source (`upstream/ghc/compiler/GHC/Types/TyThing.hs`, `GHC/Core/DataCon.hs`, `GHC/Core/TyCon.hs`, `GHC/Types/Id/Info.hs`):

```
TyThing
├── AnId Id                              -- Value identifiers
│   └── Id (is a Var)
│       ├── varName :: Name
│       ├── varType :: Type
│       ├── id_details :: IdDetails      -- STABLE: what kind of Id
│       │   ├── VanillaId                -- Regular variable
│       │   ├── DataConWorkId DataCon    -- Constructor worker
│       │   ├── DataConWrapId DataCon    -- Constructor wrapper
│       │   ├── ClassOpId Class          -- Class method
│       │   └── ...
│       └── id_info :: IdInfo            -- UNSTABLE: optimization info
│           ├── ruleInfo :: RuleInfo
│           ├── realUnfoldingInfo :: Unfolding
│           ├── dmdSigInfo :: DmdSig
│           └── ...
├── AConLike ConLike                     -- Constructor-like
│   ├── RealDataCon DataCon              -- Real data constructor
│   │   └── MkData {
│   │       dcName :: Name
│   │       dcTag :: ConTag
│   │       dcWorkId :: Id               -- Worker function
│   │       dcRepTyCon :: TyCon          -- Parent type
│   │       ...
│   │   }
│   └── PatSynCon PatSyn                 -- Pattern synonym
├── ATyCon TyCon                         -- Type constructors
│   └── TyCon {
│       tyConName :: Name
│       tyConDetails :: TyConDetails
│           ├── AlgTyCon { algTcRhs :: AlgTyConRhs }
│           ├── SynonymTyCon { synTcRhs :: Type }
│           └── ...
│   }
└── ACoAxiom (CoAxiom Branched)          -- Type family axioms
```

**Key insight:** Heavily decorated with optimization metadata (strictness, unfolding, rules, demand). We simplified to `AnId | ATyCon | ACon` without the metadata.

---

### TcGblEnv Downstream Usage

From GHC analysis (`upstream/ghc/analysis/TYPECHECK_OUTPUT_EXPLORATION.md`):

**TcGblEnv as accumulator AND output:**
```
Typechecking Phase
==================
Source Code
    ↓
tcRnModule → tcRnSrcDecls
    ↓
For each declaration:
    - Typecheck → accumulate in tcg_binds, tcg_rules
    - Update tcg_type_env
    ↓
Final TcGblEnv with all fields populated


Downstream Pipeline
===================
TcGblEnv
    ↓
tidyProgram / mkBootModDetailsTc
    ├──→ CgGuts { cg_binds, ... } ──→ Core → STG → Cmm → Native code
    │                                     (from tcg_binds)
    │
    └──→ ModDetails { md_types, md_rules, ... }
              ↓
         mkIface_ ──→ ModIface ──→ .hi file (serialized)
              ↓
         HPT storage (for other modules to import)
```

**Where outputs go:**
| TcGblEnv Field | Downstream Use |
|----------------|----------------|
| `tcg_type_env` | ModDetails.md_types → HPT + .hi files |
| `tcg_binds` | CgGuts → Core → Code generation |
| `tcg_rules` | ModDetails.md_rules → Core optimizer |
| `tcg_exports` | ModDetails.md_exports → .hi files |
| `tcg_insts` | ModDetails.md_insts → Type class resolution |

**For systemf:** Our Module combines both roles - it stores types AND executable Terms (no separate Core/STG/Cmm pipeline).

---

### AvailInfo (Exports)

**Correction from previous version:** AvailTC uses `[Name]` only, not `[FieldLabel]`. Field labels are tracked separately in TyCon.

From validated GHC analysis:

```haskell
data AvailInfo
  = Avail Name               -- Simple identifier in scope
  | AvailTC Name [Name]      -- Type/class with its children
```

**Key properties:**
- **Two constructors:** `Avail` for simple identifiers, `AvailTC` for types/classes bundled with their children
- **AvailTC invariant:** If the type/class itself is in scope, it must be FIRST in the list
  - Example: `AvailTC Eq [Eq, (==), (/=)]` or `AvailTC T [T, MkT1, MkT2, fieldSel]`

**Export processing flow:**
```
Source: module M (T(..), foo) where ...
    ↓
rnExports (GHC.Tc.Gen.Export)
    - Looks up exports in GlobalRdrEnv
    - Finds children via kids_env
    - Creates AvailTC T [T, MkT1, MkT2, fieldSel] and Avail foo
    ↓
tcg_exports = [AvailTC T [T, MkT1, MkT2, fieldSel], Avail foo]
    ↓
ModDetails.md_exports → mkIface_ → ModIface.mi_exports
    ↓
Written to M.hi interface file
```

**Import processing:**
```
Load M.hi → get mi_exports (AvailInfos)
    ↓
gresFromAvails (GHC.Rename.Names)
    - Converts AvailInfo to GREs via mkParent
    - Filters based on import spec (e.g., import M (T(MkT1)))
    ↓
GlobalRdrEnv for name resolution
```

**Key operations on AvailInfo:**
| Operation | Purpose |
|-----------|---------|
| `plusAvail` | Merge two AvailInfos with same parent (union of children) |
| `filterAvail` | Keep only names matching a predicate |
| `trimAvail` | Keep only a specific name from an AvailTC |
| `gresToAvailInfo` | Convert GREs to AvailInfos (groups children under parents) |
| `availFromGRE` | Create single AvailInfo from one GRE |

**For systemf:** Start with simple `list[Name]` for exports, but design to accommodate `AvailTC`-style bundling for proper `T(..)` export support.

---

### NameCache Unique Loading

**Sources:** `GHC/Types/Name/Cache.hs`, `GHC/Iface/Binary.hs`, `GHC/Iface/Env.hs`, `GHC/Types/Unique/Supply.hs`

How Names and Uniques are reconstructed when loading interface files.

#### Core Mechanism

Interface files (.hi) store names as `(UnitId, ModuleName, OccName)` triples in a symbol table — **not** Uniques. Uniques are ephemeral and differ between sessions. The NameCache reconstructs them at load time:

1. **Cache hit** (name already in NameCache): return the **same** `Name` object (pointer identity, same Unique).
2. **Cache miss** (name not yet seen): allocate a fresh Unique from a global atomic counter, create a new `Name`, insert into cache, return it.

This guarantees that within one session, the same external name always gets the same Unique, even if referenced from multiple interface files.

#### NameCache Structure (GHC)

```haskell
-- Two-level map, MVar-protected for thread safety
type OrigNameCache = ModuleEnv (OccEnv Name)  -- Module -> (OccName -> Name)

data NameCache = NameCache
  { nsUniqChar :: Char              -- Tag for unique generation
  , nsNames    :: MVar OrigNameCache
  }
```

The NameCache lives in `HscEnv.hsc_NC` and is shared across all modules compiled in a session.

#### Unique Generation

Fresh Uniques come from `genSym`, which uses an atomic fetch-and-add on a global C-level counter (`ghc_unique_counter64`). This is thread-safe without Haskell-level locks. The counter is shared across all Unique allocation paths, ensuring global uniqueness.

```haskell
takeUniqFromNameCache :: NameCache -> IO Unique
takeUniqFromNameCache (NameCache c _) = uniqFromTagGrimly c

uniqFromTagGrimly :: Char -> IO Unique
uniqFromTagGrimly tag = do
    uqNum <- genSym  -- atomic fetch-and-add
    return $ mkUniqueGrimilyWithTag tag uqNum
```

#### Symbol Table Reconstruction (getSymbolTable)

When reading an interface file, `getSymbolTable` processes all `(UnitId, ModuleName, OccName)` triples in a single atomic MVar transaction:

```haskell
-- Simplified from GHC/Iface/Binary.hs
getSymbolTable bh name_cache = do
    updateNameCache' name_cache $ \cache0 -> do
        -- For each (uid, mod_name, occ) in symbol table:
        case lookupOrigNameCache cache mod occ of
            Just name -> (cache, name)       -- HIT: reuse existing Name
            Nothing   -> do
                uniq <- takeUniqFromNameCache nc  -- MISS: fresh Unique
                let name = mkExternalName uniq mod occ noSrcSpan
                let new_cache = extendOrigNameCache cache mod occ name
                (new_cache, name)
```

Key points:
- The entire symbol table is processed in one `updateNameCache'` call (single MVar transaction).
- Cache state is threaded through, so names allocated early are visible to later entries.
- Names on the miss path get `noSrcSpan`; the SrcSpan is updated later at the binding site.

#### allocateGlobalBinder — SrcSpan Update on Cache Hit

Called at binding sites where the full source location is known. On a cache hit for non-wired-in names, it creates a new `Name` with the **same Unique** but updated SrcSpan:

```haskell
allocateGlobalBinder nc mod occ loc =
    updateNameCache nc mod occ $ \cache0 ->
        case lookupOrigNameCache cache0 mod occ of
            Just name
                | isWiredInName name -> (cache0, name)        -- WiredIn: unchanged
                | otherwise ->
                    let uniq  = nameUnique name                -- SAME Unique
                        name' = mkExternalName uniq mod occ loc  -- Updated SrcSpan
                    in (extendOrigNameCache cache0 mod occ name', name')
            Nothing -> do
                uniq <- takeUniqFromNameCache nc
                let name = mkExternalName uniq mod occ loc
                (extendOrigNameCache cache0 mod occ name, name)
```

This handles names that were first seen as forward references (with `noSrcSpan`) and are now being defined.

#### Pre-Seeded Wired-In Names

The NameCache is initialized with `knownKeysOrigNameCache`, which pre-populates all wired-in/known-key Names (`Int`, `Bool`, `(->)`, etc.). These have pre-assigned Uniques baked into the compiler. Infinite families (tuples, sums) are computed on-the-fly rather than stored.

#### Compilation Pipeline Summary

```
Source Code
    ↓ parse
AST
    ↓ rename (resolve names via NameCache)
Renamed AST
    ↓ typecheck (TyThings get Names from NameCache)
TcGblEnv (types, bindings, exports)
    ↓
ModDetails (md_types: dict[Name, TyThing])
    ↓
Module stored in HPT
```

TyThings in ModDetails get their Names from the NameCache via `(Module, OccName)` lookups. The NameCache ensures consistent identity throughout the pipeline.

#### For systemf Implementation

The existing `NameCache` design in the Core Types section is correct in spirit. Key refinements informed by this analysis:

1. **`NameCache.get()`** should implement hit/miss logic: return cached `Name` on hit, allocate fresh Unique on miss and insert.
2. **Names carry module provenance.** The `(module, surface)` key is the persistent identity — Uniques are derived, not stored.
3. **No SrcSpan tracking needed initially.** GHC's `allocateGlobalBinder` SrcSpan update is an optimization for error messages. systemf can use `noSrcSpan` initially.
4. **Wired-in names.** Pre-seed the NameCache with built-in types (`Int`, `Bool`, `(->)`, etc.) at session start, each with a stable Unique.
5. **Thread safety.** For single-threaded systemf, the MVar is unnecessary. A simple dict suffices. If parallelism is added later, wrap in a lock.
