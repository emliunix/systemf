# Typechecking Lookup Deep Dive - HPT/EPS and NameEnv

**Status:** In Progress
**Last Updated:** 2026-04-13
**Central Question:** How do HPT/EPS, NameEnv, TypeEnv, and HomeUnitGraph work in the import lookup path? Does tcLookupGlobal cache imported results?

## Summary

Building on TCTC_LOOKUP_EXPLORATION.md, this session investigates the lower-level machinery: how `lookupTypeInPTE` dispatches between Home Package Table (HPT) and External Package Table (EPS), what `NameEnv`/`TypeEnv` actually are, and the critical finding that `tcLookupGlobal` never caches imported lookups back into `tcg_type_env`.

## Scope IN

- `NameEnv` / `TypeEnv` type definitions and `lookupNameEnv`
- `HomeUnitGraph`, `HomeModInfo`, `ModDetails`, `md_types`
- `lookupTypeInPTE` HPT vs EPS dispatch logic
- Whether imported lookup results are cached in `tcg_type_env`

## Scope OUT

- tcLookupGlobal / tcLookupConLike (covered in master)
- TcGblEnv / TcLclEnv structure (covered in master)
- TcM monad definition (covered in master)

## Entry Points

- `GHC/Types/Name/Env.hs:126` — `lookupNameEnv` type and implementation
- `GHC/Types/TypeEnv.hs:39` — `TypeEnv = NameEnv TyThing`
- `GHC/Unit/Module/ModDetails.hs:20-43` — `ModDetails` with `md_types`
- `GHC/Unit/Home/ModInfo.hs:23-48` — `HomeModInfo` with `hm_details`
- `GHC/Unit/Home/Graph.hs:259` — `lookupHugByModule`
- `GHC/Driver/Env.hs:331-351` — `lookupTypeInPTE`

## Claims

### Claim 1: NameEnv is a wrapper around UniqFM (Name → a map)
**Statement:** `lookupNameEnv` is defined as `lookupUFM` — a simple wrapper around the unique-keyed finite map. `NameEnv a` is `Name → a`.
**Source:** `compiler/GHC/Types/Name/Env.hs:126,142`
**Evidence:**
```haskell
lookupNameEnv      :: NameEnv a -> Name -> Maybe a
lookupNameEnv x y     = lookupUFM x y
```
**Confidence:** High
**Status:** Draft

### Claim 2: TypeEnv = NameEnv TyThing
**Statement:** `TypeEnv` is simply a type alias for `NameEnv TyThing`. It maps `Name` to `TyThing` (type constructor, class, data constructor, etc.).
**Source:** `compiler/GHC/Types/TypeEnv.hs:39`
**Evidence:**
```haskell
type TypeEnv = NameEnv TyThing
```
**Confidence:** High
**Status:** Draft

### Claim 3: HomeModInfo contains hm_details :: ModDetails
**Statement:** `HomeModInfo` wraps a `ModDetails` which contains `md_types :: TypeEnv`. This is the home module's type environment, populated during typechecking.
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
**Confidence:** High
**Status:** Draft

### Claim 4: lookupTypeInPTE checks HPT first, then EPS
**Statement:** In non-one-shot mode, `lookupTypeInPTE` first calls `lookupHugByModule` to find the `HomeModInfo` for the name's module, then looks up in that module's `md_types`. Only if HPT lookup fails does it fall back to the EPS (PackageTypeEnv / PTE).
**Source:** `compiler/GHC/Driver/Env.hs:337-351`
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
**Confidence:** High
**Status:** Draft

### Claim 5: Imported lookup results are NEVER cached back to tcg_type_env
**Statement:** `tcLookupGlobal` calls `tcLookupImported_maybe` for external names, but the resulting `TyThing` is returned directly — it is NOT inserted into `tcg_type_env`. The `tcg_type_env` only contains local definitions added via `tcExtendGlobalEnvImplicit`, `tcExtendTyConEnv`, etc. This means every imported lookup is a fresh HPT/EPS query.
**Source:** `compiler/GHC/Tc/Utils/Env.hs:246-269` (lookup flow confirms no write-back)
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
**Confidence:** High
**Status:** Draft

## Open Questions

- [x] Is imported result cached in tcg_type_env? → No, confirmed
- [ ] How does knot-tying interact with HPT? (tcg_type_env_var)
- [ ] What triggers EPS population vs HPT population?

## Related Topics

- [TCTC_LOOKUP_EXPLORATION.md](../analysis/TCTC_LOOKUP_EXPLORATION.md) — Master file
- [TCTYPE_ENV_EXPLORATION.md](../analysis/TCTYPE_ENV_EXPLORATION.md) — How tcg_type_env is built
