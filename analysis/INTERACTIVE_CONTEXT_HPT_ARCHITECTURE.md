# InteractiveContext and HPT Architecture

**Validation Status:** ✅ Source code locations verified against GHC compiler (Mar 28, 2026)

## Overview

This document captures the architecture of GHCi's interactive context and how it bridges to the standard type-checking pipeline.

## Core Architecture

### The Two-Layer Design

```
InteractiveContext (PERSISTENT - Session-wide)
├── ic_imports :: [InteractiveImport]     - User-specified imports
├── ic_tythings :: [TyThing]              - Previous REPL definitions
├── ic_gre_cache :: IcGlobalRdrEnv        - Combined name resolution env
└── ...

HomePackageTable (HPT - STORAGE)
├── Module "Ghci1" → HomeModInfo
│   ├── hm_iface :: ModIface              - Interface
│   ├── hm_details :: ModDetails          - Type env (LAZY!)
│   └── hm_linkable :: HomeModLinkable    - Bytecode
└── Module "Prelude" → HomeModInfo
    └── ...
```

## InteractiveContext Fields

### ic_imports vs ic_tythings

**File:** `compiler/GHC/Runtime/Context.hs:278-295`

```haskell
ic_imports :: [InteractiveImport],
    -- ^ The GHCi top-level scope (icReaderEnv) is extended with
    -- these imports
    --
    -- This field is only stored here so that the client
    -- can retrieve it with GHC.getContext. GHC itself doesn't
    -- use it, but does reset it to empty sometimes.

ic_tythings :: [TyThing],
    -- ^ TyThings defined by the user, in reverse order of
    -- definition (ie most recent at the front).
    -- Also used in GHC.Tc.Module.runTcInteractive to fill the type
    -- checker environment.
```

**Key Distinction:**
- `ic_imports` = Equivalent to `import` statements in source files
- `ic_tythings` = Equivalent to top-level definitions in source files
- Together they form the complete "import spec" for the REPL

### ic_gre_cache Structure

**File:** `compiler/GHC/Runtime/Context.hs:296-306`

```haskell
ic_gre_cache :: IcGlobalRdrEnv,
    -- ^ Essentially the cached 'GlobalRdrEnv'.
    --
    -- The GlobalRdrEnv contains everything in scope at the command
    -- line, both imported and everything in ic_tythings, with the
    -- correct shadowing.
    --
    -- The IcGlobalRdrEnv contains extra data to allow efficient
    -- recalculation when the set of imports change.
    -- See Note [icReaderEnv recalculation]
```

**File:** `compiler/GHC/Runtime/Eval/Types.hs:163-168`

```haskell
data IcGlobalRdrEnv = IcGlobalRdrEnv
  { igre_env :: !GlobalRdrEnv
    -- ^ The final environment (imports + prompt defs, with shadowing)
  , igre_prompt_env :: !GlobalRdrEnv
    -- ^ Just the things defined at the prompt (excluding imports!)
    -- Used for efficient recalculation when imports change
  }
```

## The Bridge: runTcInteractive

**File:** `compiler/GHC/Tc/Module.hs:2110-2160`

```haskell
runTcInteractive :: HscEnv -> TcRn a -> IO (Messages TcRnMessage, Maybe a)
runTcInteractive hsc_env thing_inside
  = initTcInteractive hsc_env $ withTcPlugins hsc_env $
    withDefaultingPlugins hsc_env $ withHoleFitPlugins hsc_env $
    withInteractiveModuleNode hsc_env $
    do { ...
       ; let upd_envs (gbl_env, lcl_env) = (gbl_env', lcl_env')
               where
                 gbl_env' = gbl_env
                   { tcg_rdr_env      = icReaderEnv icxt
                   , tcg_type_env     = type_env
                   , tcg_inst_env     = tcg_inst_env gbl_env `unionInstEnv` ic_insts `unionInstEnv` home_insts
                   , tcg_fam_inst_env = ...
                   , tcg_fix_env      = ic_fix_env icxt
                   , tcg_default      = ic_default icxt
                   , tcg_imports      = imports }
       ; updEnvs upd_envs thing_inside }
```

**Key:** `tcg_rdr_env = icReaderEnv icxt` - Copies IC's name environment to standard TcGblEnv

## The Pointer Chain: Name → TyThing

### Complete Lookup Flow

```
Typechecking uses imported name "Data.Maybe.fromJust"
    ↓
tcLookupGlobal (Name "fromJust" Unique 123456)
    ↓
Not in tcg_type_env (local environment)
    ↓
tcLookupImported_maybe
    ↓
lookupType hsc_env name
    ↓
HUG.lookupHugByModule "Data.Maybe" hpt
    ↓
Just hm :: HomeModInfo
    ↓
lookupNameEnv (md_types (hm_details hm)) name
    ↓
Just (AnId fromJustId)  ← TyThing found!
```

### Why hm_details Is Lazy

**File:** `compiler/GHC/Unit/Home/ModInfo.hs:28`

```haskell
hm_details  :: ModDetails      -- ^ This field is LAZY because a ModDetails
                                --   is constructed by knot tying.
```

**File:** `compiler/GHC/IfaceToCore.hs:225-235`

```haskell
-- Typecheck the decls. This is done lazily, so that the knot-tying
-- within this single module works out right. It's the callers
-- job to make sure the knot is tied.

; names_w_things <- tcIfaceDecls ignore_prags (mi_decls iface)
; let type_env = mkNameEnv names_w_things
```

**File:** `compiler/GHC/Tc/Utils/Monad.hs:2475-2495`

```haskell
forkM :: SDoc -> IfL a -> IfL a
forkM doc thing_inside
 = unsafeInterleaveM $ uninterruptibleMaskM_ $  -- ← Creates thunk!
    do { ...
       ; thing_inside  -- Deferred until forced!
       }
```

**Key:** TyThings are thunks until first lookup forces deserialization!

### ModDetails Structure

**File:** `compiler/GHC/Unit/Module/ModDetails.hs:20-43`

```haskell
data ModDetails = ModDetails
   { md_exports   :: [AvailInfo]     -- What's exported
   , md_types     :: !TypeEnv        -- NameEnv TyThing (THE KEY FIELD!)
   , md_defaults  :: !DefaultEnv     -- Default declarations
   , md_insts     :: InstEnv         -- Type class instances
   , md_fam_insts :: ![FamInst]      -- Family instances
   , md_rules     :: ![CoreRule]     -- Rewrite rules
   , md_anns      :: ![Annotation]   -- Annotations
   , md_complete_matches :: CompleteMatches
   }
```

## HomeModInfo Contents

**File:** `compiler/GHC/Unit/Home/ModInfo.hs:23-38`

```haskell
data HomeModInfo = HomeModInfo
   { hm_iface    :: !ModIface       -- ^ Interface file
   , hm_details  :: ModDetails      -- ^ Extra info (LAZY!)
   , hm_linkable :: !HomeModLinkable  -- ^ Compiled code
   }

data HomeModLinkable = HomeModLinkable 
    { homeMod_bytecode :: !(Maybe Linkable)  -- For GHCi
    , homeMod_object   :: !(Maybe Linkable)  -- For compilation
    }
```

**For imported modules:**
- `hm_iface` populated from .hi file (strict)
- `hm_details` lazy thunk (deserialized on demand)
- `hm_linkable` usually Nothing (bytecode not needed)

**For interactive modules (GhciN):**
- `hm_iface` generated (not from file)
- `hm_details` strict (created during typechecking)
- `hm_linkable` always has bytecode (for execution)

## Name Resolution Sources

### Two Sources in IC

| Source | Equivalent To | Content |
|--------|---------------|---------|
| `ic_imports` | `import X` statements | Modules explicitly imported |
| `ic_tythings` | Top-level definitions | All previous REPL inputs |

### The Combined View

**File:** `compiler/GHC/Runtime/Context.hs:298-301`

> "The GlobalRdrEnv contains everything in scope at the command line, both imported and everything in ic_tythings, with the correct shadowing."

```haskell
-- Merge process:
ic_gre_cache.igre_env = (imports_env) `plusGlobalRdrEnv` (prompt_env)
  where
    imports_env = from ic_imports (with ImportSpec for qualification)
    prompt_env  = from ic_tythings (gre_lcl = True)
```

## Shadowing and Recalculation

**File:** `compiler/GHC/Runtime/Context.hs:231-258` (Note [icReaderEnv recalculation])

```haskell
-- The GlobalRdrEnv describing what's in scope at the prompts consists
-- of all the imported things, followed by all the things defined on the prompt,
-- with shadowing.
--
-- Example:
--     ghci> let empty = True
--     ghci> import Data.IntMap.Strict     -- Exports 'empty'
--     ghci> empty   -- Still gets the 'empty' defined at the prompt
--     True
--
-- It would be correct to re-construct the env from scratch based on
-- `ic_tythings`, but that'd be quite expensive if there are many entries in
-- `ic_tythings` that shadow each other.
--
-- Therefore we keep around a `GlobalRdrEnv` in `igre_prompt_env` that contains
-- _just_ the things defined at the prompt, and use that in `replaceImportEnv` to
-- rebuild the full env.
```

## Differences from Batch Mode

| Aspect | Batch Mode | Interactive Mode |
|--------|-----------|------------------|
| Imports | From source `import` decls | From `ic_imports` + `ic_tythings` |
| RdrEnv construction | `rnImports` per module | Snapshot from IC via `icReaderEnv` |
| TypeEnv population | Strict during typecheck | IC tythings strict, HPT lazy |
| Module lifecycle | Compile once | Accumulate in HPT across session |

## Source Locations

| Component | File | Lines |
|-----------|------|-------|
| InteractiveContext | GHC/Runtime/Context.hs | 269-330 |
| IcGlobalRdrEnv | GHC/Runtime/Eval/Types.hs | 163-168 |
| runTcInteractive | GHC/Tc/Module.hs | 2110-2160 |
| tcRnStmt | GHC/Tc/Module.hs | 2220-2253 |
| HomeModInfo | GHC/Unit/Home/ModInfo.hs | 23-38 |
| ModDetails | GHC/Unit/Module/ModDetails.hs | 20-43 |
| lookupType | GHC/Driver/Env.hs | 331-355 |
| tcLookupGlobal | GHC/Tc/Utils/Env.hs | 246-280 |

## Key Insights

1. **IC is persistent** - maintains state across GHCi commands
2. **HPT is storage** - holds compiled code for all modules
3. **runTcInteractive is the bridge** - converts IC to standard TcGblEnv
4. **hm_details is lazy** - interface files deserialized on demand
5. **Names are the pointer** - Unique → HPT → TypeEnv → TyThing
