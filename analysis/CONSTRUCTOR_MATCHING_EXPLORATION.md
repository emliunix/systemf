# HsToCore Constructor Pattern Matching

**Status:** Validated
**Last Updated:** 2026-04-14
**Central Question:** How does GHC desugar constructor pattern matching, including sub-grouping by record field order and the transformation from constructor patterns to case alternatives?

## Summary

After `match` groups equations by `PatGroup` (`PgCon`), the `match_group` function in `Match.hs` calls `subGroupUniq` to further divide the broad constructor group into subgroups by specific `ConLike`. Only then does `matchConFamily` in `Match/Constructor.hs` generate the actual case alternatives. It implements the "do-it-right" approach: generate alternatives only for constructors actually used, and add a `DEFAULT` alternative only when the match is non-exhaustive.

For each constructor, `matchOneConLike` further sub-groups equations by whether their record fields appear in the same order (see `compatible_pats`). This is necessary because record patterns like `T { y=True, x=False }` and `T { x=True, y=False }` must match fields in different orders. Positional patterns (`T a b`) are always compatible with each other.

The core transformation decomposes each `ConPat` into its sub-patterns via `shift`, which prepends the constructor's argument patterns to `eqn_rest` using `prependPats`. Then `match` is called recursively on the expanded equation list.

## Scope

**IN:**
- `matchConFamily` and `matchOneConLike`
- `match_group` and `subGroupUniq` constructor-level subgrouping
- `compatible_pats` and record pattern sub-grouping
- `shift` and equation decomposition
- `select_arg_vars` and field reordering
- `conArgPats` and argument pattern extraction

**OUT:**
- Pattern synonym matching details (covered by `matchPatSyn`, but not deeply)
- Boxer/unboxing logic for constructor arguments
- Pattern coverage checking

## Entry Points

- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:226-240` — `match_group` and the `PgCon` branch
- `upstream/ghc/compiler/GHC/HsToCore/Match.hs:1055-1072` — `subGroup` and `subGroupUniq`
- `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:94-107` — `matchConFamily`
- `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:128-192` — `matchOneConLike`
- `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:229-235` — `compatible_pats`
- `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:255-266` — `conArgPats`
- `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:213-226` — `select_arg_vars`

## Claims

### Claim 1: `match_group` Subgroups `PgCon` Equations by Specific Constructor Before Calling `matchConFamily`

**Statement:** When `match_group` processes a broad `PgCon` group (which may contain equations for multiple different constructors), it calls `subGroupUniq` to further divide the equations by their specific `ConLike`. This produces `NonEmpty (NonEmpty EquationInfoNE)`, where each inner group contains only equations for a single constructor, which is exactly what `matchConFamily` expects.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:226-240`

**Evidence:**
```haskell
match_group eqns@((group,_) :| _)
    = case group of
        PgCon {}  -> matchConFamily  vars ty (ne $ subGroupUniq [(c,e) | (PgCon c, e) <- eqns'])
  where eqns' = NE.toList eqns
        ne l = case NE.nonEmpty l of
          Just nel -> nel
          Nothing -> pprPanic "match match_group" $ text "Empty result should be impossible since input was non-empty"
```

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match.hs:1055-1072`

**Evidence:**
```haskell
subGroup :: (m -> [NonEmpty EquationInfo]) -> m -> (a -> m -> Maybe (NonEmpty EquationInfo)) -> (a -> NonEmpty EquationInfo -> m -> m) -> [(a, EquationInfo)] -> [NonEmpty EquationInfo]
subGroup elems empty lookup insert group
    = fmap NE.reverse $ elems $ foldl' accumulate empty group
  where
    accumulate pg_map (pg, eqn)
      = case lookup pg pg_map of
          Just eqns -> insert pg (NE.cons eqn eqns) pg_map
          Nothing   -> insert pg [eqn] pg_map
```

**Status:** Validated
**Confidence:** High
**Notes:** This bridges the gap between the broad `PatGroup`-level grouping performed by `match`/`match_groups` and the per-constructor alternative generation performed by `matchConFamily`.

---

### Claim 2: matchConFamily Generates One Alternative Per Constructor Group

**Statement:** `matchConFamily` takes groups of equations that share the same constructor and produces one `MatchResult CoreExpr` representing a case expression with alternatives for each constructor group.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:94-107`

**Evidence:**
```haskell
matchConFamily (var :| vars) ty groups
  = do let mult = idMult var
       alts <- mapM (fmap toRealAlt . matchOneConLike vars ty mult) groups
       return (mkCoAlgCaseMatchResult var ty alts)
```

**Status:** Validated
**Confidence:** High
**Notes:** `groups` is already a `NonEmpty (NonEmpty EquationInfoNE)` where each inner group is for a single constructor. `mkCoAlgCaseMatchResult` handles exhaustiveness checking and `DEFAULT` insertion.

---

### Claim 3: Record Patterns Are Sub-Grouped by Field Order

**Statement:** Within a single constructor group, equations are further sub-grouped by `compatible_pats` based on whether record patterns mention the same fields in the same order.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:183-185`

**Evidence:**
```haskell
let groups :: NonEmpty (NonEmpty (ConArgPats, EquationInfoNE))
      groups = NE.groupBy1 compatible_pats
             $ fmap (\eqn -> (con_pat_args (firstPat eqn), eqn)) (eqn1 :| eqns)
```

**Status:** Validated
**Confidence:** High
**Notes:** This is required because `f (T { y=True, x=False }) = ...` and `f (T { x=True, y=False }) = ...` must match fields in different orders (see `Note [Record patterns]`).

---

### Claim 4: compatible_pats Treats Empty Record Patterns as Wildcards

**Statement:** `compatible_pats` treats `C {}` as compatible with any other pattern because `C {}` is semantically equivalent to `C _ _` and does not impose any field ordering constraints.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:232-235`

**Evidence:**
```haskell
compatible_pats (RecCon flds1, _) (RecCon flds2, _) = same_fields flds1 flds2
compatible_pats (RecCon flds1, _) _                 = null (rec_flds flds1)
compatible_pats _                 (RecCon flds2, _) = null (rec_flds flds2)
compatible_pats _                 _                 = True -- Prefix or infix con
```

**Status:** Validated
**Confidence:** High
**Notes:** `null (rec_flds flds)` detects `C {}`. Positional and infix patterns are always compatible with each other (`True`).

---

### Claim 5: shift Decomposes ConPat into Sub-Patterns via prependPats

**Statement:** The local `shift` function in `matchOneConLike` extracts the sub-patterns from a `ConPat` and prepends them to the equation's remaining patterns using `prependPats`, producing a new equation ready for recursive matching.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:155-168`

**Evidence:**
```haskell
shift (_, EqnMatch {
        eqn_pat = L _ (ConPat
                      { pat_args = args
                      , pat_con_ext = ConPatTc
                        { cpt_tvs = tvs
                        , cpt_dicts = ds
                        , cpt_binds = bind }})
      , eqn_rest = rest })
  = do dsTcEvBinds bind $ \ds_bind ->
       return ( wrapBinds (tvs `zip` tvs1)
              . wrapBinds (ds  `zip` dicts1)
              . mkCoreLets ds_bind
              , prependPats (conArgPats val_arg_tys args) rest )
```

**Status:** Validated
**Confidence:** High
**Notes:** `shift` also handles type variable and dictionary bindings via `wrapBinds` and evidence bindings via `mkCoreLets ds_bind`. The returned `DsWrapper` is composed with the recursive match result.

---

### Claim 6: select_arg_vars Reorders Variables for Record Patterns

**Statement:** When a sub-group uses record patterns, `select_arg_vars` reorders the freshly generated argument variables to match the field order specified by that sub-group's patterns, rather than the data constructor's declaration order.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:213-226`

**Evidence:**
```haskell
select_arg_vars arg_vars ((arg_pats, _) :| _)
  | RecCon flds <- arg_pats
  , let rpats = rec_flds flds
  , not (null rpats)
  = assertPpr (fields1 `equalLength` arg_vars)
              (ppr con1 $$ ppr fields1 $$ ppr arg_vars) $
    map lookup_fld rpats
  | otherwise
  = arg_vars
  where
    fld_var_env = mkNameEnv $ zipEqual fields1 arg_vars
    lookup_fld (L _ rpat) = lookupNameEnv_NF fld_var_env
                                        (idName (hsRecFieldId rpat))
```

**Status:** Validated
**Confidence:** High
**Notes:** For positional patterns, `arg_vars` (in declaration order) is returned unchanged. For record patterns, variables are looked up by field name to match the user's field order.

---

### Claim 7: conArgPats Handles Empty Record Patterns as All Wildcards

**Statement:** `conArgPats` maps an empty record pattern `C {}` to a list of `WildPat`s, one for each constructor argument.

**Source:** `upstream/ghc/compiler/GHC/HsToCore/Match/Constructor.hs:262-266`

**Evidence:**
```haskell
conArgPats  arg_tys (RecCon (HsRecFields { rec_flds = rpats }))
  | null rpats = map (noLocA . WildPat . scaledThing) arg_tys
  | otherwise  = map (hfbRHS . unLoc) rpats
```

**Status:** Validated
**Confidence:** High
**Notes:** This is why `C {}` is compatible with all other patterns: it expands to `n` wildcards, just like a positional pattern.

---

## Related Topics

- [EQUATION_GROUPING_EXPLORATION.md](EQUATION_GROUPING_EXPLORATION.md) — The broader `PatGroup` classification and `match` function
- [PGANY_AND_PATCO_EXPLORATION.md](PGANY_AND_PATCO_EXPLORATION.md) — How non-constructor patterns (variables, coercions, lazy patterns) are handled
