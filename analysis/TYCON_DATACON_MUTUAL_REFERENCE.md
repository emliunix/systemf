# TyCon-DataCon Mutual Reference Pattern

## Overview

GHC uses a bidirectional reference pattern between `TyCon` (type constructors) and `DataCon` (data constructors). This allows navigation from type to constructors and from constructors back to their parent type.

## Source Code References

### 1. TyCon → DataCon (via algTcRhs.data_cons)

**File:** `compiler/GHC/Core/TyCon.hs` (Lines 817-858)

```haskell
data TyConDetails = 
    AlgTyCon {
      ...
      algTcRhs    :: AlgTyConRhs, -- ^ Contains information about the
                                  -- data constructors of the algebraic type
      ...
    }
```

**File:** `compiler/GHC/Core/TyCon.hs` (Lines 1050-1087)

```haskell
data AlgTyConRhs = 
    ...
  | DataTyCon {
        data_cons :: [DataCon],  -- ^ The data type constructors
        data_cons_size :: Int,
        is_enum :: Bool,
        ...
    }
```

### 2. DataCon → TyCon (via dcRepTyCon)

**File:** `compiler/GHC/Core/DataCon.hs` (Lines 553-554)

```haskell
data DataCon = MkData {
    ...
    -- Result type of constructor is T t1..tn
    dcRepTyCon  :: TyCon,  -- Result tycon, T
    ...
}
```

### 3. Accessor Function

**File:** `compiler/GHC/Core/DataCon.hs` (Lines 1275-1276)

```haskell
-- | The type constructor that we are building via this data constructor
dataConTyCon :: DataCon -> TyCon
dataConTyCon = dcRepTyCon
```

## Reference Diagram

```
TyCon (AlgTyCon)
    └── algTcRhs :: AlgTyConRhs
            └── DataTyCon
                    └── data_cons :: [DataCon]
                                    ↓
DataCon (MkData) ←────────────────┘
    └── dcRepTyCon :: TyCon
```

## Example: data List a = Nil | Cons a (List a)

```haskell
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

## Key Functions

- `tyConDataCons :: TyCon -> [DataCon]` - Get constructors from TyCon
- `dataConTyCon :: DataCon -> TyCon` - Get parent TyCon from DataCon
- `visibleDataCons :: AlgTyConRhs -> [DataCon]` - Extract visible constructors

## Multiple Representations

Different phases use different TyCon representations:

| Phase | TyCon Type | Notes |
|-------|-----------|-------|
| Type-checking | `TcTyCon` | Placeholder with scoped tyvars |
| Post type-check | `AlgTyCon` | Full definition with DataCons |
| Core | `AlgTyCon` | Same as post-TC |
| Interface files | Serialized | Reconstructed via `mkTyConTagMap` |

## Invariants

1. **Tag ordering**: `data_cons` kept in order of increasing DataCon tag
2. **Uniqueness**: Each `DataCon` appears in exactly one `TyCon`s `data_cons`
3. **Back reference**: Every `DataCon` has valid `dcRepTyCon` pointing to parent

## Related Analysis

See also:
- `IMPORT_HANDLING_SUMMARY.md` - How DataCons are populated into environments
- `MODULE_TYPE_INFERENCE_QA.md` - Lookup chains for constructors
- `TYPE_INFERENCE.md` - How constructors are type-checked
