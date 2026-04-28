# Import Alias Behavior

**Status:** Validated  
**Last Updated:** 2024-03-28  
**Central Question:** How does GHC handle duplicate import aliases?

## Summary

GHC allows multiple modules to be imported with the same qualified alias. When the same alias is used for different modules, GHC unions their namespaces rather than reporting an error. This behavior is a side effect of the implementation rather than an intentional design feature.

Key behaviors observed:
- Same alias can be used for different modules (e.g., both `Data.List` and `Data.Maybe` as `L`)
- The `qualified` keyword without `as` does not restrict imports to qualified-only access
- Name collisions resolve via first-match semantics rather than ambiguity errors

## Claims

### Claim 1: Duplicate Aliases Are Allowed
GHC permits using the same alias for different modules in the same scope.

**Evidence:**
```haskell
import qualified Data.List as L
import qualified Data.Maybe as L
```
Both imports succeed without error.

**Source:** GHCi experiments (Test 1)

---

### Claim 2: Namespaces Are Unioned
When duplicate aliases are used, the resulting alias provides access to names from all aliased modules (union semantics).

**Evidence:**
```haskell
L.nub [1,2]       -- works (from Data.List)
L.isJust (Just 1) -- works (from Data.Maybe)
```

**Source:** GHCi experiments (Test 1)

---

### Claim 3: `qualified` Without `as` Does Not Restrict Access
Using `import qualified Data.List` (without `as`) does not restrict usage to qualified-only access.

**Evidence:**
```haskell
import Data.List           -- unqualified
import qualified Data.List -- should be qualified only?
nub [1,2] -- still works unqualified!
```

**Source:** GHCi experiments (Test 2)

---

### Claim 4: Name Collisions Resolve via First-Match
When the same name exists in multiple modules sharing an alias, GHC uses first-match resolution rather than reporting an ambiguity error.

**Evidence:**
```haskell
import qualified Data.List as L
import qualified Data.Maybe as L
L.null []        -- True (Data.List.null)
L.null Nothing   -- True (Data.Maybe.null)
-- Type: Foldable t => t a -> Bool (polymorphic, both work)
```

**Source:** GHCi experiments (Test 3)

## Test Results

| Test | Description | Result |
|------|-------------|--------|
| 1 | Same alias for different modules | PASS - Both modules accessible via alias |
| 2 | Qualified import without `as` | PASS - Does not restrict to qualified-only |
| 3 | Same name collision | PASS - First match wins, no ambiguity error |

## Implementation Details

### Root Cause
This behavior stems from implementation choices in GHC's name resolution system:

1. **`ImportSpec` uses `Bag` (multiset)** - Allows duplicate import specifications without detection
2. **`qualSpecOK` filtering logic** - Returns ALL matching `is_as` values, not just one
3. **No validation for duplicate aliases** - The import processing pipeline does not check for alias collisions
4. **GRE accumulation via `plusGlobalRdrEnv`** - Unions namespaces as a side effect

### Relevant Source Locations

| File | Line | Function | Purpose |
|------|------|----------|---------|
| `compiler/GHC/Types/Name/Reader.hs` | 2151 | `qualSpecOK` | Filters import specs by alias |
| `compiler/GHC/Types/Name/Reader.hs` | 1601 | `pickQualGRE` | Selects qualified GRE |
| `compiler/GHC/Types/Name/Reader.hs` | 1549 | `pickGREs` | General GRE selection |

### Scope

**In Scope:**
- `ImportSpec` data structure
- `qualSpecOK` filtering logic
- GRE accumulation (`plusGlobalRdrEnv`)
- Duplicate alias handling

**Out of Scope:**
- Error detection logic (not currently implemented)
- Fix implementation (future work)

## Related Topics

- Qualified imports
- Import aliases (`as` clause)
- Global Rdr Environment (GRE)
- Name resolution and shadowing
- Import specification validation
