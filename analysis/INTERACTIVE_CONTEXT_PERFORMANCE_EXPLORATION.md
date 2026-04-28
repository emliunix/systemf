# InteractiveContext Performance Characteristics

**Status:** Validated  
**Last Updated:** 2024-03-28  
**Central Question:** What are the performance characteristics of GHC's interactive context operations?

## Summary

GHC's `InteractiveContext` maintains a cache of global reader environment (`ic_gre_cache`) that maps names to their definitions. Despite unbounded growth of `ic_tythings` (which accumulates all prompt definitions including shadowed ones), the performance of cache operations remains constant over long REPL sessions.

The key insight is that GHC uses **incremental extension** for normal REPL inputs and an **optimization via `igre_prompt_env`** for import changes. This ensures that cache operation complexity depends only on the number of *visible* (unshadowed) names and new definitions, not the total accumulated history.

## Claims

### Claim 1: ic_gre_cache is Extended Incrementally (NOT Rebuilt)

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:418-419`

On normal REPL input, `ic_gre_cache` is **extended incrementally**, not rebuilt from scratch:

```haskell
extendInteractiveContext ictxt new_tythings ... =
  ictxt { ...
        , ic_gre_cache = ic_gre_cache ictxt `icExtendIcGblRdrEnv` new_tythings
          -- ^ INCREMENTAL extension, not rebuild!
        }
```

The function `icExtendIcGblRdrEnv` (lines 448-455) extends both the full environment and the prompt-only environment with just the new TyThings:

```haskell
icExtendIcGblRdrEnv :: IcGlobalRdrEnv -> [TyThing] -> IcGlobalRdrEnv
icExtendIcGblRdrEnv igre tythings = IcGlobalRdrEnv
    { igre_env        = icExtendGblRdrEnv False (igre_env igre)        tythings
    , igre_prompt_env = icExtendGblRdrEnv True  (igre_prompt_env igre) tythings
    }
```

---

### Claim 2: Incremental Extension is O(|new_tythings|)

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:467-492`

The incremental extension iterates only over the NEW tythings:

```haskell
icExtendGblRdrEnv :: Bool -> GlobalRdrEnv -> [TyThing] -> GlobalRdrEnv
icExtendGblRdrEnv drop_only_qualified env tythings
  = foldr add env tythings  -- Only folds over NEW tythings!
  where
    add thing env = foldl' extendGlobalRdrEnv env1 new_gres
      where
        new_gres = tyThingLocalGREs thing  -- Extract GREs from thing
        env1     = shadowNames drop_only_qualified env $ mkGlobalRdrEnv new_gres
```

**Complexity:** O(|new_tythings| × k) where k is the average number of GREs per TyThing. This is **constant per REPL input** - it does NOT depend on the size of `ic_tythings`.

---

### Claim 3: Full Rebuild Only Happens on Import Changes

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Eval.hs:817-830`

Full rebuild via `replaceImportEnv` is only triggered by `setContext`, which is called when the user changes imports (e.g., `:m +Data.Map`):

```haskell
setContext :: GhcMonad m => [InteractiveImport] -> m ()
setContext imports = do
   ...
   let !final_gre_cache = ic_gre_cache old_ic `replaceImportEnv` all_env
   --                           ^ Only happens on import changes!
```

**Frequency:** Only when imports change, NOT on every REPL statement.

---

### Claim 4: The Key Optimization - igre_prompt_env

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:231-262` (Note [icReaderEnv recalculation])

GHC developers explicitly designed around this problem. The `IcGlobalRdrEnv` has TWO fields:

```haskell
data IcGlobalRdrEnv = IcGlobalRdrEnv
  { igre_env :: !GlobalRdrEnv        -- Full env (imports + prompt defs)
  , igre_prompt_env :: !GlobalRdrEnv  -- ONLY prompt defs (no imports)
  }
```

The explicit purpose of `igre_prompt_env` (from Note [icReaderEnv recalculation]):

> "It would be correct to re-construct the env from scratch based on `ic_tythings`, but that'd be quite expensive if there are many entries in `ic_tythings` that shadow each other."
>
> "Therefore we keep around a `GlobalRdrEnv` in `igre_prompt_env` that contains _just_ the things defined at the prompt..."

**Key insight:** When imports change, `replaceImportEnv` only needs to shadow the visible prompt definitions (in `igre_prompt_env`), NOT all of `ic_tythings`.

---

### Claim 5: replaceImportEnv Complexity

**Status:** Validated  
**Source:** `compiler/GHC/Runtime/Context.hs:459-463`

```haskell
replaceImportEnv :: IcGlobalRdrEnv -> GlobalRdrEnv -> IcGlobalRdrEnv
replaceImportEnv igre import_env = igre { igre_env = new_env }
  where
    import_env_shadowed = shadowNames False import_env (igre_prompt_env igre)
    new_env = import_env_shadowed `plusGlobalRdrEnv` igre_prompt_env igre
```

The `shadowNames` function (from `compiler/GHC/Types/Name/Reader.hs:1778-1810`) processes:
- The `import_env` (size proportional to imports)
- The `igre_prompt_env` (size proportional to *visible* prompt definitions)

**Complexity:** O(|import_env| + |igre_prompt_env|)

**Critical:** `igre_prompt_env` contains only the visible (unshadowed) names! Shadowed names in `ic_tythings` do NOT appear in `igre_prompt_env`.

---

## Complexity Analysis

| Operation | Trigger | Complexity | Depends on ic_tythings? |
|-----------|---------|------------|------------------------|
| Incremental extension | Every REPL input | O(\|new_tythings\|) | NO |
| Full rebuild (`replaceImportEnv`) | Import changes only | O(\|imports\| + \|visible_names\|) | NO |

### Performance Implications

1. **Normal REPL operation:** Each new binding adds constant overhead proportional to the number of new definitions, independent of session history.

2. **Import changes:** Cost depends on the number of visible names and imports, NOT the accumulated shadowed definitions.

3. **Long-running sessions:** Do NOT experience degradation in `ic_gre_cache` operations. The cost per operation remains constant regardless of how many shadowed bindings have accumulated.

4. **Memory vs. Time tradeoff:** While `ic_tythings` grows unboundedly (memory cost), the time cost of cache operations is bounded by the visible set size.

### Source Reference Table

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| InteractiveContext | GHC/Runtime/Context.hs | 265-337 | Data structure with ic_gre_cache |
| extendInteractiveContext | GHC/Runtime/Context.hs | 408-426 | Incremental extension |
| icExtendIcGblRdrEnv | GHC/Runtime/Context.hs | 448-455 | Dual-env extension |
| icExtendGblRdrEnv | GHC/Runtime/Context.hs | 467-492 | GRE creation and shadowing |
| replaceImportEnv | GHC/Runtime/Context.hs | 459-463 | Import change handling |
| setContext | GHC/Runtime/Eval.hs | 817-830 | Import change trigger |
| shadowNames | GHC/Types/Name/Reader.hs | 1778-1810 | Shadowing implementation |
| Note [icReaderEnv recalculation] | GHC/Runtime/Context.hs | 231-262 | Optimization rationale |

## Conclusion

**The unbounded growth of `ic_tythings` does NOT create performance degradation for `ic_gre_cache` operations.** GHC's design uses:

1. **Incremental extension** for normal REPL inputs (O(|new|) per input)
2. **igre_prompt_env optimization** to avoid processing shadowed entries during import changes
3. **Bounded rebuild cost** proportional to visible names, not total history

The memory cost of unbounded `ic_tythings` growth is real, but the time complexity of cache operations remains constant over long REPL sessions.

## Related Topics

- Shadowing behavior in `ic_tythings` accumulation
- Memory usage patterns in long-running GHCi sessions
- Global Reader Environment (GRE) architecture
- Name resolution in interactive contexts
- `:m` and `:load` command implementation
