# Typechecking Phase: Constructor and TyThing Lookup

**Status:** Validated
**Last Updated:** 2026-04-13
**Central Question:** How does GHC's typechecking phase look up type constructors and data constructors? How does the TcM monad work, and what does GhcTc mean?

## Summary

GHC's typechecking phase (`TcRn`, historically `TcM`) uses a two-tier environment architecture. Pattern matching on data constructors goes through `tcDataConPat`, which calls `tcLookupConLike` → `tcLookupGlobal`. The `tcLookupGlobal` function first checks the local `tcg_type_env` (which only contains definitions from the current module), and if not found and the name is external, fetches the `TyThing` on-demand from the Home Package Table (HPT) or External Package Table (EPS) via interface loading.

## Claims

### Claim 1: TcM = TcRn = TcRnIf TcGblEnv TcLclEnv
**Statement:** The typechecking monad is a reader-transformer monad layered over `IOEnv (Env TcGblEnv TcLclEnv)`.
**Source:** `compiler/GHC/Tc/Types.hs:253-254`
**Evidence:**
```haskell
type TcRnIf a b = IOEnv (Env a b)
type TcRn       = TcRnIf TcGblEnv TcLclEnv    -- Type inference
type TcM        = TcRn                        -- Historical alias
```
**Status:** Validated

### Claim 2: TcGblEnv tracks module-level typechecking state
**Statement:** `TcGblEnv` holds the global type environment (`tcg_type_env :: TypeEnv`), reader environment (`tcg_rdr_env :: GlobalRdrEnv`), instance environment, and other module-level accumulators.
**Source:** `compiler/GHC/Tc/Types.hs:466-490`
**Evidence:**
```haskell
data TcGblEnv
  = TcGblEnv {
        tcg_mod     :: Module,
        tcg_rdr_env :: GlobalRdrEnv,
        tcg_type_env :: TypeEnv,
        tcg_type_env_var :: KnotVars (IORef TypeEnv),
        tcg_inst_env     :: !InstEnv,
        tcg_fam_inst_env :: !FamInstEnv,
        ...
    }
```
**Status:** Validated

### Claim 3: TcLclEnv tracks expression-level local state
**Statement:** `TcLclEnv` holds `TcLclCtxt` (which contains `tcl_env :: TcTypeEnv` for local bindings), constraint accumulator (`tcl_lie`), source location, and error context. The `tcl_env` field is actually inside `TcLclCtxt`, not directly in `TcLclEnv`.
**Source:** `compiler/GHC/Tc/Types/LclEnv.hs:76-122`
**Evidence:**
```haskell
data TcLclEnv
  = TcLclEnv {
        tcl_lcl_ctxt    :: !TcLclCtxt,
        tcl_usage :: TcRef UsageEnv,
        tcl_lie  :: TcRef WantedConstraints,
        tcl_errs :: TcRef (Messages TcRnMessage)
    }

data TcLclCtxt
  = TcLclCtxt {
        tcl_loc        :: RealSrcSpan,
        tcl_ctxt       :: [ErrCtxt],
        ...
        tcl_env  :: TcTypeEnv    -- The local type environment:
                                  -- Ids and TyVars defined in this module
    }
```
**Status:** Validated (Corrected - local bindings are in TcLclCtxt, not directly in TcLclEnv)

### Claim 4: GhcTc is a pass marker for typechecked AST
**Statement:** `GhcTc = GhcPass 'Typechecked` marks AST nodes that have been processed by the typechecker. At this point, identifiers have been converted from `RdrName` → `Name` → `Id`.
**Source:** `compiler/GHC/Hs/Extension.hs:151,166`
**Evidence:**
```haskell
data GhcPass (c :: Pass) where
  GhcTc :: GhcPass 'Typechecked

type GhcTc   = GhcPass 'Typechecked -- Output of typechecker

type family IdGhcP pass where
  IdGhcP 'Parsed      = RdrName
  IdGhcP 'Renamed     = Name
  IdGhcP 'Typechecked = Id
```
**Status:** Validated

### Claim 5: tcDataConPat is the entry point for data constructor pattern checking
**Statement:** When typechecking a pattern like `C x y`, the flow is: `tcConPat` → `tcLookupConLike` → `tcLookupGlobal` → (if external) `tcLookupImported_maybe`.
**Source:** `compiler/GHC/Tc/Gen/Pat.hs:1131-1139,1154-1268`
**Evidence:**
```haskell
tcConPat penv (L loc qcon) pat_ty arg_pats thing_inside
  = do  { con_lname = L loc (getName qcon)
        ; con_like <- tcLookupConLike qcon
        ; case con_like of
            RealDataCon data_con -> tcDataConPat con_lname data_con pat_ty
                                                 penv arg_pats thing_inside
```

```haskell
tcDataConPat (L con_span con_name) data_con pat_ty_scaled
             penv arg_pats thing_inside
  = do  { let tycon = dataConTyCon data_con
               -- For data families this is the representation tycon
        ; (wrap, ctxt_res_tys) <- matchExpectedConTy penv tycon pat_ty_scaled
        ; ...
```
**Status:** Validated

### Claim 6: tcLookupConLike dispatches to tcLookupGlobal then unwraps ConLike
**Statement:** `tcLookupConLike` calls `tcLookupGlobal name` and pattern matches on the result to extract either a `RealDataCon` or `PatSynCon`.
**Source:** `compiler/GHC/Tc/Utils/Env.hs:294-300`
**Evidence:**
```haskell
tcLookupConLike :: WithUserRdr Name -> TcM ConLike
tcLookupConLike qname@(WithUserRdr _ name) = do
    thing <- tcLookupGlobal name
    case thing of
        AConLike cl -> return cl
        ATyCon  {}  -> failIllegalTyCon WL_ConLike qname
        _           -> wrongThingErr WrongThingConLike (AGlobal thing) name
```
**Status:** Validated

### Claim 7: tcLookupGlobal uses 3-tier lookup
**Statement:** `tcLookupGlobal` first checks `tcg_type_env` (local definitions), then checks if the name is local to this module, and if not, calls `tcLookupImported_maybe` to fetch from HPT/EPS.
**Source:** `compiler/GHC/Tc/Utils/Env.hs:246-269`
**Evidence:**
```haskell
tcLookupGlobal name
  = do  {    -- Try local envt
          env <- getGblEnv
        ; case lookupNameEnv (tcg_type_env env) name of {
                Just thing -> return thing ;
                Nothing    ->
          if nameIsLocalOrFrom (tcg_semantic_mod env) name
          then notFound name  -- Internal names can happen in GHCi
          else
           -- Try home package table and external package table
          do  { mb_thing <- tcLookupImported_maybe name
              ; case mb_thing of
                  Succeeded thing -> return thing
                  Failed msg      -> failWithTc (TcRnInterfaceError msg)
              }}}
```
**Status:** Validated

### Claim 8: tcg_type_env only contains local definitions
**Statement:** `tcg_type_env` starts empty and is populated incrementally with TyThings defined in the current module. Imported names are NEVER copied into it — they are fetched on-demand from HPT/EPS.
**Source:** `compiler/GHC/Tc/Utils/Monad.hs:352` (initialization) and `compiler/GHC/Tc/Utils/Env.hs:250-269` (lookup logic)
**Evidence:**
```haskell
-- Initialization (tcg_type_env = emptyNameEnv)
, tcg_type_env           = emptyNameEnv

-- Lookup: imported names go to HPT/EPS, not tcg_type_env
; case lookupNameEnv (tcg_type_env env) name of {
        Just thing -> return thing ;
        Nothing    ->
  if nameIsLocalOrFrom (tcg_semantic_mod env) name
  then notFound name
  else do { mb_thing <- tcLookupImported_maybe name ... }
```
**Status:** Validated

### Claim 9: tcLookupImported_maybe fetches from HPT/EPS on-demand
**Statement:** `tcLookupImported_maybe` first tries `lookupType hsc_env name` (which checks HPT then EPS), and if not found, calls `tcImportDecl_maybe` to load the interface file.
**Source:** `compiler/GHC/Iface/Load.hs:150-168`
**Evidence:**
```haskell
tcLookupImported_maybe :: Name -> TcM (MaybeErr IfaceMessage TyThing)
tcLookupImported_maybe name
  = do  { hsc_env <- getTopEnv
        ; mb_thing <- liftIO (lookupType hsc_env name)
        ; case mb_thing of
            Just thing -> return (Succeeded thing)
            Nothing    -> tcImportDecl_maybe name }
```
**Status:** Validated

### Claim 10: lookupType checks HPT first, then EPS
**Statement:** The `lookupType` function in `GHC.Driver.Env` checks the Home Unit Graph (HPT) first by module, then falls back to the External Package Table (EPS).
**Source:** `compiler/GHC/Driver/Env.hs:331-351`
**Evidence:**
```haskell
lookupType hsc_env name = do
   eps <- liftIO $ hscEPS hsc_env
   let pte = eps_PTE eps
   lookupTypeInPTE hsc_env pte name

lookupTypeInPTE hsc_env pte name = ty
  where
    hpt = hsc_HUG hsc_env
    ty = if isOneShot (ghcMode (hsc_dflags hsc_env))
            then return $! lookupNameEnv pte name
            else HUG.lookupHugByModule mod hpt >>= \case
             Just hm -> pure $! lookupNameEnv (md_types (hm_details hm)) name
             Nothing -> pure $! lookupNameEnv pte name
```
**Status:** Validated

### Claim 11: NameEnv is a wrapper around UniqFM (Name → a map)
**Statement:** `lookupNameEnv` is defined as `lookupUFM` — a simple wrapper around the unique-keyed finite map. `NameEnv a` is `Name → a`.
**Source:** `compiler/GHC/Types/Name/Env.hs:126,142`
**Evidence:**
```haskell
lookupNameEnv      :: NameEnv a -> Name -> Maybe a
lookupNameEnv x y     = lookupUFM x y
```
**Status:** Validated
**Confidence:** High

### Claim 12: TypeEnv = NameEnv TyThing
**Statement:** `TypeEnv` is a type alias for `NameEnv TyThing`. It maps `Name` to `TyThing`.
**Source:** `compiler/GHC/Types/TypeEnv.hs:39`
**Evidence:**
```haskell
type TypeEnv = NameEnv TyThing
```
**Status:** Validated
**Confidence:** High

### Claim 13: HomeModInfo contains hm_details :: ModDetails
**Statement:** `HomeModInfo` wraps a `ModDetails` which contains `md_types :: TypeEnv`. This is the home module's type environment, populated during typechecking. The field is LAZY to support knot-tying.
**Source:** `compiler/GHC/Unit/Home/ModInfo.hs:23-28`, `compiler/GHC/Unit/Module/ModDetails.hs:23`
**Evidence:**
```haskell
data HomeModInfo = HomeModInfo
   { hm_iface    :: !ModIface
   , hm_details  :: ModDetails   -- ^ LAZY: constructed by knot tying
   , hm_linkable :: !HomeModLinkable
   }

data ModDetails = ModDetails
   { md_types     :: !TypeEnv
      -- ^ Local type environment for this particular module
      -- Includes Ids, TyCons, PatSyns
   , ...
   }
```
**Status:** Validated
**Confidence:** High

### Claim 14: lookupTypeInPTE checks HPT first, then EPS
**Statement:** In non-one-shot mode, `lookupTypeInPTE` first calls `lookupHugByModule` to find the `HomeModInfo` for the name's module, then looks up in that module's `md_types`. Only if HPT lookup fails does it fall back to the EPS (PackageTypeEnv / PTE).
**Source:** `compiler/GHC/Driver/Env.hs:331-351`
**Evidence:**
```haskell
lookupTypeInPTE hsc_env pte name = ty
  where
    hpt = hsc_HUG hsc_env
    mod = if isHoleName name
            then mkHomeModule ... (moduleName (nameModule name))
            else nameModule name

    ty = if isOneShot (ghcMode (hsc_dflags hsc_env))
            then return $! lookupNameEnv pte name
            else HUG.lookupHugByModule mod hpt >>= \case
             Just hm -> pure $! lookupNameEnv (md_types (hm_details hm)) name
             Nothing -> pure $! lookupNameEnv pte name
```
**Status:** Validated

### Claim 15: Imported lookup results are NEVER cached back to tcg_type_env
**Statement:** `tcLookupGlobal` calls `tcLookupImported_maybe` for external names, but the resulting `TyThing` is returned directly — it is NOT inserted into `tcg_type_env`. The `tcg_type_env` only contains local definitions added via `tcExtendGlobalEnvImplicit`, `tcExtendTyConEnv`, etc. This means every imported lookup is a fresh HPT/EPS query.
**Source:** `compiler/GHC/Tc/Utils/Env.hs:246-269`
**Evidence:**
```haskell
tcLookupGlobal name
  = do  { env <- getGblEnv
        ; case lookupNameEnv (tcg_type_env env) name of {
                Just thing -> return thing ;
                Nothing    ->
          if nameIsLocalOrFrom (tcg_semantic_mod env) name
          then notFound name
          else do { mb_thing <- tcLookupImported_maybe name
                  ; case mb_thing of
                        Succeeded thing -> return thing   -- returned, NOT written to tcg_type_env
                        Failed msg      -> failWithTc ...
        }}}
```
**Status:** Validated

## Open Questions

- [ ] What is the role of `tcg_type_env_var` (KnotVars) for recursive type declarations?
- [ ] How does Backpack extend the lookup mechanism with signature merging?

## Related Topics

- [TCTYPE_ENV_EXPLORATION.md](../analysis/TCTYPE_ENV_EXPLORATION.md) — How tcg_type_env is built
- [READER_ENV_EXPLORATION.md](../analysis/READER_ENV_EXPLORATION.md) — GlobalRdrEnv architecture
- [PATTERN_TC_FACTS.md](../analysis/PATTERN_TC_FACTS.md) — Pattern matching type checking
