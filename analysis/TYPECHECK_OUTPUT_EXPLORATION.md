# Typechecking Output

**Status:** Validated
**Last Updated:** 2024-03-28
**Central Question:** What does typechecking produce besides TyThings?

## Summary

Typechecking produces **far more than just TyThings**. The complete picture includes:

1. **TyThings** (TypeEnv): Ids, TyCons, Classes, DataCons, Pattern Synonyms
2. **Type class instances** (ClsInst): Dictionary functions and their instances
3. **Family instances** (FamInst): Type/data family instances
4. **Rewrite rules** (CoreRule): Optimizations like fusion rules
5. **Annotations** (Annotation): Pragma annotations
6. **Default declarations** (DefaultEnv): `default` statements
7. **Complete matches** (CompleteMatches): `COMPLETE` pragmas
8. **Value bindings** (LHsBinds): Typechecked code with evidence bindings
9. **Foreign declarations**: FFI imports/exports
10. **Pattern synonyms**: Pattern synonym definitions

## Key Outputs Table

| Output Category | TcGblEnv Field | ModDetails Field | Description |
|----------------|----------------|------------------|-------------|
| **TyThings** | `tcg_type_env` | `md_types` | All TyCons, Classes, Ids, DataCons, PatSyns |
| **Type class instances** | `tcg_insts` | `md_insts` | Dictionary functions and instances |
| **Family instances** | `tcg_fam_insts` | `md_fam_insts` | Type/data family instances |
| **Rewrite rules** | `tcg_rules` | `md_rules` | Optimization rules (e.g., fusion) |
| **Annotations** | `tcg_anns` | `md_anns` | Pragma annotations |
| **Default declarations** | `tcg_default_exports` | `md_defaults` | Default type declarations |
| **Complete matches** | `tcg_complete_matches` | `md_complete_matches` | COMPLETE pragmas |
| **Value bindings** | `tcg_binds` | (in code gen) | Typechecked code |
| **Foreign declarations** | `tcg_fords` | (in code gen) | FFI imports/exports |
| **Pattern synonyms** | `tcg_patsyns` | (in type env) | Pattern synonym definitions |
| **Exports** | `tcg_exports` | `md_exports` | What's exported from module |

## TcGblEnv Structure

**File:** `compiler/GHC/Tc/Types.hs:466-694`

The `TcGblEnv` is the central structure that accumulates all typechecking outputs:

```haskell
data TcGblEnv = TcGblEnv {
    -- Type environment (TyThings)
    tcg_type_env :: TypeEnv,              -- ^ All TyCons, Classes, Ids
    
    -- Instances
    tcg_insts     :: [ClsInst],           -- ^ Type class instances
    tcg_fam_insts :: [FamInst],           -- ^ Family instances
    tcg_inst_env  :: !InstEnv,            -- ^ Instance environment
    tcg_fam_inst_env :: !FamInstEnv,      -- ^ Family instance environment
    
    -- Rules and pragmas  
    tcg_rules     :: [LRuleDecl GhcTc],   -- ^ Rewrite rules
    tcg_anns      :: [Annotation],        -- ^ Annotations
    tcg_complete_matches :: CompleteMatches, -- ^ COMPLETE pragmas
    
    -- Value-level outputs
    tcg_binds     :: LHsBinds GhcTc,      -- ^ Value bindings
    tcg_ev_binds  :: Bag EvBind,          -- ^ Evidence bindings
    tcg_patsyns   :: [PatSyn],            -- ^ Pattern synonyms
    tcg_fords     :: [LForeignDecl GhcTc], -- ^ Foreign declarations
    tcg_imp_specs :: [LTcSpecPrag],       -- ^ SPECIALISE prags
    
    -- Defaults and fixities
    tcg_default   :: DefaultEnv,          -- ^ Default declarations
    tcg_default_exports :: DefaultEnv,    -- ^ Exported defaults
    tcg_fix_env   :: FixityEnv,           -- ^ Fixity declarations
    
    -- Metadata
    tcg_exports   :: [AvailInfo],         -- ^ What's exported
    tcg_tcs       :: [TyCon],             -- ^ TyCons and Classes defined
    tcg_sigs      :: NameSet,             -- ^ Top-level names lacking signatures
    ...
}
```

### ModDetails - The Module Interface

**File:** `compiler/GHC/Unit/Module/ModDetails.hs:20-56`

`ModDetails` is the "cache" for home modules, constructed from `TcGblEnv`:

```haskell
data ModDetails = ModDetails
   { md_exports   :: [AvailInfo]        -- ^ What's exported
   , md_types     :: !TypeEnv           -- ^ Local type environment (TyThings)
   , md_defaults  :: !DefaultEnv        -- ^ Default declarations
   , md_insts     :: InstEnv            -- ^ DFunIds for instances
   , md_fam_insts :: ![FamInst]         -- ^ Family instances
   , md_rules     :: ![CoreRule]        -- ^ Rewrite rules
   , md_anns      :: ![Annotation]      -- ^ Annotations
   , md_complete_matches :: CompleteMatches  -- ^ COMPLETE pragmas
   }
```

## Flow: Typechecking to Interface

```
Typechecking Phase (TcGblEnv accumulation)
==========================================
Source Code
    ↓
tcRnModule
    ↓
tcRnSrcDecls
    ↓
For each declaration group:
    - Typecheck -> accumulate in tcg_binds, tcg_rules, etc.
    - Zonk -> resolve metavariables
    - Update tcg_type_env
    ↓
Final TcGblEnv with all fields populated


Conversion to ModDetails (GHC.Iface.Tidy)
=========================================
TcGblEnv
    { tcg_type_env, tcg_insts, tcg_fam_insts, tcg_rules,
      tcg_anns, tcg_complete_matches, tcg_exports, tcg_default_exports }
    ↓
tidyProgram / mkBootModDetailsTc
    ↓
ModDetails
    { md_types, md_insts, md_fam_insts, md_rules, md_anns,
      md_complete_matches, md_exports, md_defaults }


Interface File Construction (GHC.Iface.Make)
=============================================
ModDetails
    ↓
mkIface_
    ↓
ModIface
    { mi_decls      <- tyThingToIfaceDecl (md_types)
      mi_insts      <- instanceToIfaceInst (md_insts)
      mi_fam_insts  <- famInstToIfaceFamInst (md_fam_insts)
      mi_rules      <- coreRuleToIfaceRule (md_rules)
      mi_anns       <- mkIfaceAnnotation (md_anns)
      mi_exports    <- mkIfaceExports (md_exports)
      ... }
    ↓
Serialized to .hi file
```

### Construction Details

**File:** `compiler/GHC/Iface/Tidy.hs:164-189` (mkBootModDetailsTc)

```haskell
mkBootModDetailsTc logger
        TcGblEnv{ tcg_exports          = exports,
                  tcg_type_env         = type_env,
                  tcg_tcs              = tcs,
                  tcg_patsyns          = pat_syns,
                  tcg_insts            = insts,
                  tcg_fam_insts        = fam_insts,
                  tcg_complete_matches = complete_matches,
                  tcg_mod              = this_mod,
                  tcg_default_exports  = default_exports
                }
  = return (ModDetails { md_types            = type_env'
                       , md_defaults         = default_exports
                       , md_insts            = insts'
                       , md_fam_insts        = fam_insts
                       , md_rules            = []  -- no rules in boot files
                       , md_anns             = []  -- no anns in boot files
                       , md_exports          = exports
                       , md_complete_matches = complete_matches
                       })
```

**File:** `compiler/GHC/Iface/Tidy.hs:475-484` (tidyProgram)

```haskell
return (CgGuts { ... }
       , ModDetails { md_types            = tidy_type_env
                    , md_rules            = tidy_rules
                    , md_defaults         = cls_defaults
                    , md_insts            = tidy_cls_insts
                    , md_fam_insts        = fam_insts
                    , md_exports          = exports
                    , md_anns             = anns
                    , md_complete_matches = complete_matches
                    }
       )
```

### Interface File Serialization

**File:** `compiler/GHC/Iface/Make.hs:307-393` (mkIface_)

Shows how `ModDetails` is converted to interface file format:

```haskell
mkIface_ hsc_env ... 
         ModDetails{ md_defaults  = defaults,
                     md_insts     = insts,
                     md_fam_insts = fam_insts,
                     md_rules     = rules,
                     md_anns      = anns,
                     md_types     = type_env,
                     md_exports   = exports,
                     md_complete_matches = complete_matches }
  = do
    let decls  = [ tyThingToIfaceDecl entity
                 | entity <- typeEnvElts type_env,
                   not (isImplicitTyThing entity),
                   not (isWiredInName (getName entity)) ]
        
        iface_rules = map coreRuleToIfaceRule rules
        iface_insts = map instanceToIfaceInst $ instEnvElts insts
        iface_fam_insts = map famInstToIfaceFamInst fam_insts
        annotations = map mkIfaceAnnotation anns
        
    emptyPartialModIface this_mod
          & set_mi_exports          (mkIfaceExports exports)
          & set_mi_defaults         (defaultsToIfaceDefaults defaults)
          & set_mi_insts            (sortBy cmp_inst iface_insts)
          & set_mi_fam_insts        (sortBy cmp_fam_inst iface_fam_insts)
          & set_mi_rules            (sortBy cmp_rule iface_rules)
          & set_mi_anns             annotations
          & set_mi_decls            decls
          & set_mi_complete_matches (map mkIfaceCompleteMatch complete_matches)
          ...
```

### TyThing Serialization (IfaceDecl)

**File:** `compiler/GHC/Iface/Syntax.hs:187-253`

TyThings are serialized as `IfaceDecl`:

```haskell
data IfaceDecl
  = IfaceId { ifName      :: IfaceTopBndr,
              ifType      :: IfaceType,
              ifIdDetails :: IfaceIdDetails,
              ifIdInfo    :: IfaceIdInfo }

  | IfaceData { ifName       :: IfaceTopBndr,
                ifKind       :: IfaceType,
                ifBinders    :: [IfaceTyConBinder],
                ...
                ifCons       :: IfaceConDecls }

  | IfaceSynonym { ifName    :: IfaceTopBndr,
                   ifSynRhs  :: IfaceType }

  | IfaceFamily  { ifName    :: IfaceTopBndr,
                   ifFamFlav :: IfaceFamTyConFlav }

  | IfaceClass { ifName    :: IfaceTopBndr,
                 ifBody    :: IfaceClassBody }

  | IfaceAxiom { ifName       :: IfaceTopBndr,
                 ifAxBranches :: [IfaceAxBranch] }

  | IfacePatSyn { ifName          :: IfaceTopBndr,
                  ifPatMatcher    :: (IfExtName, Bool),
                  ifPatBuilder    :: Maybe (IfExtName, Bool),
                  ... }
```

## Related Topics

- **Source Files:**
  - `compiler/GHC/Tc/Types.hs` - TcGblEnv definition (lines 466-694)
  - `compiler/GHC/Tc/Module.hs` - tcRnModule entry (lines 200-213), tcRnSrcDecls (lines 546-651)
  - `compiler/GHC/Unit/Module/ModDetails.hs` - ModDetails definition (lines 20-56)
  - `compiler/GHC/Iface/Tidy.hs` - tidyProgram, mkBootModDetailsTc (lines 164-189, 475-484)
  - `compiler/GHC/Unit/Module/ModIface.hs` - ModIface definition (lines 318-378)
  - `compiler/GHC/Iface/Syntax.hs` - IfaceDecl serialization (lines 187-253)
  - `compiler/GHC/Iface/Make.hs` - Interface construction (lines 307-393)

- **Validation Notes:**
  - 10 output categories validated
  - TcGblEnv fields verified
  - ModDetails mapping confirmed
  - Flow description conceptually correct
  - Confidence: HIGH

- **See Also:**
  - TyThings exploration
  - Interface file format
  - Module compilation pipeline
