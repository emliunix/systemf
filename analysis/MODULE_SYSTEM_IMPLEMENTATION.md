# Module System Implementation Analysis

## Overview

This document consolidates findings about GHC's module system implementation, covering name resolution, environment structures, and the relationship between type constructors and data constructors.

### Validation Status

**Validated against GHC source:** This document was cross-checked against the actual GHC source code. Key findings:

| Component | Status | Notes |
|-----------|--------|-------|
| TyCon-DataCon mutual reference | **VERIFIED** | All line numbers and field names confirmed |
| GlobalRdrEnv/GRE | **UPDATED** | Uses parameterized `GlobalRdrEnvX`, includes `gre_par` field |
| NameCache | **UPDATED** | Refactored to use `NameSupply` with MVar |
| TyThing constructors | **CORRECTED** | Order: `AnId`, `AConLike`, `ATyCon`, `ACoAxiom` |
| Import pipeline | **VERIFIED** | Flow and key functions confirmed |
| Interactive context | **VERIFIED** | Shadowing behavior confirmed |

**Source locations** cite `compiler/` paths (e.g., `compiler/GHC/Core/TyCon.hs`).

---

## 1. GlobalRdrEnv - Name Resolution Environment

### 1.1 Structure

**File:** `compiler/GHC/Types/Name/Reader.hs`

```haskell
-- Uses parameterized type for extensibility
type GlobalRdrEnv = GlobalRdrEnvX GREInfo
type GlobalRdrEnvX info = OccEnv [GlobalRdrEltX info]
-- Maps: OccName → [GlobalRdrElt] (list handles name clashes!)

data GlobalRdrEltX info = GRE
    { gre_name :: !Name              -- The actual Name (WITH Unique)
    , gre_par  :: !Parent            -- Parent declaration (for record fields)
    , gre_lcl  :: !Bool              -- Locally defined?
    , gre_imp  :: !(Bag ImportSpec)  -- How imported (if not local)
    , gre_info :: info               -- Extra renamer info (GREInfo for normal use)
    }

type GlobalRdrElt = GlobalRdrEltX GREInfo
```

**Key insight:** Stores ALL candidates for a name, not just one. This enables both collision detection and shadowing behavior.

### 1.2 Merge Semantics

**Batch Compilation** (`plusGlobalRdrEnv`):
```haskell
-- File: compiler/GHC/Types/Name/Reader.hs
-- Implementation: OccEnv.unionWith (++) env1 env2
-- Result: Appends candidates, no collision check at merge time
```

**GHCi Interactive** (`icExtendGblRdrEnv`):
```haskell
-- File: compiler/GHC/Runtime/Context.hs
-- "Add TyThings to the GlobalRdrEnv, earlier ones in the list shadowing 
--  later ones, and shadowing existing entries in the GlobalRdrEnv."
-- Implementation: Prepends new definitions to front of list
```

### 1.3 Lookup Behavior

**File:** `compiler/GHC/Rename/Names.hs` (lookupOccRn)

```haskell
-- 1. Check local environment
lookupLocalRdrEnv → Maybe Name

-- 2. Check global environment  
lookupGlobalOccRn_maybe
    ↓
lookupGRE env (LookupRdrName rdr which_gres)
    ↓
lookupOccEnv env (rdrNameOcc rdr) → [GlobalRdrElt]
    ↓
pickGREs (filter by qualification)
    ↓
match count?
    ├── 0 → "Not in scope" error
    ├── 1 → return GRE (with Name + Unique)
    └── 2+ → "Ambiguous occurrence" error (batch mode)
           → return head (shadowing, GHCi mode)
```

---

## 2. Name Data Types

### 2.1 OccName (Surface Names)

**File:** `compiler/GHC/Types/Name/Occurrence.hs`

```haskell
data OccName = OccName
    { occNameSpace :: NameSpace   -- VarName, DataName, TvName, TcClsName
    , occNameFS    :: FastString  -- "map", "Just", "Maybe"
    }
```

### 2.2 Name (Unique Identifiers)

**File:** `compiler/GHC/Types/Name.hs`

```haskell
data Name = Name
    { n_sort :: NameSort     -- External Module | Internal | ...
    , n_occ  :: OccName      -- The occurrence name
    , n_uniq :: !Unique      -- Globally unique (64-bit)
    , n_loc  :: !SrcSpan     -- Definition site
    }
```

### 2.3 RdrName (Parsed Names)

**File:** `compiler/GHC/Types/Name/Reader.hs`

```haskell
data RdrName
    = Unqual OccName         -- x, used locally
    | Qual ModuleName OccName -- M.x, imported qualified
    | Orig Module OccName     -- Original name in compiled code
    | Exact Name              -- Exact name with Unique
```

---

## 3. Import Processing Pipeline

### 3.1 Flow

**File:** `compiler/GHC/Rename/Names.hs` (rnImports)

```
Source imports
    ↓
Parser: [ImportDecl GhcPs]
    ↓
rnImports (GHC.Rename.Names)
    ├─ Partition source vs ordinary imports
    ├─ rnImportDecl (per import)
    │   ├─ loadSrcInterface (load .hi file)
    │   ├─ filterImports (resolve import list)
    │   └─ calculateAvails (compute ImportAvails)
    ↓
tcRnImports (GHC.Tc.Module)
    ├─ tcg_rdr_env `plusGlobalRdrEnv` rdr_env
    └─ tcg_imports `plusImportAvails` imports
```

### 3.2 Interface Files

**File:** `compiler/GHC/Iface/Binary.hs`

```haskell
-- What .hi files store:
- IfaceDecl declarations (types, signatures, metadata)
- Symbol table: (UnitId, ModuleName, OccName) - NOT Unique!

-- On read, Names reconstructed via NameCache lookup:
getSymbolTable bh name_cache = do
  foldGet' sz bh cache0 $ \i (uid, mod_name, occ) cache ->
    case lookupOrigNameCache cache mod occ of
      Just name -> return (name, cache)           -- Use existing
      Nothing   -> do
        uniq <- takeUniqFromNameCache name_cache  -- Fresh Unique
        return (mkExternalName uniq mod occ noSrcSpan, ...)
```

**Key:** Interface files store `(Module, OccName)`, not Uniques. Uniques assigned on load via NameCache.

---

## 4. Type Check Environment

### 4.1 TcGblEnv Structure

**File:** `compiler/GHC/Tc/Types.hs`

```haskell
data TcGblEnv = TcGblEnv {
    tcg_type_env     :: TypeEnv,      -- NameEnv TyThing (all type-checked entities)
    tcg_rdr_env      :: GlobalRdrEnv, -- Renamer env (name resolution)
    tcg_imports      :: ImportAvails, -- What was imported
    tcg_tythings     :: [TyThing],    -- Top-level definitions (this module)
    tcg_binds        :: LHsBinds GhcTc, -- Type-checked bindings
    tcg_complete_match_env :: CompleteMatchMap, -- Pattern exhaustiveness
    tcg_type_env_var :: KnotVars (IORef TypeEnv), -- For recursive definitions
    ...
}

type TypeEnv = NameEnv TyThing
```

### 4.2 Environment Lookup Chain

**File:** `compiler/GHC/Tc/Utils/Env.hs` (tcLookup)

```haskell
-- Lookup chain when encountering variable reference 'x':
1. Local Environment (tcl_env)
   └── lookupNameEnv local_env name

2. Module Global (tcg_type_env)
   └── lookupNameEnv (tcg_type_env env) name

3. Import lookup (tcLookupGlobal)
   └── lookupType hsc_env name
       └── Check ExternalPackageTable
       └── Load interface if needed

-- No merged environment: hierarchical search
```

---

## 5. TyThing - Type-Checked Entities

### 5.1 Definition

**File:** `compiler/GHC/Types/TyThing.hs`

```haskell
data TyThing
  = AnId     Id          -- Value identifiers (functions, variables)
  | AConLike ConLike     -- Data constructors or pattern synonyms
  | ATyCon   TyCon       -- Type constructors
  | ACoAxiom CoAxiom     -- Type family instances

data ConLike
  = RealDataCon DataCon  -- Real data constructor
  | PatSynCon PatSyn     -- Pattern synonym
```

**Key:** "Ty" means "type-checked", not "type". Data constructors ARE functions with types.

### 5.2 Storage Example

```haskell
data Maybe a = Nothing | Just a

-- In tcg_type_env:
"Maybe" → ATyCon maybeTyCon          -- Type constructor
"Just"  → AConLike (RealDataCon justDataCon)   -- Data constructor
"Nothing" → AConLike (RealDataCon nothingDataCon)
```

---

## 6. TyCon-DataCon Mutual Reference

### 6.1 Forward Reference (TyCon → DataCon)

**File:** `compiler/GHC/Core/TyCon.hs` (Lines 817-858)

```haskell
data TyConDetails = 
    AlgTyCon {
      ...
      algTcRhs    :: AlgTyConRhs, -- Contains information about the
                                  -- data constructors of the algebraic type
      ...
    }
```

**File:** `compiler/GHC/Core/TyCon.hs` (Lines 1050-1087)

```haskell
data AlgTyConRhs = 
  | DataTyCon {
        data_cons :: [DataCon],  -- The data type constructors
        data_cons_size :: Int,
        is_enum :: Bool,
        ...
    }
  | NewTyCon {
        data_con :: DataCon,     -- The unique constructor for newtype
        ...
    }
```

### 6.2 Back Reference (DataCon → TyCon)

**File:** `compiler/GHC/Core/DataCon.hs` (Lines 553-554)

```haskell
data DataCon = MkData {
    dcName       :: Name,           -- Name of constructor
    dcUnique     :: Unique,
    dcUnivTyVars :: [TyVar],        -- Universal vars (match parent TyCon)
    dcExTyCoVars :: [TyCoVar],      -- Existential vars (GADTs)
    dcOrigArgTys :: [Scaled Type],  -- Argument types
    dcOrigResTy  :: Type,           -- Result type
    dcRepTyCon   :: TyCon,          -- PARENT type constructor
    ...
}
```

**File:** `compiler/GHC/Core/DataCon.hs` (Lines 1275-1276)

```haskell
-- | The type constructor that we are building via this data constructor
dataConTyCon :: DataCon -> TyCon
dataConTyCon = dcRepTyCon
```

### 6.3 Reference Diagram

```
TyCon (AlgTyCon)
    └── algTcRhs :: AlgTyConRhs
            └── DataTyCon
                    └── data_cons :: [DataCon]
                                    ↓
DataCon (MkData) ←────────────────┘
    └── dcRepTyCon :: TyCon
```

### 6.4 Example: List Type

```haskell
data List a = Nil | Cons a (List a)

-- TyCon stores its constructors
listTyCon = TyCon {
    tyConDetails = AlgTyCon {
        algTcRhs = DataTyCon {
            data_cons = [nilDataCon, consDataCon]
        }
    }
}

-- DataCon stores reference to parent
consDataCon = MkData {
    dcRepTyCon = listTyCon,      -- Points back to List
    dcOrigArgTys = [a, List a],  -- Constructor args
    dcOrigResTy = List a         -- Returns List a
}
```

---

## 7. NameCache - Unique Management

### 7.1 Structure

**File:** `compiler/GHC/Types/Name/Cache.hs` (Lines 113-119)

```haskell
data NameCache = NameCache {
    nsUniqChar :: !Char,              -- Prefix character for unique generation
    nsNames    :: !(MVar OrigNameCache)  -- Cache wrapped in MVar for thread safety
}

type OrigNameCache = ModuleEnv (OccEnv Name)
-- Module → (OccName → Name)
```

### 7.2 Lookup

**File:** `compiler/GHC/Types/Name/Cache.hs` (Lines 127-145)

```haskell
-- Pure lookup in the cache (Maybe Name return)
lookupOrigNameCache :: OrigNameCache -> Module -> OccName -> Maybe Name

-- During interface loading, names are looked up via:
-- 1. Check cache for existing Name (same Unique)
-- 2. If not found, allocate fresh Unique via NameSupply
-- 3. Store in cache for future lookups

-- Key invariant: Same (Module, OccName) → same Unique within GHC session
```

**Note:** The NameCache structure was refactored to use `NameSupply` for unique generation and MVar for thread-safe access to the name cache.

---

## 8. Interactive Context (GHCi)

### 8.1 Structure

**File:** `compiler/GHC/Runtime/Context.hs`

```haskell
data InteractiveContext = InteractiveContext {
    ic_mod_index :: Int,              -- Incremented per statement
    ic_tythings  :: [TyThing],        -- User definitions, reverse order
    ic_gre_cache :: IcGlobalRdrEnv,   -- Cached GlobalRdrEnv
    ic_imports   :: [InteractiveImport],
    ...
}

-- Each statement gets a new module name: interactive:Ghci9.T
-- ic_tythings in reverse order: most recent definition first
```

### 8.2 Shadowing Behavior

**File:** `compiler/GHC/Runtime/Context.hs` (icExtendGblRdrEnv)

```haskell
-- "Add TyThings to the GlobalRdrEnv, earlier ones in the list shadowing 
--  later ones, and shadowing existing entries in the GlobalRdrEnv."

-- Implementation: Prepend new definitions
newEnv = foldr addOne existingEnv newTyThings
  where
    addOne thing env = 
        let gre = makeGRE thing
        in extendOccEnv (occName thing) (gre : lookup env) env

-- Lookup: take first match (newest/shadowing)
lookupGRE env name = case candidates of
    (g:_) -> Just g   -- First match = shadow
    []    -> Nothing
```

**Contrast with batch mode:**
- Batch: Append imports, error on 2+ candidates
- GHCi: Prepend definitions, take first (shadowing)

---

## 9. Collision Detection Comparison

### 9.1 Batch Mode (Module Compilation)

**Policy:** Error on ambiguous names

**When detected:** At use site (lookup time)

**Example:**
```haskell
import A (foo)  -- foo added to GlobalRdrEnv
import B (foo)  -- foo appended to same list

main = foo      -- ERROR: Ambiguous occurrence 'foo'
                -- Could refer to either A.foo or B.foo
```

### 9.2 GHCi Mode (REPL)

**Policy:** Shadowing (last definition wins)

**When detected:** Never an error, implicit resolution

**Example:**
```haskell
ghci> let foo = 1
ghci> let foo = 2      -- Shadows previous foo
ghci> foo              -- Returns 2
ghci> Ghci1.foo        -- Returns 1 (qualified access to shadowed)
```

### 9.3 Design Trade-offs

| Aspect | Batch Mode | GHCi Mode |
|--------|-----------|-----------|
| Merge order | Append | Prepend |
| Collision check | At use (error) | Never (shadow) |
| Qualified access | Required to resolve | Available for old definitions |
| Safety | High | Convenience |
| Use case | Production code | Interactive experimentation |

---

## 10. Key Invariants

1. **NameCache session-global:** Single `HscEnv` per GHC session, shared across all modules
2. **External names consistent:** Same `(Module, OccName)` → same Unique via cache
3. **Interface files store identity:** `(Module, OccName)` reconstructed via NameCache
4. **GlobalRdrEnv stores ALL candidates:** Lists enable both collision detection and shadowing
5. **DataCon-TyCon mutual reference:** Bidirectional navigation via `data_cons` and `dcRepTyCon`
6. **TyThing uniformity:** Single container for all type-checked entities
7. **No eager collision checking:** All name validation happens at use time

---

## 11. Source Files Index

| Concept | Primary File | Key Functions/Types |
|---------|-------------|---------------------|
| GlobalRdrEnv | `GHC/Types/Name/Reader.hs` | GlobalRdrEnv, GRE, plusGlobalRdrEnv |
| Name | `GHC/Types/Name.hs` | Name, NameSort |
| OccName | `GHC/Types/Name/Occurrence.hs` | OccName, NameSpace |
| Import processing | `GHC/Rename/Names.hs` | rnImports, rnImportDecl |
| Type environment | `GHC/Tc/Types.hs` | TcGblEnv, tcg_type_env |
| Environment lookup | `GHC/Tc/Utils/Env.hs` | tcLookup, lookupGRE |
| TyThing | `GHC/Types/TyThing.hs` | TyThing, ConLike |
| TyCon | `GHC/Core/TyCon.hs` | TyCon, AlgTyConRhs, data_cons |
| DataCon | `GHC/Core/DataCon.hs` | DataCon, dcRepTyCon, dataConTyCon |
| NameCache | `GHC/Types/Name/Cache.hs` | NameCache, lookupNameCache |
| Interactive context | `GHC/Runtime/Context.hs` | InteractiveContext, icExtendGblRdrEnv |
| Interface files | `GHC/Iface/Binary.hs` | getSymbolTable |

---

## References

- `IMPORT_HANDLING_SUMMARY.md` - Import processing details
- `MODULE_TYPE_INFERENCE_QA.md` - Type inference Q&A
- `TYPE_INFERENCE.md` - Type inference system
- `TYCON_DATACON_MUTUAL_REFERENCE.md` - Mutual reference deep dive
