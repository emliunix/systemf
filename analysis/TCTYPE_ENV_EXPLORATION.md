# How tcg_type_env is Built and Why tcg_rdr_env Persists into Typechecking

**Status:** Validated
**Last Updated:** 2026-03-31
**Central Question:** What are the sources that feed `tcg_type_env`, and what visibility role does `tcg_rdr_env` serve during typechecking?

## Summary

GHC's `TcGblEnv` carries two distinct environments: `tcg_type_env` (TypeEnv: Name → TyThing) and `tcg_rdr_env` (GlobalRdrEnv: OccName → [GRE]). They answer different questions. `tcg_type_env` answers "what is this thing?" — providing type information for any Name the typechecker knows about. `tcg_rdr_env` answers "is this thing visible to the user?" — carrying provenance (import specs, local/external status). The typechecker needs both because certain semantic decisions (newtype unwrapping, instance resolution, deriving) depend on visibility, not just existence.

`tcg_type_env` is populated incrementally from local definitions during typechecking, and only contains things defined in the current module. Imported names are resolved on-demand through HPT (Home Package Table) and EPS (External Package Table), never eagerly copied into `tcg_type_env`.

## Claims

### Claim 1: tcg_type_env starts empty
**Statement:** `tcg_type_env` is initialized to `emptyNameEnv` at the start of every typechecking session.
**Source:** `compiler/GHC/Tc/Utils/Monad.hs:352`
**Evidence:**
```haskell
, tcg_type_env           = emptyNameEnv
```
**Status:** Validated
**Confidence:** High
**Notes:** Confirmed in `initTc` function which builds the initial `TcGblEnv`.

### Claim 2: Local type/class declarations populate tcg_type_env via tcExtendGlobalEnv family
**Statement:** Type and class declarations are added to `tcg_type_env` during typechecking through nested calls: `tcExtendTyConEnv` (TyCons) → `tcExtendGlobalEnvImplicit` (implicit things: data constructors, field selectors) → `tcExtendGlobalValEnv` (default method Ids).
**Source:** `compiler/GHC/Tc/TyCl/Utils.hs:758-761`
**Evidence:**
```haskell
addTyConsToGblEnv tyclss
  = tcExtendTyConEnv tyclss                    $
    tcExtendGlobalEnvImplicit implicit_things  $
    tcExtendGlobalValEnv def_meth_ids          $
    do { ... }
 where
   implicit_things = concatMap implicitTyConThings tyclss
   def_meth_ids    = mkDefaultMethodIds tyclss
```
**Status:** Validated
**Confidence:** High
**Notes:** Each of these calls does `extendTypeEnvList (tcg_type_env env) things` then `setGlobalTypeEnv`.

### Claim 3: tcExtendGlobalEnvImplicit is the low-level populator
**Statement:** All `tcExtend*` functions ultimately call `tcExtendGlobalEnvImplicit`, which does `extendTypeEnvList` on `tcg_type_env` and syncs `tcg_type_env_var`.
**Source:** `compiler/GHC/Tc/Utils/Env.hs:497-504`
**Evidence:**
```haskell
tcExtendGlobalEnvImplicit things thing_inside
   = do { tcg_env <- getGblEnv
        ; let ge'  = extendTypeEnvList (tcg_type_env tcg_env) things
        ; tcg_env' <- setGlobalTypeEnv tcg_env ge'
        ; setGblEnv tcg_env' thing_inside }
```
**Status:** Validated
**Confidence:** High

### Claim 4: setGlobalTypeEnv syncs knot-tying IORef
**Statement:** `setGlobalTypeEnv` updates both `tcg_type_env` (the pure field) and `tcg_type_env_var` (the IORef visible to interface loading for knot-tying recursive types).
**Source:** `compiler/GHC/Tc/Utils/Env.hs:485-494`
**Evidence:**
```haskell
setGlobalTypeEnv tcg_env new_type_env
  = do  { case lookupKnotVars (tcg_type_env_var tcg_env) (tcg_mod tcg_env) of
               Just tcg_env_var -> writeMutVar tcg_env_var new_type_env
               Nothing -> return ()
        ; return (tcg_env { tcg_type_env = new_type_env }) }
```
**Status:** Validated
**Confidence:** High
**Notes:** The knot-tying mechanism allows mutually recursive type declarations to see each other during kind-checking.

### Claim 5: Local value bindings are promoted to tcg_type_env only after zonking
**Statement:** Top-level value bindings live in the local type env (`tcl_env`) during typechecking. Their Ids are added to `tcg_type_env` only after constraint solving and zonking, via `plusTypeEnv id_env`.
**Source:** `compiler/GHC/Tc/Module.hs:591-603`
**Evidence:**
```haskell
--   * Add the zonked Ids from the value bindings to tcg_type_env
--     Up to now these Ids are only in tcl_env's type-envt
init_tcg_env = tcg_env { tcg_type_env  = tcg_type_env tcg_env
                                      `plusTypeEnv` id_env }
```
**Status:** Validated
**Confidence:** High
**Notes:** This happens twice — once for main bindings, once after TH finalizers (line 636-637: `plusTypeEnv id_env_mf`).

### Claim 6: Imported names are NOT stored in tcg_type_env
**Statement:** `tcg_type_env` only contains things defined in the current module. Imported names are resolved on-demand through HPT and EPS caches, never eagerly copied into `tcg_type_env`.
**Source:** `compiler/GHC/Tc/Utils/Env.hs:250-269`
**Evidence:**
```haskell
tcLookupGlobal name
  = do  { env <- getGblEnv
        ; case lookupNameEnv (tcg_type_env env) name of {
                Just thing -> return thing ;
                Nothing    ->
          if nameIsLocalOrFrom (tcg_semantic_mod env) name
          then notFound name
          else
     do  { mb_thing <- tcLookupImported_maybe name
         ; ... }}}
```
**Status:** Validated
**Confidence:** High
**Notes:** The 3-tier lookup: (1) tcg_type_env, (2) local-module check, (3) HPT/EPS on-demand. Confirmed: `tcRnImports` at `Tc/Module.hs:491-503` does NOT touch `tcg_type_env`.

### Claim 7: Import lookup checks HPT first, then EPS
**Statement:** `lookupType` in `GHC.Driver.Env` checks the Home Unit Graph (HPT) first by module, then falls back to the External Package Table (EPS).
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
**Confidence:** High
**Notes:** One-shot mode (batch compilation) skips HPT entirely and goes straight to PTE.

### Claim 8: Interactive context populates tcg_type_env from ic_tythings
**Statement:** In GHCi, `runTcInteractive` builds `tcg_type_env` from `ic_tythings` (closed TyThings go to global env, open Ids go to local env) plus dfuns from `ic_instances`.
**Source:** `compiler/GHC/Tc/Module.hs:2148-2183`
**Evidence:**
```haskell
gbl_env' = gbl_env
  { tcg_type_env     = type_env, ... }

type_env1 = mkTypeEnvWithImplicits top_ty_things
type_env  = extendTypeEnvWithIds type_env1
          $ map instanceDFunId (instEnvElts ic_insts)
```
Where `top_ty_things` are the "closed" TyThings from `ic_tythings`, and open Ids go to `lcl_env` via `tcExtendLocalTypeEnv`.
**Status:** Validated
**Confidence:** High

### Claim 9: tcg_rdr_env in typechecker serves primarily visibility, not resolution
**Statement:** After renaming, `tcg_rdr_env` is used during typechecking primarily for visibility and semantic checks — determining whether a named entity is "in scope" — not for RdrName→Name resolution (which is already complete).
**Source:** Multiple files using `lookupGRE_Name rdr_env` during typechecking
**Evidence:**
The renamer resolves all `RdrName → Name`. The typechecker uses `tcg_rdr_env` to ask "is this Name visible?" via `lookupGRE_Name`:
- `Tc/Instance/Family.hs:514`: `lookupGRE_Name rdr_env (dataConName con)` — newtype unwrapping
- `Tc/Instance/Class.hs:640`: `lookupGRE_Name rdr_env $ dataConName con` — DataToTag
- `Tc/Deriv.hs:2116`: `lookupGRE_Name rdr_env dc` — deriving visibility
- `Tc/Solver/Equality.hs:2194`: `lookupGRE_Name rdr_env (dataConName con)` — solver newtype check
- `Tc/Gen/Foreign.hs:198`: `lookupGRE_Name rdr_env (dataConName con)` — newtype FFI check
- `Tc/Gen/Export.hs:1147`: `expectJust . lookupGRE_Name rdr_env` — export resolution
**Status:** Validated (Partial — "exclusively" corrected to "primarily"; Export/Foreign uses are semantic checks, not pure visibility, but none perform RdrName→Name resolution)
**Confidence:** Medium-High

### Claim 10: Newtype unwrapping depends on constructor visibility via rdr_env
**Statement:** The constraint solver will only unwrap a newtype if its data constructor is in scope, checked via `lookupGRE_Name` on `tcg_rdr_env`. This is a semantic decision affecting type equality solving.
**Source:** `compiler/GHC/Tc/Instance/Family.hs:508-518`
**Evidence:**
```haskell
try_nt_unwrap tc tys
  | Just con <- newTyConDataCon_maybe tc
  , Just (ty', co) <- instNewTyCon_maybe tc tys
  = case lookupGRE_Name rdr_env (dataConName con) of
      Nothing -> Left $ outOfScopeNT con
      Just gre -> Right (gre, co, ty')
```
**Status:** Validated
**Confidence:** High
**Notes:** This is passed `GlobalRdrEnv` explicitly — see `can_eq_nc` signature at `Tc/Solver/Equality.hs:420`: `-> GlobalRdrEnv -- needed to see which newtypes are in scope`.

### Claim 11: DataToTag requires all constructors in scope
**Statement:** The built-in DataToTag instance only matches if ALL data constructors of the type are in scope, checked via `lookupGRE_Name` on `tcg_rdr_env`.
**Source:** `compiler/GHC/Tc/Instance/Class.hs:639-641`
**Evidence:**
```haskell
, let  rdr_env = tcg_rdr_env gbl_env
       inScope con = isJust $ lookupGRE_Name rdr_env $ dataConName con
, all inScope constrs
```
**Status:** Validated
**Confidence:** High

### Claim 12: Error diagnostics enumerate rdr_env for suggestions
**Statement:** Error messages (hole fits, HasField, import suggestions) enumerate `globalRdrEnvElts rdr_env` to find candidate names or suggest imports.
**Source:** `compiler/GHC/Tc/Errors/Hole.hs:592,611`
**Evidence:**
```haskell
do { rdr_env <- getGlobalRdrEnv
   ; let (lcl, gbl) = partition gre_lcl (globalRdrEnvElts rdr_env)
```
**Status:** Validated
**Confidence:** High

### Claim 13: tcg_type_env and tcg_rdr_env answer different questions
**Statement:** `tcg_type_env` (TypeEnv: Name → TyThing) answers "what is this thing?" — providing type/kind information. `tcg_rdr_env` (GlobalRdrEnv: OccName → [GRE]) answers "is this visible and how did it come into scope?" — carrying provenance. Neither subsumes the other.
**Source:** Type definitions + usage patterns
**Evidence:**
- TypeEnv: `lookupTypeEnv :: TypeEnv -> Name -> Maybe TyThing` — lookup by Name, returns TyThing
- GlobalRdrEnv: `lookupGRE_Name :: GlobalRdrEnv -> Name -> Maybe GlobalRdrElt` — lookup by Name, returns GRE with provenance
- A TyThing can exist in `tcg_type_env` but not be visible (not in `tcg_rdr_env`) — e.g., hidden constructors, abstract type constructors
**Status:** Validated
**Confidence:** High

### Claim 14: Deriving checks data constructor visibility via rdr_env
**Statement:** Standalone deriving requires all data constructors to be in scope, checked via `lookupGRE_Name` on `tcg_rdr_env`. Hidden constructors cause the deriving to fail.
**Source:** `compiler/GHC/Tc/Deriv.hs:2111-2123`
**Evidence:**
```haskell
rdr_env <- lift getGlobalRdrEnv
let data_con_names = map dataConName (tyConDataCons rep_tc)
    hidden_data_cons = not (isWiredIn rep_tc) &&
                       (isAbstractTyCon rep_tc ||
                        any not_in_scope data_con_names)
    not_in_scope dc  = isNothing (lookupGRE_Name rdr_env dc)
```
**Status:** Validated
**Confidence:** High

## Open Questions
- [x] Does the typechecker ever *modify* tcg_rdr_env after renaming, or is it frozen?
  **Answer:** Not frozen. `tcRnImports` at `Tc/Module.hs:493` sets it during renamer→TC handoff. Backpack processing (`Tc/Utils/Backpack.hs:640,691,954`) extends it during typechecking. But for ordinary (non-Backpack) compilation, it is effectively frozen after `tcRnImports`.
- [ ] For elab3: what is the minimal visibility check we need during typechecking?

## Related Topics
- [READER_ENV_EXPLORATION.md](READER_ENV_EXPLORATION.md) — ReaderEnv architecture for name resolution
- [INTERACTIVE_CONTEXT_EXPLORATION.md](INTERACTIVE_CONTEXT_EXPLORATION.md) — InteractiveContext and ic_tythings
