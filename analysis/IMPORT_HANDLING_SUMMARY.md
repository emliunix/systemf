# GHC Import Handling & Name Resolution - Complete Summary

## 1. Import Processing Pipeline

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

## 2. Key Data Structures

### OccName - "Occurrence Name" (string + namespace)
```haskell
data OccName = OccName
    { occNameSpace :: NameSpace   -- VarName, DataName, TvName, TcClsName
    , occNameFS    :: FastString  -- "map", "Just", "Maybe"
    }
```

### Name - Uniquely identifies an entity
```haskell
data Name = Name
    { n_sort :: NameSort     -- External Module | Internal | ...
    , n_occ  :: OccName      -- The occurrence name
    , n_uniq :: !Unique      -- Globally unique (64-bit)
    , n_loc  :: !SrcSpan     -- Definition site
    }
```

### GlobalRdrEnv - Top-level naming environment
```haskell
type GlobalRdrEnv = OccEnv [GlobalRdrElt]
-- Maps: OccName → [GlobalRdrElt] (list handles name clashes!)

data GlobalRdrElt = GRE
    { gre_name :: !Name              -- The actual Name (WITH Unique)
    , gre_lcl  :: !Bool              -- Locally defined?
    , gre_imp  :: !(Bag ImportSpec)  -- How imported (if not local)
    , gre_info :: GREInfo            -- Extra renamer info
    }
```

## 3. Name Lookup Flow

```
Source: "Just"
    ↓
RdrName: Unqual (OccName "Just")
    ↓
lookupOccRn
    ├─ lookupLocalRdrEnv → Maybe Name (local vars)
    └─ lookupGlobalOccRn_maybe
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
            └── 2+ → "Ambiguous occurrence" error
```

## 4. NameCache - Session-Global Unique Management

**Location:** `HscEnv.hsc_NC :: NameCache` - shared across all modules in compilation session

**Purpose:** Ensures same external Name gets same Unique within session

**Lookup mechanism:**
```haskell
lookupNameCache :: NameCache -> Module -> OccName -> IO Name
lookupNameCache nc mod occ = 
  case lookupOrigNameCache cache mod occ of
    Just name -> return name              -- Cache hit! Same Unique
    Nothing   -> do
      uniq <- takeUniqFromNameCache nc    -- Fresh Unique
      let name = mkExternalName uniq mod occ noSrcSpan
      return name
```

**Who uses it:**
- `loadSrcInterface` - loading .hi files
- `readIface` - reading interfaces
- `fromHieName` - HIE file reading
- `thNameToGhcNameIO` - Template Haskell

## 5. Unique Allocation Strategy

**External Names** (imported/exported):
- From NameCache: `takeUniqFromNameCache`
- Same `(Module, OccName)` → same Unique within GHC invocation
- Cached in `OrigNameCache: Module → OccEnv Name`

**Internal Names** (local definitions):
- Fresh supply per compilation: `mkSplitUniqSupply`
- Tagged by subsystem: `'X'` (local), `'t'` (prelude), etc.

**Structure:**
```haskell
Unique = [Tag:8 bits][Number:56 bits]
```

## 6. Interface Files (.hi) - NO Uniques Stored!

**What .hi files store:**
- `IfaceDecl` declarations (types, signatures, metadata)
- Symbol table: `(UnitId, ModuleName, OccName)` - NOT Unique!

**On read:** Names reconstructed via NameCache lookup:
```haskell
getSymbolTable bh name_cache = do
  foldGet' sz bh cache0 $ \i (uid, mod_name, occ) cache ->
    case lookupOrigNameCache cache mod occ of
      Just name -> return (name, cache)           -- Use existing
      Nothing   -> do
        uniq <- takeUniqFromNameCache name_cache  -- Fresh Unique
        return (mkExternalName uniq mod occ noSrcSpan, 
                extendOrigNameCache cache mod occ name)
```

**Result:** Different sessions' interfaces get remapped to consistent Uniques!

## 7. Output Files Summary

| File | Contents | Names/Uniques |
|------|----------|---------------|
| **.hi** | Interface declarations | `(Module, OccName)` only, no Uniques |
| **.o/.dyn_o** | Native machine code | Machine code references (symbol table) |
| **.gbc** | Bytecode for interpreter | Names serialized with counter preservation |

## 8. Bytecode Name Serialization

**The Problem:** Local Names have different Uniques each session, but bytecode must preserve "same Name" vs "different Name" relationships.

**Solution - Counter System:**
```haskell
-- Writing: x#0, y#1, x#2 (OccName + counter)
-- Format: "occName#counter" (e.g., "x#0", "x#1")

-- Reading: Ensure same counter → same Name
case lookupOccEnv env occ of
  Just nm -> (env, nm)              -- Already seen
  Nothing -> 
    let nm' = mkInternalName freshUnique occ noSrcSpan
    in (extendOccEnv env occ nm', nm')
```

**Purpose:** Distinguish multiple locals with same OccName (shadowing, etc.)

## 9. Type Constructor & Data Constructor

**TyCon:**
```haskell
data TyCon = TyCon
    { tyConUnique  :: !Unique
    , tyConName    :: !Name
    , tyConBinders :: [TyConBinder]  -- Full binders with visibility
    , tyConTyVars  :: [TyVar]        -- Cached: binderVars tyConBinders
    }
```

**DataCon:**
```haskell
data DataCon = MkData
    { dcName       :: Name           -- Name of constructor
    , dcUnique     :: Unique
    , dcUnivTyVars :: [TyVar]        -- Universal vars (match parent TyCon)
    , dcExTyCoVars :: [TyCoVar]      -- Existential vars (GADTs)
    , dcOrigArgTys :: [Scaled Type]  -- Argument types
    , dcOrigResTy  :: Type           -- Result type
    , dcRepTyCon   :: TyCon          -- PARENT type constructor
    }
```

## 10. Key Invariants

1. **NameCache session-global:** Single `HscEnv` per GHC session, shared across all modules
2. **External names consistent:** Same `(Module, OccName)` → same Unique via cache
3. **Internal names module-local:** Different modules' internal names never collide
4. **Interface files store identity, not Uniques:** `(Module, OccName)` reconstructed via NameCache
5. **Bytecode preserves relationships:** Counter system ensures local Name identity across sessions
6. **No hash-based Uniques:** Fresh supply per session, tags partition spaces

## References

Key files:
- `compiler/GHC/Rename/Names.hs` - Import processing
- `compiler/GHC/Types/Name/Cache.hs` - NameCache implementation
- `compiler/GHC/Iface/Binary.hs` - Interface file serialization
- `compiler/GHC/ByteCode/Serialize.hs` - Bytecode name handling
- `compiler/GHC/Tc/Types.hs` - TcGblEnv with tcg_rdr_env, tcg_imports
