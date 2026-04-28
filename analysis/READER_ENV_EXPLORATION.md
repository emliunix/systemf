# ReaderEnv Architecture

**Status:** Validated  
**Last Updated:** 2026-03-30  
**Central Question:** How does GHC's ReaderEnv (GlobalRdrEnv + LocalRdrEnv) work for name resolution, and what design does elab3 need?
**Validation:** 13/15 fully validated, 2/15 partial (Claims 2, 7). See READER_ENV_VALIDATION_TEMP.md for details.

## Summary

GHC's renamer uses two environments: LocalRdrEnv (lexical scope) and GlobalRdrEnv (imports, top-level, interactive defs). Name lookup is tiered: local first, then global. The GlobalRdrEnv maps OccName to a list of GREs, where each GRE carries a Name, provenance (local flag + bag of ImportSpecs), parent, and info. Shadowing is encoded in the environment via `shadowNames`, which converts older GREs to qualified-only rather than deleting them.

## Claims

### Claim 1: Two-Tier Lookup (LocalRdrEnv then GlobalRdrEnv)
**Statement:** The renamer tries LocalRdrEnv first, then GlobalRdrEnv. `lookupOccRnX_maybe` uses `msum` (first success wins) over `[lookupLocalOccRn_maybe, globalLookup]`.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Rename/Env.hs:1327-1338`
**Evidence:**
```haskell
lookupOccRnX_maybe globalLookup wrapper rdr_name
  = runMaybeT . msum . map MaybeT $
      [ do { res <- lookupLocalOccRn_maybe rdr_name
           ; case res of
           { Nothing -> return Nothing
           ; Just nm ->
           do { let gre = mkLocalVanillaGRE NoParent nm
              ; Just <$> wrapper gre } } }
      , globalLookup rdr_name ]
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 2: LocalRdrEnv Contains Only Lexical Bindings
**Statement:** LocalRdrEnv stores only local bindings (let, where, lambda, case pattern vars). Data constructors, type constructors, and imports are NOT in LocalRdrEnv.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:415-434` (Note at 415-428, data decl at 433-434)
**Evidence:**
```haskell
{- Note [LocalRdrEnv]
The LocalRdrEnv is used to store local bindings (let, where, lambda, case).
* It is keyed by OccName, because we never use it for qualified names.
* It maps the OccName to a Name.  That Name is almost always an
  Internal Name, but (hackily) it can be External too for top-level
  pattern bindings.
-}
data LocalRdrEnv = LRE { lre_env      :: OccEnv Name
                       , lre_in_scope :: NameSet }
```
**VALIDATED:** Partial  
**Source Check:** Note at 415-428 ✓. Data decl at 433-434 (not in original range). Paraphrase dropped External name nuance.  
**Logic Check:** Sound  
**Status:** Validated

### Claim 3: GlobalRdrEnv = OccEnv [GlobalRdrElt]
**Statement:** GlobalRdrEnv maps OccName to a list of GREs. Multiple GREs per OccName represent different Names with the same surface name (ambiguity), NOT the same Name with different provenance.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:527,556`
**Evidence:**
```haskell
type GlobalRdrEnv = GlobalRdrEnvX GREInfo
type GlobalRdrEnvX info = OccEnv [GlobalRdrEltX info]
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 4: GRE Has Five Fields
**Statement:** Each GlobalRdrElt carries: gre_name (resolved Name), gre_par (parent tycon), gre_lcl (locally defined?), gre_imp (Bag of ImportSpecs), gre_info (lazy metadata). The `info` type parameter allows forcing to `()` for long-lived structures.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:577-591`
**Evidence:**
```haskell
data GlobalRdrEltX info
  = GRE { gre_name :: !Name
        , gre_par  :: !Parent
        , gre_lcl  :: !Bool
        , gre_imp  :: !(Bag ImportSpec)
        , gre_info :: info
        }
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 5: Bag Is O(1) Merge via TwoBags
**Statement:** Bag is a catenable collection. `unionBags` is O(1) — just wraps in `TwoBags` node. This is why `gre_imp` uses Bag instead of list: import merging must be efficient when the same Name arrives through multiple import paths.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Data/Bag.hs:48-87`
**Evidence:**
```haskell
data Bag a
  = EmptyBag
  | UnitBag a
  | TwoBags (Bag a) (Bag a)   -- INVARIANT: neither branch is empty
  | ListBag (NonEmpty a)

unionBags :: Bag a -> Bag a -> Bag a
unionBags EmptyBag b = b
unionBags b EmptyBag = b
unionBags b1 b2      = TwoBags b1 b2
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 6: Per-OccName List vs Per-GRE Bag Are Different Tiers
**Statement:** The list per OccName holds GREs with *different* Names (ambiguity/shadowing). The bag per GRE holds ImportSpecs for the *same* Name through different import paths. `plusGRE` merges same-Name GREs by unioning their bags, not by extending the list.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:1663-1670`
**Evidence:**
```haskell
plusGRE :: GlobalRdrElt -> GlobalRdrElt -> GlobalRdrElt
plusGRE g1 g2
  = GRE { gre_name = gre_name g1
        , gre_lcl  = gre_lcl g1 || gre_lcl g2
        , gre_imp  = gre_imp g1 `unionBags` gre_imp g2
        , gre_par  = gre_par g1 `plusParent` gre_par g2
        , gre_info = gre_info g1 `plusGREInfo` gre_info g2 }
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 7: Lookup Dispatches on List Length
**Statement:** `lookupGreRn_helper` calls `lookupGRE` which returns `[GlobalRdrElt]`, then pattern matches on list length: `[]` → GreNotFound, `[gre]` → OneNameMatch, `(gre:rest)` → MultipleNames. The caller `lookupGreRn_maybe` handles MultipleNames by emitting `addNameClashErrRn` and returning `Just (NE.head gres)` for error recovery.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Rename/Env.hs:1719-1738,1767-1776`
**Evidence:**
```haskell
data GreLookupResult = GreNotFound
                     | OneNameMatch GlobalRdrElt
                     | MultipleNames (NE.NonEmpty GlobalRdrElt)

lookupGreRn_maybe which_gres rdr_name = do
    res <- lookupGreRn_helper which_gres rdr_name AllDeprecationWarnings
    case res of
      OneNameMatch gre ->  return $ Just gre
      MultipleNames gres -> do
        addNameClashErrRn rdr_name gres    -- error in caller, not helper
        return $ Just (NE.head gres)
      GreNotFound -> return Nothing

lookupGreRn_helper which_gres rdr_name warn_if_deprec
  = do  { env <- getGlobalRdrEnv
        ; case lookupGRE env (LookupRdrName rdr_name which_gres) of
            []    -> return GreNotFound
            [gre] -> do { addUsedGRE warn_if_deprec gre
                        ; return (OneNameMatch gre) }
            (gre:others) -> return (MultipleNames (gre NE.:| others)) }
```
**VALIDATED:** Partial  
**Source Check:** Verified — code matches. Original claim attributed ambiguity error to `lookupGreRn_helper`; actually in `lookupGreRn_maybe`.  
**Logic Check:** Sound  
**Status:** Validated

### Claim 8: Bag Filtering Drives Qualified/Unqualified Resolution
**Statement:** `pickGREs` dispatches on RdrName constructor. For `Unqual`: `filterBag unQualSpecOK` (keeps specs where `not is_qual`). For `Qual mod`: `filterBag (qualSpecOK mod)` (keeps specs where `mod == is_as`). If bag is empty after filtering and not local, the GRE is discarded.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:1576-1607,2145-2151`
**Evidence:**
```haskell
pickGREs (Unqual {})  gres = mapMaybe pickUnqualGRE     gres
pickGREs (Qual mod _) gres = mapMaybe (pickQualGRE mod) gres

pickUnqualGRE gre@(GRE { gre_lcl = lcl, gre_imp = iss })
  | not lcl, null iss' = Nothing
  | otherwise          = Just (gre { gre_imp = iss' })
  where iss' = filterBag unQualSpecOK iss

unQualSpecOK is = not (is_qual (is_decl is))
qualSpecOK mod is = mod == is_as (is_decl is)
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 9: gre_lcl Needed Because Local Defs Have Empty Bag
**Statement:** Local definitions have `gre_lcl = True` and `gre_imp = emptyBag`. Without `gre_lcl`, "locally defined" and "not in scope" would be indistinguishable (both empty bag). The check is always `not lcl && null iss' = Nothing`.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:1589-1602`
**Evidence:**
```haskell
pickUnqualGRE gre@(GRE { gre_lcl = lcl, gre_imp = iss })
  | not lcl, null iss' = Nothing    -- both channels empty = not in scope
  | otherwise          = Just (gre { gre_imp = iss' })
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 10: ImportSpec Is Two-Layer (Shared Decl + Per-Item)
**Statement:** `ImportSpec = ImpSpec { is_decl :: ImpDeclSpec, is_item :: ImpItemSpec }`. ImpDeclSpec is shared across all names from one import declaration (module, alias, qualified?, source location). ImpItemSpec is per-name: `ImpAll` (no import list) or `ImpSome { is_explicit, is_iloc }` (named in import list).
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:1982-2051`
**Evidence:**
```haskell
data ImportSpec = ImpSpec { is_decl :: !ImpDeclSpec, is_item :: !ImpItemSpec }

data ImpDeclSpec
  = ImpDeclSpec { is_mod :: !Module, is_as :: !ModuleName, is_qual :: !Bool, ... }

data ImpItemSpec
  = ImpAll
  | ImpSome { is_explicit :: !Bool, is_iloc :: !SrcSpan }
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 11: shadowNames Converts Older GREs to Qualified-Only
**Statement:** `shadowNames` doesn't delete old GREs. It converts them to qualified-only by: (1) setting `gre_lcl = False`, (2) converting all ImportSpecs to `is_qual = True` via `set_qual`, (3) creating a fake ImportSpec for local GREs with `is_qual = True` and `is_as = moduleName`. This means older interactive bindings remain accessible via qualified name (e.g. `Ghci3.x`).
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:1778-1847`
**Evidence:**
```haskell
shadow old_gre@(GRE { gre_lcl = lcl, gre_imp = iss }) =
  case greDefinitionModule old_gre of
    Nothing -> Just old_gre   -- Internal names: do not shadow
    Just old_mod
       |  null iss' || drop_only_qualified -> Nothing
       | otherwise -> Just (old_gre { gre_lcl = False, gre_imp = iss' })
       where iss' = lcl_imp `unionBags` mapBag set_qual iss
             lcl_imp | lcl = unitBag $ mk_fake_imp_spec old_gre old_mod
                     | otherwise = emptyBag

set_qual is = is { is_decl = (is_decl is) { is_qual = True } }
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 12: REPL Uses shadowNames on Interactive Env Then Merges with Import Env
**Statement:** `replaceImportEnv` recalculates the reader env by: (1) shadowing the import env with the prompt env (`shadowNames False import_env (igre_prompt_env igre)`), then (2) merging the shadowed import env with the prompt env (`plusGlobalRdrEnv`). `icExtendGblRdrEnv` adds TyThings one at a time (foldr) so each shadows previous ones.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:459-481`
**Evidence:**
```haskell
replaceImportEnv igre import_env = igre { igre_env = new_env }
  where
    import_env_shadowed = shadowNames False import_env (igre_prompt_env igre)
    new_env = import_env_shadowed `plusGlobalRdrEnv` igre_prompt_env igre

icExtendGblRdrEnv drop_only_qualified env tythings
  = foldr add env tythings    -- foldr: front shadows back
  where add thing env = ...
          env1 = shadowNames drop_only_qualified env $ mkGlobalRdrEnv new_gres
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 13: After shadowNames, Lookup Order Doesn't Matter
**Statement:** Post-shadowing, each GRE in the list is independent. Lookup does `filterBag` on each GRE individually — multiple surviving GREs is genuine ambiguity. List order only matters for shadowNames itself (first = unqualified, rest = qualified-only).
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:1576-1607`
**VALIDATED:** Yes  
**Status:** Validated

### Claim 14: RdrName Has Four Constructors
**Statement:** `data RdrName = Unqual OccName | Qual ModuleName OccName | Orig Module OccName | Exact Name`. `Unqual` = bare name, `Qual` = user-written qualified, `Orig` = compiler-generated pins to defining module, `Exact` = already resolved (built-in syntax, TH). For elab3, only Unqual and Qual are needed.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Reader.hs:173-210`
**Evidence:**
```haskell
data RdrName
  = Unqual OccName
  | Qual ModuleName OccName
  | Orig Module OccName
  | Exact Name
```
**VALIDATED:** Yes  
**Status:** Validated

### Claim 15: OccName = NameSpace + FastString
**Statement:** `data OccName = OccName { occNameSpace :: !NameSpace, occNameFS :: !FastString }`. Equality is by both fields: `s1 == s2 && sp1 == sp2`. For elab3 with single namespace, OccName simplifies to just `str`.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Types/Name/Occurrence.hs:366-372`
**Evidence:**
```haskell
data OccName = OccName { occNameSpace :: !NameSpace, occNameFS :: !FastString }
instance Eq OccName where
    (OccName sp1 s1) == (OccName sp2 s2) = s1 == s2 && sp1 == sp2
```
**VALIDATED:** Yes  
**Status:** Validated

## Open Questions
- [ ] What is `Parent` used for beyond record fields and children lookup?
- [ ] Does elab3 need `ImpItemSpec` or just `ImpDeclSpec`?
- [ ] Should elab3's Cons be used for the bag (O(n) merge) or should we add a TwoBags-like node?

## Related Topics
- [analysis/INTERACTIVE_CONTEXT_EXPLORATION.md](INTERACTIVE_CONTEXT_EXPLORATION.md) — ic_tythings, interactive module storage
