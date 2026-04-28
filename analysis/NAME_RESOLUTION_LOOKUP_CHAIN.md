# Name Resolution and Lookup Chain

**Validation Status:** ✅ Source code locations verified against GHC compiler (Mar 28, 2026)

## The Complete Pointer Chain

```
Name Resolution Chain:

User writes: A.foo
    ↓
Parser: RdrName (Qual "A" "foo")
    ↓
lookupGRE env (Qual "A" "foo")
    ↓
1. lookupOccEnv env "foo" 
   = [GRE1, GRE2, ...]  (all definitions named "foo")
    ↓
2. pickGREs (Qual "A" "foo") candidates
   = [GRE_A_foo]  (filter by qualification)
    ↓
GRE { gre_name = Name { n_uniq = Unique 123 } }
    ↓
lookupType hsc_env name
    ↓
HPT lookup by Module "A"
    ↓
HomeModInfo { hm_details = ModDetails { md_types = type_env } }
    ↓
lookupNameEnv type_env (Name "A.foo" Unique 123)
    ↓
Just (AnId fooId)  ← TyThing with actual type!
```

## Name Components

### Name Structure

**File:** `compiler/GHC/Types/Name.hs:126-145`

```haskell
data Name = Name
  { n_sort :: NameSort     -- External | Internal | System
  , n_occ  :: !OccName     -- The string (e.g., "foo")
  , n_uniq :: {-# UNPACK #-} !Unique  -- THE POINTER! Globally unique ID
  , n_loc  :: !SrcSpan     -- Definition site
  }
```

**Name equality is O(1) via Unique:**

**File:** `compiler/GHC/Types/Name.hs:596-632`

```haskell
cmpName :: Name -> Name -> Ordering
cmpName n1 n2 = n_uniq n1 `nonDetCmpUnique` n_uniq n2

instance Eq Name where
    a == b = case (a `compare` b) of { EQ -> True;  _ -> False }
```

### OccName vs Name

**OccName** = Surface name (string + namespace)
```haskell
data OccName = OccName
  { occNameSpace :: NameSpace   -- VarName | DataName | TcClsName | TvName
  , occNameFS    :: FastString  -- "foo", "Maybe", etc.
  }
```

**Key difference:**
- OccName = "foo" (just the string, may have collisions)
- Name = Module + "foo" + Unique (globally unique)

## GlobalRdrEnv Structure

### Type Definition

**File:** `compiler/GHC/Types/Name/Reader.hs:556-558`

```haskell
type GlobalRdrEnv = GlobalRdrEnvX GREInfo
type GlobalRdrEnvX info = OccEnv [GlobalRdrEltX info]
-- Maps: OccName → [GlobalRdrElt]  (list for collision handling!)
```

### GlobalRdrElt Contents

**File:** `compiler/GHC/Types/Name/Reader.hs:577-591`

```haskell
data GlobalRdrEltX info = GRE
  { gre_name :: !Name              -- The actual Name (with Unique)
  , gre_par  :: !Parent            -- Parent declaration (for record fields)
  , gre_lcl  :: !Bool              -- Locally defined?
  , gre_imp  :: !(Bag ImportSpec)  -- How imported (qualified? as what?)
  , gre_info :: info               -- Extra renamer info
  }
```

### ImportSpec - Tracking Qualification

**File:** `compiler/GHC/Types/Name/Reader.hs:1980-2010`

```haskell
data ImportSpec = ImpSpec 
  { is_decl :: ImpDeclSpec   -- Import declaration info
  , is_item :: ImpItemSpec   -- Specific item or all
  }

data ImpDeclSpec = ImpDeclSpec
  { is_mod      :: !Module        -- From which module
  , is_as       :: !ModuleName    -- "AS" alias (e.g., "Map")
  , is_qual     :: !Bool          -- Qualified import?
  , is_dloc     :: !SrcSpan       -- Import declaration location
  , ...
  }

-- Check if available qualified:
qualSpecOK :: ModuleName -> ImportSpec -> Bool
qualSpecOK mod is = mod == is_as (is_decl is)

-- Check if available unqualified:
unQualSpecOK :: ImportSpec -> Bool
unQualSpecOK is = not (is_qual (is_decl is))
```

## Two-Stage Lookup

### Stage 1: By OccName

**File:** `compiler/GHC/Types/Name/Occurrence.hs:600-650`

```haskell
newtype OccEnv a = MkOccEnv (FastStringEnv (UniqFM NameSpace a))
-- Maps: String → (NameSpace → a)

lookupOccEnv :: OccEnv a -> OccName -> Maybe a
lookupOccEnv (MkOccEnv as) (OccName ns s)
  = do { m <- lookupFsEnv as s       -- Step 1: Lookup string "foo"
       ; lookupUFM m ns              -- Step 2: Lookup namespace VarName
       }
```

### Stage 2: Filter by Qualification

**File:** `compiler/GHC/Types/Name/Reader.hs:1576-1600`

```haskell
pickGREs :: RdrName -> [GlobalRdrEltX info] -> [GlobalRdrEltX info]
pickGREs (Unqual {})  gres = mapMaybe pickUnqualGRE     gres
pickGREs (Qual mod _) gres = mapMaybe (pickQualGRE mod) gres

pickQualGRE :: ModuleName -> GlobalRdrEltX info -> Maybe (GlobalRdrEltX info)
pickQualGRE mod gre@(GRE { gre_lcl = lcl, gre_imp = iss })
  | not lcl', null iss' = Nothing
  | otherwise           = Just (gre { gre_lcl = lcl', gre_imp = iss' })
  where
    iss' = filterBag (qualSpecOK mod) iss  -- ← Filter by "as" name!
    lcl' = lcl && name_is_from mod
```

## TypeEnv Structure

### Definition

**File:** `compiler/GHC/Types/TypeEnv.hs:39`

```haskell
type TypeEnv = NameEnv TyThing
```

**File:** `compiler/GHC/Types/Name/Env.hs:101`

```haskell
type NameEnv a = UniqFM Name a       -- Domain is Name (keyed by Unique!)
```

**File:** `compiler/GHC/Types/Unique/FM.hs:110`

```haskell
newtype UniqFM key ele = UFM (M.Word64Map ele)
-- Maps: Word64 (Unique) → element
```

### Lookup by Name/Unique

**File:** `compiler/GHC/Types/Unique/FM.hs:469-470`

```haskell
lookupUFM :: Uniquable key => UniqFM key elt -> key -> Maybe elt
lookupUFM (UFM m) k = M.lookup (getKey $ getUnique k) m
-- O(1) hash lookup by Unique!
```

## The Pointer Chain Explained

### 1. GlobalRdrEnv: OccName → [GRE]

**Purpose:** Name resolution (find all candidates)

```haskell
GlobalRdrEnv: "foo" → [ GRE { name = A.foo, imp = [unqualified] }
                      , GRE { name = B.foo, imp = [qualified as "B"] }
                      ]
```

### 2. GRE: Contains Name with Unique

**Purpose:** Global identifier with import provenance

```haskell
GRE { gre_name = Name { n_occ = "foo"
                      , n_uniq = Unique 123456  -- ← THE POINTER!
                      , n_sort = External Module "A"
                      }
    , gre_imp = [ImpSpec { is_as = "A", is_qual = False }]
    }
```

### 3. TypeEnv: Unique → TyThing

**Purpose:** Actual type information

```haskell
TypeEnv: Unique 123456 → AnId id  -- The actual Id with type!
```

## NameCache: Consistent Uniques

**File:** `compiler/GHC/Types/Name/Cache.hs:116-135`

```haskell
data NameCache = NameCache
  { nsUniqChar :: {-# UNPACK #-} !Char
  , nsNames    :: {-# UNPACK #-} !(MVar OrigNameCache)
  }

type OrigNameCache = ModuleEnv (OccEnv Name)
-- Maps: (Module, OccName) → Name

lookupOrigNameCache :: OrigNameCache -> Module -> OccName -> Maybe Name
-- Returns same Name (with same Unique) for repeated lookups!
```

**Invariant:** Same `(Module, OccName)` → same Unique within GHC session

## Complete Lookup Examples

### Example 1: Unqualified Lookup

```haskell
-- Environment:
-- import Data.Maybe (fromMaybe)
-- import Data.List (sort)

lookupGRE env (Unqual "fromMaybe")
  ↓
lookupOccEnv env "fromMaybe"
  = [GRE { name = Data.Maybe.fromMaybe, imp = [unqualified] }]
  ↓
pickGREs (Unqual "fromMaybe") [...]
  = [GRE { ... }]  -- Available unqualified!
  ↓
lookupType (Name "Data.Maybe.fromMaybe" Unique 123)
  ↓
HPT["Data.Maybe"].hm_details.md_types[Unique 123]
  = Just (AnId fromMaybeId)
```

### Example 2: Qualified Lookup

```haskell
-- Environment:
-- import qualified Data.Maybe as M

lookupGRE env (Qual "M" "fromMaybe")
  ↓
lookupOccEnv env "fromMaybe"
  = [GRE { name = Data.Maybe.fromMaybe, imp = [qualified as "M"] }]
  ↓
pickGREs (Qual "M" "fromMaybe") [...]
  = filter (qualSpecOK "M") [...]
  = [GRE { ... }]  -- Only those with is_as = "M"
  ↓
lookupType ...
  = Just (AnId fromMaybeId)
```

### Example 3: Collision Detection

```haskell
-- Environment:
-- import A (foo)
-- import B (foo)

lookupGRE env (Unqual "foo")
  ↓
lookupOccEnv env "foo"
  = [ GRE { name = A.foo, imp = ... }
    , GRE { name = B.foo, imp = ... }
    ]
  ↓
pickGREs (Unqual "foo") [GRE_A, GRE_B]
  = [GRE_A, GRE_B]  -- Both available unqualified!
  ↓
ERROR: Ambiguous occurrence 'foo'
      Could refer to either A.foo or B.foo
```

## Source Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| Name | GHC/Types/Name.hs | 126-145 (definition), 596-632 (equality) |
| OccName | GHC/Types/Name/Occurrence.hs | 600-650 (OccEnv) |
| GlobalRdrEnv | GHC/Types/Name/Reader.hs | 556-591 (definition), 1576-1600 (pickGREs) |
| ImportSpec | GHC/Types/Name/Reader.hs | 2162-2170 (ImpDeclSpec) |
| TypeEnv | GHC/Types/TypeEnv.hs | 39 (definition) |
| NameEnv | GHC/Types/Name/Env.hs | 101 (definition), 126-142 (lookup) |
| UniqFM | GHC/Types/Unique/FM.hs | 110 (definition), 469-470 (lookup) |
| NameCache | GHC/Types/Name/Cache.hs | 116-135 (definition) |

## Key Invariants

1. **GlobalRdrEnv keyed by OccName** - Multiple Names can share same OccName
2. **TypeEnv keyed by Name/Unique** - Unique is the actual pointer
3. **Name equality is O(1)** - Just compare Uniques
4. **NameCache provides consistency** - Same (Module, OccName) → same Unique
5. **Two-stage lookup** - OccName → filter by qualification → Name → TyThing
