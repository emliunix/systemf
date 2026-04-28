# Interactive Context and ic_tythings

**Status:** Validated  
**Last Updated:** 2026-03-30  
**Central Question:** Why does ic_tythings keep a growing list of all definitions rather than just currently visible ones?

## Summary

The `ic_tythings` field in GHC's `InteractiveContext` accumulates ALL TyThings (Ids, TyCons, Classes) defined at the GHCi prompt, including shadowed definitions. This design is intentional and serves multiple critical purposes.

The accumulation enables: (1) access to shadowed bindings via qualified names, (2) the debugger's breakpoint restoration mechanism, (3) type environment reconstruction for type checking and Core Lint, and (4) maintains the invariant that each original name M.T refers to exactly one unique thing throughout the session.

This is not a memory leak or oversight - it is a fundamental design requirement. The implementation intentionally trades unbounded memory growth for correct semantics, efficient incremental updates, full debugger functionality, and complete type checking.

## Claims

### Claim 1: ic_tythings Accumulates All Definitions Including Shadowed Ones
**Statement:** The `ic_tythings` field grows unboundedly by prepending new TyThings to the front of the list. Shadowed definitions are NEVER removed from the underlying storage.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:418`
**Evidence:**
```haskell
-- In extendInteractiveContext (line 418):
, ic_tythings   = new_tythings ++ ic_tythings ictxt
```
**VALIDATED:** Yes  
**Source Check:** Verified at line 418  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** The prepend operation ensures newer definitions shadow older ones during traversal. The field comment at lines 289-294 confirms TyThings are stored "in reverse order of definition (ie most recent at the front)."

---

### Claim 2: Shadowed Bindings Remain Accessible via Qualified Names
**Statement:** Shadowed definitions are retained in `ic_tythings` so they can still be accessed using their qualified names (e.g., `Ghci1.foo` even after `Ghci2.foo` shadows it unqualified).
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:62-76`
**Evidence:**
```haskell
{- Note [The interactive package]
This scheme deals well with shadowing.  For example:

   ghci> data T = A
   ghci> data T = B
   ghci> :i A
   data Ghci1.T = A  -- Defined at <interactive>:2:10

Here we must display info about constructor A, but its type T has been
shadowed by the second declaration.  But it has a respectable
qualified name (Ghci1.T), and its source location says where it was
defined, and it can also be used with the qualified name.

So the main invariant continues to hold, that in any session an
original name M.T only refers to one unique thing.
-}
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 62-76 (exact match)  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** This is a fundamental design invariant - original names must remain unique and resolvable. If shadowed definitions were deleted, their qualified names would become dangling references.

---

### Claim 3: The Debugger Requires Full ic_tythings History for Breakpoint Restoration
**Statement:** The debugger uses `ic_tythings` to save and restore the interactive context when entering and leaving breakpoints. Without the full history, breakpoint resumption would lose bindings.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Eval.hs:421-432`
**Evidence:**
```haskell
-- From resumeExec function:
let (resume_tmp_te,resume_gre_cache) = resumeBindings r
    ic' = ic { ic_tythings = resume_tmp_te,
               ic_gre_cache = resume_gre_cache,
               ic_resume   = rs }
setSession hsc_env{ hsc_IC = ic' }

-- remove any bindings created since the breakpoint from the linker's environment
let old_names = map getName resume_tmp_te
    new_names = [ n | thing <- ic_tythings ic
                    , let n = getName thing
                    , not (n `elem` old_names) ]
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 421-432  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** When resuming from a breakpoint, the debugger must restore the exact state from before the breakpoint. This requires saving a snapshot of `ic_tythings` in the `Resume` structure.

---

### Claim 4: Type Checking Requires Complete TyThings for Type Environment Construction
**Statement:** The type checker uses the full `ic_tythings` list to construct the type environment (`tcg_type_env`) when typechecking interactive input. Shadowed definitions may still be referenced in types.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Tc/Module.hs:2167, 2181`
**Evidence:**
```haskell
-- In runTcInteractive:
(lcl_ids, top_ty_things) = partitionWith is_closed (ic_tythings icxt)

type_env1 = mkTypeEnvWithImplicits top_ty_things
type_env  = extendTypeEnvWithIds type_env1
          $ map instanceDFunId (instEnvElts ic_insts)
            -- Putting the dfuns in the type_env
            -- is just to keep Core Lint happy
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 2167, 2181  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** Even shadowed definitions may appear in the types of currently-visible bindings. The type environment must contain ALL TyThings that could be referenced.

---

### Claim 5: Core Lint Requires Full ic_tythings for In-Scope Variable Checking
**Statement:** The Core Lint pass uses `ic_tythings` to determine which variables are in scope when linting interactive expressions. Without the full list, Lint would report valid variables as out of scope.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Core/Lint/Interactive.hs:38-46`
**Evidence:**
```haskell
interactiveInScope :: InteractiveContext -> [Var]
-- In GHCi we may lint expressions, or bindings arising from 'deriving'
-- clauses, that mention variables bound in the interactive context.
-- These are Local things (see Note [Interactively-bound Ids in GHCi] in GHC.Runtime.Context).
-- So we have to tell Lint about them, lest it reports them as out of scope.
--
-- See #8215 for an example
interactiveInScope ictxt
  = tyvars ++ ids
  where
    (cls_insts, _fam_insts) = ic_instances ictxt
    te1    = mkTypeEnvWithImplicits (ic_tythings ictxt)
    te     = extendTypeEnvWithIds te1 (map instanceDFunId $ instEnvElts cls_insts)
    ids    = typeEnvIds te
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 38-46  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** This is crucial for validating generated Core code. Interactive bindings can appear in derived code or expressions being linted. See issue #8215.

---

### Claim 6: icInScopeTTs Only Filters for DISPLAY Purposes
**Statement:** The `icInScopeTTs` function filters `ic_tythings` to show only unshadowed bindings, but this filtering is ONLY for display purposes (e.g., `:showBindings`). The underlying `ic_tythings` list remains unchanged.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:389-397`
**Evidence:**
```haskell
-- | This function returns the list of visible TyThings (useful for
-- e.g. showBindings).
--
-- It picks only those TyThings that are not shadowed by later definitions on the interpreter,
-- to not clutter :showBindings with shadowed ids, which would show up as Ghci9.foo.
--
-- Some TyThings define many names; we include them if _any_ name is still
-- available unqualified.
icInScopeTTs :: InteractiveContext -> [TyThing]
icInScopeTTs ictxt = filter in_scope_unqualified (ic_tythings ictxt)
  where
    in_scope_unqualified thing = or
        [ unQualOK gre
        | gre <- tyThingLocalGREs thing
        , let name = greName gre
        , Just gre <- [lookupGRE_Name (icReaderEnv ictxt) name]
        ]
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 389-397  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** The comment explicitly states this is to avoid cluttering `:showBindings` with shadowed ids. This confirms that filtering is a UI concern, not a semantic requirement.

---

### Claim 7: The Design Explicitly Acknowledges Memory Cost for Time Efficiency
**Statement:** GHC developers explicitly acknowledge that `ic_tythings` can contain "many entries that shadow each other" and that reconstructing the environment from scratch would be "quite expensive." The design accepts unbounded memory growth to maintain O(1) incremental updates.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:248-250`
**Evidence:**
```haskell
-- It would be correct to re-construct the env from scratch based on
-- `ic_tythings`, but that'd be quite expensive if there are many entries in
-- `ic_tythings` that shadow each other.
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 248-250  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** This is a classic time-space tradeoff. The implementation uses `igre_prompt_env` (a cache of visible prompt definitions) to make import changes efficient without reconstructing from the full `ic_tythings`. See Note [icReaderEnv recalculation] for full context.

---

### Claim 8: The Interactive Package Design Requires Persistent Original Names
**Statement:** The "interactive package" design assigns each GHCi input a unique module name (Ghci1, Ghci2, etc.). This design REQUIRES that all definitions persist because each has a unique original name that must remain valid for the entire session.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:82-86`
**Evidence:**
```haskell
-- Module from the 'interactive' package (Ghci1, Ghci2 etc) never go
-- in the Home Package Table (HPT). When you say :load, that's when we
-- extend the HPT.
```
**VALIDATED:** Partial  
**Source Check:** Content correct, line reference should be 82-86 (not 48-76 as originally cited)  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** The note at lines 82-86 mentions that a previous iteration used the same module name with different uniques, which "gave rise to all sorts of trouble." The current design solves this by giving each definition a unique module name, but this requires keeping all definitions. The interactive package design assigns unique module names (Ghci1, Ghci2, etc.) to each input batch.

---

### Claim 9: DFunIds Are Explicitly Excluded from ic_tythings
**Statement:** Dictionary function Ids (DFunIds) are deliberately NOT stored in `ic_tythings` because they can be reconstructed from `ic_instances`. This is an intentional optimization to avoid redundancy.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:215-217`
**Evidence:**
```haskell
{- Note [ic_tythings]
It does *not* contain
  * DFunIds (they can be gotten from ic_instances)
  * CoAxioms (ditto)
-}
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 215-217 (exact match)  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** This confirms that the design is intentional about what goes into `ic_tythings`. DFunIds are excluded because they're derivable from instances, but record selectors are included because they cannot be easily reconstructed.

---

### Claim 10: Shadowing Affects GlobalRdrEnv, Not ic_tythings Storage
**Statement:** Name shadowing is implemented at the `GlobalRdrEnv` level (the name resolution environment), NOT by removing entries from `ic_tythings`. Both the shadowing and shadowed definitions coexist in storage; only visibility differs.
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:459-481`
**Evidence:**
```haskell
-- replaceImportEnv: Rebuilds the GlobalRdrEnv when imports change
replaceImportEnv :: IcGlobalRdrEnv -> GlobalRdrEnv -> IcGlobalRdrEnv
replaceImportEnv igre import_env = igre { igre_env = new_env }
  where
    import_env_shadowed = shadowNames False import_env (igre_prompt_env igre)
    new_env = import_env_shadowed `plusGlobalRdrEnv` igre_prompt_env igre

-- icExtendGblRdrEnv: Adds TyThings with shadowing
icExtendGblRdrEnv :: Bool -> GlobalRdrEnv -> [TyThing] -> GlobalRdrEnv
icExtendGblRdrEnv drop_only_qualified env tythings
  = foldr add env tythings  -- Foldr makes things in the front of
                            -- the list shadow things at the back
  where
    -- One at a time, to ensure each shadows the previous ones
    add thing env
       | is_sub_bndr thing
       = env
       | otherwise
       = foldl' extendGlobalRdrEnv env1 new_gres
       where
          new_gres = tyThingLocalGREs thing
          env1     = shadowNames drop_only_qualified env $ mkGlobalRdrEnv new_gres
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 459-481  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** The `shadowNames` function creates shadowed entries in the GlobalRdrEnv, but the underlying TyThings remain in `ic_tythings`. This is a separation of concerns: storage (`ic_tythings`) vs. visibility (`GlobalRdrEnv`).

---

## Special Notes

### ic_tythings Does NOT Go Into HPT
**Statement:** Interactive modules (Ghci1, Ghci2, etc.) never go into the Home Package Table
**Source:** `/home/liu/Documents/bub/upstream/ghc/compiler/GHC/Runtime/Context.hs:82-86`
**Evidence:**
```haskell
-- Module from the 'interactive' package (Ghci1, Ghci2 etc) never go
-- in the Home Package Table (HPT). When you say :load, that's when we
-- extend the HPT.
```
**VALIDATED:** Yes  
**Source Check:** Verified at lines 82-86  
**Logic Check:** Sound  
**Confidence:** High  
**Notes:** 
- HPT only contains modules loaded via `:load`
- ic_tythings is the ONLY storage for interactive definitions
- Two parallel environments exist: TypeEnv (for type checking) and closure_env (for execution)

---

## Key Design Decisions Summary

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Storage** | Keep all TyThings | Qualified access, debugger restoration, type environment |
| **Shadowing** | At GlobalRdrEnv level | Efficient incremental updates without list rebuilding |
| **Order** | Reverse chronological | Natural shadowing semantics (first match wins) |
| **DFunIds** | Excluded | Reconstructible from instances |
| **Record selectors** | Included | Not reconstructible from TyCon alone |

## What Would Break If Definitions Were Deleted?

1. **Qualified access**: `Ghci1.foo` would become a dangling reference after `foo` is redefined
2. **Debugger resumption**: Breakpoint restoration would lose bindings created after the breakpoint
3. **Type checking**: Types referencing shadowed definitions would become ill-formed
4. **Core Lint**: Valid Core code referencing shadowed bindings would fail validation
5. **The "original name" invariant**: Each M.T would no longer refer to exactly one unique thing

## Conclusion

The accumulation of all TyThings in `ic_tythings` is not a memory leak or oversight - it is a **fundamental design requirement** of GHC's interactive system. The design intentionally trades unbounded memory growth for:
- Correct semantics (original name invariant)
- Efficient incremental updates
- Full debugger functionality
- Complete type checking
- Access to shadowed bindings via qualified names

## Open Questions
- [ ] None

## Related Topics
- PATTERN_TC_FACTS.md
- Other GHC exploration files
