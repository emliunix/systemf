# Module System Design Sketch

**Last Updated:** 2026-03-28
**Previous Version:** Initial draft (pre-level-separation)

Based on analysis of GHC's architecture, a streamlined module system for a modern language.

## Architectural Insight: Module Object = Compilation Result

### The Core Principle

GHC's module object (`ModDetails`) stores **only the compilation result**: exported types,
instances, rules, and linkable code. It does NOT store import declarations, reader
environments, or any source-level structure. Import processing is a pipeline step that
produces a reader env as transient workflow context — the module object never looks back
at its import specs.

This principle is confirmed by GHC's `ModDetails` (compiler/GHC/Unit/Module/ModDetails.hs:20-43)
which has 8 fields, none relating to imports:

```haskell
data ModDetails = ModDetails
   { md_exports           :: [AvailInfo]
   , md_types             :: !TypeEnv
   , md_defaults          :: !DefaultEnv
   , md_insts             :: InstEnv
   , md_fam_insts         :: ![FamInst]
   , md_rules             :: ![CoreRule]
   , md_anns              :: ![Annotation]
   , md_complete_matches  :: CompleteMatches
   }
```

**Implication for systemf:** `ModuleEntry` should only store compilation results (values,
data_cons). Import specs are not a property of the module object — they belong to the
pipeline that produces it.

### Three Distinct Levels

The module system has three conceptual levels that must not be conflated:

| Level | What | Lifetime | GHC Analog |
|-------|------|----------|------------|
| **1. AST** | Source file with import declarations | Ephemeral (parse → discard) | `HsModule` with `hsmodImports` |
| **2. Pipeline context** | Reader env built from imports | Transient (during compilation) | `tcg_rdr_env` on `TcGblEnv` |
| **3. Module result** | Resolved names, typed terms, data cons | Persistent (stored in HPT) | `ModDetails` |

**Why this matters:** Conflating levels leads to designs that store import specs on module
objects or mix source-level structure with runtime state. The current `ModuleEntry` in
`MODULE_COMPONENTS_REFERENCE.md` correctly stores only level 3 (values + data_cons).

### Reader Env Is Always Derived, Never Stored

The reader environment used for name resolution is always derived from other data:

- **File compilation:** derived from source import declarations + loaded modules' exports
  (GHC: `tcRnImports` → `tcg_rdr_env` via `plusGlobalRdrEnv`)
- **REPL:** derived from accumulated IC state (`ic_imports` + `ic_tythings` → `icReaderEnv`)

The module object (`ModDetails` / `ModuleEntry`) never holds its own reader env. This is
confirmed across three GHC source locations: `ModDetails` has no reader env field,
`icReaderEnv` lives on `InteractiveContext` (not on a module), and `tcg_rdr_env` is on
`TcGblEnv` with the comment "used during renaming" — transient compilation state.

## Two Processing Flows

GHC has two fundamentally different flows for building name resolution context. These flows
do NOT share reader environments.

### Flow 1: File Compilation

```
Parse source
    ↓
Extract import declarations (hsmodImports)
    ↓
For each import: load interface, extract exports
    ↓
Build tcg_rdr_env from imports via plusGlobalRdrEnv
    (compiler/GHC/Tc/Module.hs:493)
    ↓
Rename + typecheck using tcg_rdr_env
    ↓
Produce ModDetails (compilation result — no import info)
```

Key: `tcg_rdr_env` is built **fresh** from the source file's import declarations each time.
It is transient state on `TcGblEnv`, discarded after compilation.

### Flow 2: REPL / Interactive Context

```
InteractiveContext maintains session state:
    ic_imports   :: [InteractiveImport]    -- User's import statements
    ic_tythings  :: [TyThing]              -- Previous REPL definitions
    ic_gre_cache :: IcGlobalRdrEnv         -- Combined name resolution env
    ↓
icReaderEnv derived from ic_gre_cache:
    icReaderEnv = igre_env . ic_gre_cache
    (compiler/GHC/Runtime/Context.hs:374-375)
    ↓
When user enters statement, runTcInteractive copies:
    tcg_rdr_env = icReaderEnv icxt
    (compiler/GHC/Tc/Module.hs:2148)
    ↓
Typecheck statement using copied env
    ↓
Update IC with new tythings → rebuild ic_gre_cache
```

Key: The REPL's reader env accumulates across interactions. It is **derived** from IC state,
never stored on any module object. `runTcInteractive` bridges IC → standard `TcGblEnv` by
copying the pre-built reader env.

## Design Goals

1. **Simplicity** - Fewer concepts than GHC, clearer boundaries
2. **Level separation** - Explicit distinction between pipeline context and module results
3. **Explicit state** - No lazy knots, explicit loading order
4. **Fast lookup** - O(1) everywhere possible
5. **Clear REPL semantics** - Interactive and batch modes as distinct pipelines sharing a core

## Core Concepts

### Module Identity

```
Module = Package + Name + Version

Example: ("base", "Data.Maybe", 1)
```

**Principle**: Identity is immutable and unique. No "home unit" vs "package" distinction.

### Three Kinds of Names

```
SurfaceName (OccName in GHC)
  - Just the string: "foo"
  - Used in source code, parser output

ResolvedName (Name in GHC)
  - Module + SurfaceName + Unique ID
  - Created during name resolution
  - Unique = hash(Module + SurfaceName) for external names

InternalName
  - Unique ID only
  - For compiler-generated bindings
```

**Simplification**: No "Exact" names in RdrName. Everything goes through resolution.

## Environment Architecture

The architecture separates **pipeline structures** (used during compilation) from **result
structures** (stored in module objects). This follows the three-level model confirmed by
GHC's own design.

### Pipeline Level: Reader Environment

Used during name resolution (renaming). Built fresh for each compilation unit, discarded
afterward. Contains only names and provenance — no types, no code.

```haskell
data ReaderEnv = ReaderEnv
  { reOccTable :: HashMap SurfaceName [RdrElt]  -- O(1) string lookup
  , reImports  :: [ImportSpec]                    -- Active import specifications
  }

data RdrElt = RdrElt
  { reName   :: ResolvedName
  , reSource :: RdrSource     -- Local | Imported
  , reSpec   :: Maybe ImportSpec  -- Nothing for local; Just for imported
  }

data RdrSource = Local | Imported
```

**ImportSpec** is pipeline context — it lives here, on `ReaderEnv`, NOT on the module result.

```haskell
data ImportSpec = ImportSpec
  { isFrom      :: Module
  , isQualified :: Bool
  , isAlias     :: Maybe ModuleName  -- "as M"
  , isHiding    :: [SurfaceName]     -- Explicit import list
  }
```

**How ReaderEnv is built (Flow 1 — file compilation):**
```
1. Extract import declarations from parsed AST
2. For each import: load interface, get exports
3. Create RdrElts with ImportSpec provenance
4. Merge into ReaderEnv via occTable union
5. Use during renaming, then discard
```

### Result Level: Type Environment

Stored in `ModuleEntry` (the compilation result). Keyed by `Name` (with unique), contains
actual types and executable terms.

```haskell
data TypeEnv = TypeEnv
  { teUniqTable :: IntMap TyThing  -- O(1) lookup by unique
  }

data TyThing
  = AnId   { tiTerm :: Term }       -- Executable value
  | ATyCon { tiCon  :: TyConInfo }  -- Type constructor info
  | AData  { tiCons :: [DataConInfo] } -- Data constructors
```

**The bridge:** `ReaderEnv` resolves `SurfaceName` → `ResolvedName` (with unique).
`TypeEnv` resolves `ResolvedName` → `TyThing`. The `Name` is the common currency between
them — same pattern as GHC (GlobalRdrEnv → Name → TypeEnv).

### Why Two Environments (Not One)

| Concern | ReaderEnv | TypeEnv |
|---------|-----------|---------|
| **Phase** | Renaming | Typechecking |
| **Key** | SurfaceName (string) | ResolvedName (unique) |
| **Value** | Name + provenance (small) | Type + term (large) |
| **Lifetime** | Transient (per compilation) | Persistent (in ModuleEntry) |
| **Rebuild freq** | Every import change | Only on recompilation |

A unified environment conflates these concerns. GHC deliberately separates them because:
- ReaderEnv is small and frequently rebuilt; TypeEnv is large and stable
- Renaming must handle qualification, aliasing, shadowing; typechecking only needs unique → definition
- Separation allows lazy loading of TyThings (only when typechecking needs them)

## Module Storage

### ModuleCache (HomePackageTable)

```haskell
data ModuleCache = ModuleCache
  { cachedModules :: HashMap Module CachedModule
  , cachedPackages :: HashMap PackageName PackageInfo
  }

data CachedModule = CachedModule
  { cmInterface :: Interface  -- Always loaded (small)
  , cmDetails   :: MVar ModDetails  -- Loaded on demand (lazy but explicit)
  }

-- Interface = exports + dependencies + version
-- ModDetails = type env + instances + etc
```

**Difference from HPT**: Explicit `MVar` instead of implicit lazy evaluation. Clear concurrency story.

### ModuleEntry (Compilation Result Only)

Aligned with `MODULE_COMPONENTS_REFERENCE.md` — stores only level 3 data:

```python
@dataclass
class ModuleEntry:
    values: dict[Name, Term]          # Elaborated core AST (executable)
    data_cons: dict[int, DataConInfo]  # Constructor info for pattern matching
    source_path: str | None            # Original source file
```

**No import specs, no reader env, no source AST.** This is the compilation output.

### Loading Protocol

```
1. Load interface file
2. Cache interface in ModuleCache
3. Create MVar for ModDetails (empty)
4. On first use: load ModDetails, fill MVar
```

## Name Resolution

### Two-Stage Resolution

```haskell
-- Stage 1: Renaming (uses ReaderEnv)
resolveName :: SurfaceName -> ReaderEnv -> Either Error ResolvedName
resolveName surface renv =
  case HashMap.lookup surface (reOccTable renv) of
    Nothing -> Left (NotInScope surface)
    Just [elt] -> Right (reName elt)
    Just elts ->
      case filter (visibleInContext surface) elts of
        [e] -> Right (reName e)
        []  -> Left (NotInScope surface)
        es  -> Left (Ambiguous surface (map reName es))

-- Stage 2: Type lookup (uses TypeEnv)
lookupType :: ResolvedName -> TypeEnv -> Maybe TyThing
lookupType name tenv = IntMap.lookup (nameUnique name) (teUniqTable tenv)
```

**The two-stage flow mirrors GHC exactly:**
1. `SurfaceName` → `ReaderEnv` → `ResolvedName` (renaming)
2. `ResolvedName` → `TypeEnv` → `TyThing` (typechecking)

### Visibility Check

```haskell
visibleInContext :: SurfaceName -> RdrElt -> Bool
visibleInContext surface elt =
  case reSource elt of
    Local -> True
    Imported ->
      case reSpec elt of
        Nothing -> True
        Just spec ->
          not (isQualified spec) ||
          matchesAlias surface spec
```

### Qualified Lookup

```haskell
resolveQualified :: ModuleName -> SurfaceName -> ReaderEnv -> Either Error ResolvedName
resolveQualified mod surface renv =
  case findImportForModule mod renv of
    Nothing -> Left (NoSuchModule mod)
    Just spec ->
      lookupExport (isFrom spec) surface renv
```

## Interactive Context

### REPL State (Derived Env Pattern)

The REPL maintains its own state from which the reader environment is **derived**, mirroring
GHC's `InteractiveContext` → `icReaderEnv` pattern:

```haskell
data ReplState = ReplState
  { replImports  :: [ImportDecl]        -- User's import statements (level 1)
  , replBindings :: [Binding]           -- Definitions from previous lines (level 3)
  , replCache    :: ModuleCache          -- Loaded modules
  }
```

**Key difference from previous design:** `replEnv` is NOT stored — it is derived:

```haskell
-- Build ReaderEnv from accumulated state (like icReaderEnv)
deriveReaderEnv :: ReplState -> ReaderEnv
deriveReaderEnv state = ReaderEnv
  { reOccTable = buildOccTable (importElts ++ localElts)
  , reImports  = map toImportSpec (replImports state)
  }
  where
    importElts = concatMap (loadExports . isFrom) (replImports state)
    localElts  = map toLocalElt (replBindings state)

-- Build TypeEnv from accumulated state
deriveTypeEnv :: ReplState -> TypeEnv
deriveTypeEnv state = TypeEnv
  { teUniqTable = buildUniqTable (replBindings state)
  }
```

### REPL Processing Flow (mirrors runTcInteractive)

```
User enters statement:
    ↓
1. deriveReaderEnv(replState)     -- Build env from accumulated state
2. deriveTypeEnv(replState)       -- Build type env from bindings
3. Typecheck statement using both  -- Like runTcInteractive copying to tcg_rdr_env
    ↓
If statement is a definition:
    ↓
4. Create Binding for new definition
5. Prepend to replBindings (new shadows old)
6. Next statement will see updated bindings in derived env
    ↓
If statement is an import:
    ↓
4. Add ImportDecl to replImports
5. Load interface for imported module
6. Next statement will see updated imports in derived env
```

### Shadowing Rules

```haskell
addBinding :: Binding -> ReplState -> ReplState
addBinding new state = state
  { replBindings = new : replBindings state
  }
-- New binding prepended = shadows old ones in derived env
-- Like GHC: ic_tythings "in reverse order of definition"
```

**Key**: Shadowing is handled by list ordering during derivation. The derived env always
reflects the current state.

## Type Checking Integration

### Pipeline: ReaderEnv + TypeEnv → TcEnv

```haskell
-- During compilation, both environments are available:
data ElabEnv = ElabEnv
  { elabReaderEnv :: ReaderEnv   -- For resolving names in source
  , elabTypeEnv   :: TypeEnv     -- For looking up types of resolved names
  , elabCache     :: ModuleCache -- For cross-module lookups
  }
```

**This mirrors GHC's `TcGblEnv` which has both `tcg_rdr_env` and `tcg_type_env`.**

The `ElabEnv` is transient (pipeline level) — it is not stored in `ModuleEntry`.

## Comparison with GHC

| Aspect | GHC | This Design |
|--------|-----|-------------|
| Name environments | GlobalRdrEnv + TypeEnv (separate) | ReaderEnv + TypeEnv (separate) |
| Env separation rationale | Architectural: different phases, keys, lifetimes | Same rationale |
| Module result | ModDetails (types, instances, rules) | ModuleEntry (values, data_cons) |
| Module stores imports? | No — ModDetails has no import fields | No — aligned with GHC |
| Reader env on module? | No — tcg_rdr_env is transient | No — ReaderEnv is pipeline-level |
| REPL split | ic_imports + ic_tythings (separate lists) | replImports + replBindings (separate) |
| REPL reader env | Derived via icReaderEnv from IC state | Derived via deriveReaderEnv from ReplState |
| REPL caching | ic_gre_cache with igre_prompt_env | Derived on demand from bindings list |
| Module storage | HPT with lazy details | ModuleCache with MVar |
| Lazy loading | Implicit laziness (thunks) | Explicit MVar |
| Shadowing | IC: reverse order of definition; igre_prompt_env for efficient rebuild | List ordering in deriveReaderEnv |
| Name types | OccName, RdrName, Name | SurfaceName, ResolvedName |
| Binding provenance | GRE with ImportSpec in GlobalRdrEnv | RdrElt with ImportSpec in ReaderEnv |

## Open Questions

1. **Cross-module recursion**: How to handle mutually recursive modules?
2. **Package boundaries**: How strict is the Package + Module + Version identity?
3. **Incremental compilation**: Interface file format for fast dependency checking?
4. **Instance environments**: Where do type class instances live?
5. **Interface vs runtime**: Should systemf have a formal "interface" concept (like GHC's ModIface) separate from the runtime ModuleEntry?
6. **Elaboration environment**: What exactly goes in the elaboration environment (ElabEnv) for each flow?
7. **REPL efficiency**: How does the REPL's derived env get rebuilt efficiently after each statement? (GHC uses igre_prompt_env for incremental rebuild.)
8. **Simplification path**: Should we start with a simplified single-env approach (per DESIGN_NOTE_IMPORT_ENV_SEPARATION.md Option B) and refactor to separation later, or build the separation in from the start?

## Next Steps

1. Specify Interface format (exports + dependencies + version)
2. Design ModuleCache eviction policy
3. Define error messages for name resolution failures
4. Prototype ReaderEnv and TypeEnv data structures (separately)
5. Implement deriveReaderEnv for REPL flow
6. Implement the file compilation flow with transient ReaderEnv

## Corrections Log

**Date:** 2026-03-28

### Corrections from level-separation analysis

| What Changed | Old Content | New Content | Reason |
|-------------|-------------|-------------|--------|
| Design goal #2 | "Unified environments — Single consistent environment model" | "Level separation — Explicit distinction between pipeline context and module results" | GHC's separation of GlobalRdrEnv and TypeEnv is essential, not redundant. A unified env conflates renaming and typechecking phases (RDRENV_TYPEENV_RELATION_EXPLORATION.md). |
| Binding/BindingSource | `BindingSource = Local \| Import ImportSpec` with ImportSpec on Binding | Removed ImportSpec from result-level Binding. RdrElt in ReaderEnv carries ImportSpec instead. | ImportSpec is pipeline context (how a name was found), not a property of the compiled module. ModDetails has no import fields (Finding 1). |
| NameEnv (unified) | Single `NameEnv` serving "both renamer and type checker" | Separate `ReaderEnv` (pipeline) and `TypeEnv` (result) | The two envs have different keys, values, lifetimes, and rebuild frequencies. GHC deliberately separates them. |
| ReplState | Stored `replEnv :: NameEnv` directly | `replEnv` removed; env is derived via `deriveReaderEnv` | Mirrors GHC's `icReaderEnv` which is derived from `ic_gre_cache`, not stored as a raw field. Reader env is always derived (Finding 4). |
| REPL update | "Add exports to replEnv" (implying mutation of stored env) | "deriveReaderEnv from accumulated state" (always recomputed) | GHC's IC rebuilds ic_gre_cache from ic_imports + ic_tythings. The env is a derived view, not mutable state. |
| Processing flows | Single implicit flow | Explicit Flow 1 (file compilation) and Flow 2 (REPL/IC) | These are fundamentally different pipelines with different env sources (Finding 3). |
| "Import Tracking" section | ImportSpec as part of module-level Binding | ImportSpec lives on ReaderEnv (pipeline level) only | ImportSpec tracks how a name entered scope during renaming. It has no meaning in the module result. |

### What was preserved

- Module Identity (Package + Name + Version) — unchanged
- Three Kinds of Names (SurfaceName, ResolvedName, InternalName) — unchanged
- ModuleCache with MVar pattern — unchanged
- ModuleEntry structure (values + data_cons only) — already correct, aligned with MODULE_COMPONENTS_REFERENCE.md
- Loading protocol — unchanged
- Name resolution algorithm (two-stage) — preserved, just uses separate envs
- Shadowing by list ordering — unchanged
