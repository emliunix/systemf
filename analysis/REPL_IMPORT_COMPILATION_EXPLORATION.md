# REPL Import and Compilation

**Status:** Validated  
**Last Updated:** 2024-03-28  
**Central Question:** How does GHCi handle imports and compilation?

---

## Summary

GHCi handles module imports through two distinct paths with different compilation behaviors:

| Scenario | Missing .hi Behavior | Compilation Triggered? |
|----------|---------------------|----------------------|
| `:load MyModule` (home module) | Looks for source file, compiles if needed | YES - Full downsweep/upsweep |
| `:m + MyModule` (home module) | Error: "module is not loaded" | NO - Must use `:load` first |
| `:m + Module` (package module) | Looks for .hi file in package | NO - Package must be pre-compiled |

**Key Insight:** In GHCi, the Finder looks for SOURCE files (not .hi files) for home modules. The compilation happens during `:load`, not during import processing.

---

## Critical Correction

### Multi-line Imports DO Work

The original claim that "REPL statements cannot contain import declarations" was **incorrect**.

GHCi has a **dual parsing strategy** for interactive input (`ghc/GHCi/UI.hs`, lines 1479-1506):

```haskell
-- Path 1: Statement parsing (for expressions, bindings)
if | GHC.isStmt pflags input -> do
       hsc_env <- GHC.getSession
       mb_stmt <- liftIO (runInteractiveHsc hsc_env (hscParseStmtWithLocation source line input))
       ...

   -- Path 2: Module parsing (for imports + declarations)  
   | otherwise -> do
       hsc_env <- GHC.getSession
       liftIO (hscParseModuleWithLocation hsc_env source line input) >>= \case
         HsModule { hsmodDecls = decls, hsmodImports = imports } -> do
           run_imports imports      -- <-- Imports ARE processed!
           run_decls decls
```

### How Multi-line Imports Work

1. `isStmt` (in `compiler/GHC/Parser/Utils.hs`) uses `parseStmt` which only handles `GhciLStmt` (expressions, let bindings, `<-` binds)
2. Input containing `import` fails `parseStmt`, causing `isStmt` to return False
3. When `isStmt` returns False, GHCi falls through to `hscParseModuleWithLocation`
4. `hscParseModuleWithLocation` uses `parseModule` which CAN parse imports
5. Imports are extracted via `hsmodImports` and processed via `addImportToContext`

### Working Example

```haskell
:{
import Data.List
foo = nub [1,2,1]
:}
```

**Result:** SUCCESS - The import will be processed via `addImportToContext` and `foo` will be defined.

---

## Commands and Behaviors

### :load Command (Compilation Triggered)

**File:** `compiler/GHC/Driver/Make.hs` (lines 420-446)

```haskell
load :: GhcMonad f => LoadHowMuch -> f SuccessFlag
load how_much = loadWithCache noIfaceCache mkUnknownDiagnostic how_much

loadWithCache cache diag_wrapper how_much = do
    msg <- mkBatchMsg <$> getSession
    (errs, mod_graph) <- depanalE diag_wrapper (Just msg) [] False
    success <- load' cache how_much diag_wrapper (Just msg) mod_graph
    ...
```

**Process:**
1. `depanalE` performs dependency analysis (downsweep)
2. `load'` executes the build plan (upsweep)
3. Missing modules are discovered during downsweep via `summariseModule`
4. Modules are compiled and added to HPT

### :m + Command (NO Compilation)

**File:** `compiler/GHC/Runtime/Eval.hs` (lines 817-856)

```haskell
setContext :: GhcMonad m => [InteractiveImport] -> m ()
setContext imports = do
  { hsc_env <- getSession
  ; all_env_err <- liftIO $ findGlobalRdrEnv hsc_env imports
  ; case all_env_err of
      Left (mod, err) -> liftIO $ throwGhcExceptionIO (formatError dflags mod err)
      Right all_env -> do
        { let old_ic = hsc_IC hsc_env
        ; let !final_gre_cache = ic_gre_cache old_ic `replaceImportEnv` all_env
        ; setSession hsc_env{ hsc_IC = old_ic { ic_imports = imports
                                              , ic_gre_cache = final_gre_cache }}}}
```

**Critical Insight:**
- For `IIModule` imports (`:m +`), it looks up the module in the HPT (Home Package Table)
- If not found, returns `Left "not a home module"` or similar error
- **NO compilation is triggered** - the module must already be loaded

### :load vs :m + Comparison

| Aspect | :load | :m + |
|--------|-------|------|
| Purpose | Set program targets | Add to interactive context |
| Compilation | YES - Full build | NO - Must be pre-compiled |
| Module graph | Built from scratch | Uses existing HPT |
| Error if missing | Compiles from source | "module is not loaded" |

---

## Finder Mode Logic

**File:** `compiler/GHC/Unit/Finder.hs` (lines 506-511)

```haskell
-- In compilation manager modes, we look for source files in the home
-- package because we can compile these automatically.  In one-shot
-- compilation mode we look for .hi and .hi-boot files only.
(search_dirs, exts)
     | finder_lookupHomeInterfaces fopts = (hi_dir_path, hi_exts)
     | otherwise                         = (home_path, source_exts)
```

**Configuration:** `compiler/GHC/Driver/Config/Finder.hs` (line 18)

```haskell
finder_lookupHomeInterfaces = isOneShot (ghcMode flags)
```

**Interpretation:**
- In one-shot mode (`-c`, `-S`): Look for .hi files
- In GHCi/`--make` mode: Look for source files (.hs, .lhs)

**Key Point:** GHCi **never** looks for .hi files for home modules. The Finder always looks for source files first when `finder_lookupHomeInterfaces = False` (compilation manager mode).

---

## Multi-line Input with Imports

### Parsing Flow

When you enter multi-line input with `:{ ... :}`:

1. **Input collected** - Lines between `:{` and `:`} are collected
2. **Statement check** - `isStmt` attempts to parse as `GhciLStmt`
3. **Module fallback** - If statement parse fails, falls through to module parser
4. **Import extraction** - `hsmodImports` extracts import declarations
5. **Import processing** - `addImportToContext` processes imports like `:m +`

### Code Path

**File:** `ghc/GHCi/UI.hs` (lines 1479-1506)

```haskell
run_imports :: [LImportDecl GhcPs] -> InputT GHCi ()
run_imports imports = do
  -- Processes imports via addImportToContext
  ...
```

### What Happens with Missing .hi in Multi-line Import

**Scenario:** Multi-line input imports a module with missing .hi file

```haskell
:{
import Utils
foo = Utils.helper
:}
```

Where `Utils.hi` is missing but `Utils.hs` exists.

**Result:** The import is processed via `addImportToContext`, which follows the same `:m +` path. If Utils is not already in HPT, you will get an error: "module is not loaded".

**To make this work:** First run `:load Utils` to compile it, then the multi-line import will succeed.

---

## Related Topics

- **IMPORT_REPL_INTERACTION_EXPLORATION.md** - REPL interaction deep dive
- **MISSING_HI_2024-03-28_E_VALIDATED.md** - Validated exploration session
- **INTERACTIVE_CONTEXT_HPT_ARCHITECTURE.md** - HPT architecture details

---

## Source Evidence Index

| File | Lines | Key Function/Concept |
|------|-------|---------------------|
| `GHC/Unit/Finder.hs` | 506-511 | Source vs .hi lookup logic |
| `GHC/Driver/Config/Finder.hs` | 18 | `finder_lookupHomeInterfaces` config |
| `GHC/Driver/Make.hs` | 420-446 | `load` function |
| `GHC/Driver/Downsweep.hs` | 254-333 | `downsweepInteractiveImports` |
| `GHC/Driver/Downsweep.hs` | 1303-1410 | `summariseModule` |
| `GHC/Runtime/Eval.hs` | 817-856 | `setContext` |
| `GHC/Runtime/Eval.hs` | 858-869 | `mkTopLevEnv` (HPT lookup) |
| `GHC/Iface/Load.hs` | 290-326 | `loadSrcInterface` |
| `ghc/GHCi/UI.hs` | 1479-1506 | `runStmt` - dual parsing path |
| `ghc/GHCi/UI.hs` | 2965-3044 | `:module` command handling |
