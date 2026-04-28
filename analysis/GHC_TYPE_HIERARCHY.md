# GHC Type Hierarchy: Var, TcTyVar, TyVar, MetaTv, SkolemTv

**Status:** Validated
**Last Updated:** 2024
**Source:** GHC Compiler Source Code

## Overview

This document describes the relationships between the various type variable representations in GHC's type system.

## Type Hierarchy Diagram

```
Var (in GHC.Types.Var)
├── TyVar                              -- Post-typecheck / Core IR
│   └── Fields: varName, realUnique, varType (Kind)
│
├── TcTyVar                            -- During type checking ONLY  
│   └── Fields: varName, realUnique, varType (Kind), tc_tv_details :: TcTyVarDetails
│       │
│       └── TcTyVarDetails (in GHC.Tc.Utils.TcType)
│           ├── SkolemTv               -- Immutable skolem (rigid)
│           │   └── Fields: SkolemInfo, TcLevel, Bool (overlappable)
│           │
│           ├── MetaTv                 -- Mutable unification variable
│           │   └── Fields: 
│           │       ├── mtv_info :: MetaInfo
│           │       │   ├── TauTv          -- Ordinary unification var
│           │       │   ├── TyVarTv        -- Only unifies with tyvars
│           │       │   ├── RuntimeUnkTv   -- GHCi debugger
│           │       │   ├── CycleBreakerTv -- Occurs-check fix
│           │       │   └── ConcreteTv     -- Only concrete types
│           │       ├── mtv_ref :: IORef MetaDetails
│           │       └── mtv_tclvl :: TcLevel
│           │
│           └── RuntimeUnk             -- GHCi interactive
│
└── Id                                 -- Term-level identifiers
    └── Fields: varName, varType (Type), varMult, idScope, id_details, id_info
```

## Key Distinctions

| Aspect | TyVar | TcTyVar + SkolemTv | TcTyVar + MetaTv |
|--------|-------|-------------------|------------------|
| **When used** | Post-typecheck | Type checking (rigid) | Type checking (unification) |
| **Mutable?** | No | No | Yes (has IORef) |
| **Can unify?** | N/A | No (rigid) | Yes |
| **Level tracking** | No | Yes (TcLevel) | Yes (TcLevel) |
| **Provenance** | No | Yes (SkolemInfo) | No |

## Evidence

### Var Data Type

**Source:** `compiler/GHC/Types/Var.hs:256-274`

```haskell
data Var
  = TyVar {  -- Type and kind variables (post-typecheck)
        varName    :: !Name,
        realUnique :: {-# UNPACK #-} !Unique,
        varType    :: Kind           -- ^ The type or kind
 }
  | TcTyVar {                           -- Used only during type inference
        varName        :: !Name,
        realUnique     :: {-# UNPACK #-} !Unique,
        varType        :: Kind,
        tc_tv_details  :: TcTyVarDetails  -- <-- Contains SkolemTv or MetaTv
  }
  | Id { ... }  -- Term-level identifiers
```

### TcTyVarDetails Data Type

**Source:** `compiler/GHC/Tc/Utils/TcType.hs:634-651`

```haskell
data TcTyVarDetails
  = SkolemTv      -- A skolem (immutable, rigid)
       SkolemInfo -- Provenance info for error messages
       TcLevel    -- Level of the implication that binds it
       Bool       -- Overlappable?

  | RuntimeUnk    -- GHCi interactive context

  | MetaTv { mtv_info  :: MetaInfo      -- What kind of meta-var
           , mtv_ref   :: IORef MetaDetails  -- Mutable!
           , mtv_tclvl :: TcLevel }
```

### MetaInfo Data Type

**Source:** `compiler/GHC/Tc/Utils/TcType.hs:672-694`

```haskell
data MetaInfo
   = TauTv         -- ^ Ordinary unification variable
   | TyVarTv       -- ^ Only unifies with type variables
   | RuntimeUnkTv  -- ^ GHCi debugger
   | CycleBreakerTv -- ^ Occurs-check problem fix
   | ConcreteTv ConcreteTvOrigin  -- ^ Only concrete types
```

## Important Distinctions

**SkolemTv and MetaTv are NOT constructors of Var!** They are constructors of `TcTyVarDetails`, which is a field inside `TcTyVar`. 

A `Var` can be:
1. `TyVar` - plain type variable for Core IR (post-typecheck)
2. `TcTyVar` - type checking variable with `tc_tv_details` that is either:
   - `SkolemTv` - immutable, rigid (for checking polymorphic types)
   - `MetaTv` - mutable unification variable

## Why SkolemTv for Quantified Variables?

During type checking, quantified type variables are represented as `TcTyVar` with `SkolemTv` details because:

1. **The type checker works exclusively with TcTyVars** - TyVar is only for Core IR
2. **SkolemTv carries provenance** (SkolemInfo) needed for error messages
3. **SkolemTv tracks TcLevel** for scoping/escape checking
4. **Conversion to TyVar happens only at the end** during zonking

**Evidence:** `compiler/GHC/Tc/Utils/TcMType.hs:1906-1926`

```haskell
skolemiseUnboundMetaTyVar skol_info tv
  = ...
    do  { ...
        ; let details    = SkolemTv skol_info (pushTcLevel tc_lvl) False
              final_tv   = mkTcTyVar final_name kind details
        ; traceZonk "Skolemising" (ppr tv <+> text ":=" <+> ppr final_tv)
        ; writeMetaTyVar tv (mkTyVarTy final_tv)
        ; return final_tv }
```

## Related Topics

- SKOLEMISE_TRACE.md - Detailed trace of skolemisation in GHC
- TYPE_INFERENCE.md - General type inference mechanisms
- TcLevel invariants in GHC.Tc.Utils.TcType
