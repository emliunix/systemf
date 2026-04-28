# Exploration Session: Import Behavior (Duplicate Aliases)

**Date:** 2024-03-28
**Session ID:** F
**Focus:** How GHC handles duplicate import aliases and qualified imports
**Status:** Draft

## Central Question

How does GHC handle:
1. Same alias for different modules: `import qualified A as L; import qualified B as L`
2. Qualified import without `as`: `import qualified Data.List` (no alias)
3. Multiple imports of same module with different qualifiers

## Test Results

From GHCi experiments:

### Test 1: Same alias for different modules
```
import qualified Data.List as L
import qualified Data.Maybe as L
L.nub [1,2]       -- works (from Data.List)
L.isJust (Just 1) -- works (from Data.Maybe)
```
**Result:** Both work! Names union across modules.

### Test 2: Qualified import without `as`
```
import Data.List           -- unqualified
import qualified Data.List -- should be qualified only?
:show imports shows: import Data.List (no "qualified")
nub [1,2] -- still works!
```
**Result:** `qualified` without `as` doesn't restrict to qualified-only.

### Test 3: Same name collision
```
import qualified Data.List as L
import qualified Data.Maybe as L
L.null []        -- True
L.null Nothing   -- True
-- Both work, type is polymorphic: Foldable t => t a -> Bool
```
**Result:** No ambiguity error! First match wins.

## Hypothesis

This is **implementation behavior**, not design:
- `ImportSpec` uses `Bag` (multiset) - allows duplicates
- `qualSpecOK` filters by `is_as` - returns ALL matching specs
- No validation for duplicate aliases
- Union of namespaces is a side effect

## Entry Points

Check:
- `compiler/GHC/Types/Name/Reader.hs:2151` - qualSpecOK
- `compiler/GHC/Types/Name/Reader.hs:1601` - pickQualGRE  
- `compiler/GHC/Types/Name/Reader.hs:1549` - pickGREs

## Scope

- IN: ImportSpec data structure
- IN: qualSpecOK filtering logic
- IN: GRE accumulation (plusGlobalRdrEnv)
- IN: Duplicate alias handling
- OUT: Error detection logic
- OUT: Fix implementation

## Expected Findings

1. ImportSpec stored in Bag (allows duplicates)
2. qualSpecOK filters ALL matching is_as values
3. No check for duplicate aliases during import processing
4. First-match resolution (not ambiguity error)
