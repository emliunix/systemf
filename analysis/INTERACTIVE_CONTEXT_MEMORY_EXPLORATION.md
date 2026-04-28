# InteractiveContext Memory Behavior

**Status:** Validated  
**Last Updated:** 2024-03-28  
**Central Question:** How does GHC handle memory in interactive contexts?

---

## Summary

GHC's `InteractiveContext.ic_tythings` grows **unboundedly** with shadowed REPL bindings. There is **no compaction mechanism** for removing shadowed entries.

### Key Findings

1. **List prepend semantics**: New bindings are always prepended with `new_tythings ++ ic_tythings ictxt`
2. **No removal code**: There is no `filterTyThings` or equivalent to remove shadowed bindings
3. **Explicit acknowledgment**: GHC developers acknowledge "many entries in ic_tythings that shadow each other" as expensive
4. **Display-only filtering**: `icInScopeTTs` filters for display but does not modify the underlying list
5. **Instance-only override**: Only class instances have override logic; TyThings do not

---

## Claims

### Claim 1: ic_tythings Uses Simple List Prepend Semantics

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:289-294, 418, 439`

New TyThings are always prepended to the front of `ic_tythings`. Shadowed bindings are never removed from the underlying list.

```haskell
-- Field definition (lines 289-294)
ic_tythings   :: [TyThing],
    -- ^ TyThings defined by the user, in reverse order of
    -- definition (ie most recent at the front).

-- Main extension function (line 418)
, ic_tythings   = new_tythings ++ ic_tythings ictxt
--                     ^^^^^^^^^^^^^^^^^^^^^^^^
--                     Old items preserved!

-- Specialized extension (line 439)
, ic_tythings   = new_tythings ++ ic_tythings ictxt
```

---

### Claim 2: Shadowed Bindings Accumulate (Explicitly Acknowledged)

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:231-262`

GHC developers explicitly acknowledge that `ic_tythings` can contain "many entries that shadow each other" and that this is expensive to process.

```haskell
-- Note [icReaderEnv recalculation]
-- ...
-- It would be correct to re-construct the env from scratch based on
-- `ic_tythings`, but that'd be quite expensive if there are many entries in
-- `ic_tythings` that shadow each other.
--   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
--   EXPLICIT ACKNOWLEDGMENT: Shadowed entries accumulate in ic_tythings!
```

---

### Claim 3: Display-Level Filtering Only - No Actual Removal

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:389-397`

The only "filtering" of shadowed bindings is for display purposes (`icInScopeTTs`). Shadowed bindings remain in the underlying `ic_tythings` list.

```haskell
-- | This function returns the list of visible TyThings (useful for
-- e.g. showBindings).
--
-- It picks only those TyThings that are not shadowed by later definitions on the interpreter,
-- to not clutter :showBindings with shadowed ids, which would show up as Ghci9.foo.
icInScopeTTs :: InteractiveContext -> [TyThing]
icInScopeTTs ictxt = filter in_scope_unqualified (ic_tythings ictxt)
```

---

### Claim 4: Only Class Instances Have Override Logic

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:420-431`

The ONLY place with actual removal/compaction logic is for class instances (not TyThings). Family instances are explicitly NOT shadowed.

```haskell
, ic_instances  = ( new_cls_insts `unionInstEnv` old_cls_insts
                  , new_fam_insts ++ fam_insts )
                  -- we don't shadow old family instances (#7102),
                  -- so don't need to remove them here
  where
    -- Discard old instances that have been fully overridden
    -- See Note [Override identical instances in GHCi]
    (cls_insts, fam_insts) = ic_instances ictxt
    old_cls_insts = filterInstEnv (\i -> not $ anyInstEnv (identicalClsInstHead i) new_cls_insts) cls_insts
    --              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    --              ONLY class instances have override logic!
```

---

### Claim 5: Debugger Resume Restores Saved State (Not Compaction)

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Eval.hs:422-424`

The only code that "removes" from `ic_tythings` is the debugger resume mechanism, which restores a previously saved state - this is not compaction.

```haskell
resumeExec :: GhcMonad m => SingleStep -> Maybe Int -> m ExecResult
resumeExec step mbCnt = do
   ...
   (r:rs) -> do
      -- unbind the temporary locals by restoring the TypeEnv from
      -- before the breakpoint, and drop this Resume from the InteractiveContext.
      let (resume_tmp_te,resume_gre_cache) = resumeBindings r
          ic' = ic { ic_tythings = resume_tmp_te,
                     --               ^^^^^^^^^^^^^^
                     --               Restores SAVED state, not compaction
                     ic_gre_cache = resume_gre_cache,
                     ic_resume   = rs }
```

---

### Claim 6: Shadowing Affects GlobalRdrEnv, Not ic_tythings Storage

**Status:** Validated  
**Source:** `compiler/GHC/Types/Name/Reader.hs:1689-1776`

Shadowing affects the `GlobalRdrEnv` (name resolution), NOT the underlying `ic_tythings` storage. Both bindings exist; only visibility changes.

```haskell
{- Note [GlobalRdrEnv shadowing]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
...
   ghci> M.x           -- M.x is still in scope!
                       -- ^^^^^^^^^^^^^^^^^^^^^
                       -- Old binding STILL EXISTS!
...
    So when we add `x = True` we must not delete the `M.x` from the
    GlobalRdrEnv; rather we just want to make it "qualified only"
-}
```

Key insight: Shadowing makes old bindings "qualified only" - they STILL EXIST in the environment, just with reduced visibility.

---

### Claim 7: Complete List of ic_tythings Modification Sites

**Status:** Validated  
**Source:** Grep analysis of GHC codebase

There are exactly **5 places** in the codebase that modify `ic_tythings`. All are either prepend operations or state restoration - none remove shadowed bindings.

| File | Line | Operation | Type |
|------|------|-----------|------|
| Context.hs | 363 | `ic_tythings = []` | Initialization (empty list) |
| Context.hs | 418 | `new_tythings ++ ic_tythings ictxt` | **PREPEND** |
| Context.hs | 439 | `new_tythings ++ ic_tythings ictxt` | **PREPEND** |
| Context.hs | 497 | `map subst_ty tts` | Transform (substitution) |
| Eval.hs | 422 | `ic_tythings = resume_tmp_te` | **State restoration** |

All verified sites are either:
- Prepend operations (418, 439)
- State restoration (422)
- Initialization (363)
- Type-preserving transform (497 - substitution does not remove elements)

**None remove shadowed bindings.**

---

## Related Topics

- [INTERACTIVE_CONTEXT_HPT_ARCHITECTURE.md](./INTERACTIVE_CONTEXT_HPT_ARCHITECTURE.md) - InteractiveContext and HPT architecture
- [VALBINDS_EXPLORATION.md](./VALBINDS_EXPLORATION.md) - Value bindings in GHCi

### Related Notes from GHC Codebase

- `Note [icReaderEnv recalculation]` - Explains the optimization for handling many shadowed entries
- `Note [Interactively-bound Ids in GHCi]` - Explains why Ids have External Names
- `Note [Override identical instances in GHCi]` - Shows the pattern that COULD be applied to TyThings

---

## Source Location Reference

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| ic_tythings definition | GHC/Runtime/Context.hs | 289-294 | Field definition and comment |
| extendInteractiveContext | GHC/Runtime/Context.hs | 408-426 | Main prepend operation |
| extendInteractiveContextWithIds | GHC/Runtime/Context.hs | 433-443 | Specialized prepend |
| icInScopeTTs | GHC/Runtime/Context.hs | 389-397 | Display filtering |
| Note [icReaderEnv recalculation] | GHC/Runtime/Context.hs | 231-262 | Shadowing cost acknowledgment |
| resumeExec | GHC/Runtime/Eval.hs | 422-424 | State restoration (not compaction) |
| Note [GlobalRdrEnv shadowing] | GHC/Types/Name/Reader.hs | 1689-1776 | Shadowing semantics |
| runTcInteractive | GHC/Tc/Module.hs | 2110-2185 | Uses ic_tythings for typechecking |

---

## Memory Impact

For a long-running GHCi session where the user repeatedly redefines the same names (e.g., iterating on a function definition):

```haskell
ghci> f x = x + 1
ghci> f x = x + 2  -- Shadows first f
ghci> f x = x + 3  -- Shadows second f
-- ... 1000 more iterations ...
```

All 1000+ versions of `f` remain in `ic_tythings`, each consuming memory for:
- The TyThing wrapper
- The underlying Id with its type
- The name and unique

While the `ic_gre_cache` maintains efficient lookup via the `igre_prompt_env` optimization, the underlying storage grows without bound.

