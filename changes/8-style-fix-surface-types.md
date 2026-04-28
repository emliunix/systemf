# Change Plan: Style Violations in surface/types.py

## Facts

File: `systemf/src/systemf/surface/types.py`

Current style violations (trivial fixes only):
1. **Imports**: Uses deprecated `Optional, Union` from typing (line 10)
2. **Type annotations**: Multiple `Optional[T]` usages (lines 24, 169, 240, 243, 314, 484, 485, 547, 548, 743)
3. **Union types**: Uses `Union[...]` syntax (lines 124-126, 777-782)
4. **Forward references**: Uses quoted forward references in `SurfaceTypeRepr` (lines 124-126)

Non-trivial violations (out of scope):
- `field(default_factory=list)` usages - requires factory method refactoring

## Design

### Changes to make:

1. **Update imports (line 10)**
   - Remove `Optional, Union` from typing import
   - Keep `override`

2. **Replace Optional[T] with T | None**
   - Line 24: `Optional[Location]` -> `Location | None`
   - Line 169: `Optional[SurfaceType]` -> `SurfaceType | None`
   - Line 240: `Optional[SurfaceType]` -> `SurfaceType | None`
   - Line 243: `Optional[SurfaceTerm]` -> `SurfaceTerm | None`
   - Line 314: `Optional[SurfaceTerm]` -> `SurfaceTerm | None`
   - Line 315: `Optional[SurfaceType]` -> `SurfaceType | None`
   - Line 484: `Optional[SurfaceTerm]` -> `SurfaceTerm | None`
   - Line 485: `Optional[SurfaceTerm]` -> `SurfaceTerm | None`
   - Line 547: `Optional[SurfacePatternBase]` -> `SurfacePatternBase | None`
   - Line 548: `Optional[SurfacePatternBase]` -> `SurfacePatternBase | None`
   - Line 743: `Optional[SurfaceType]` -> `SurfaceType | None`

3. **Replace Union types with | operator**
   - Lines 124-126: `Union[...]` -> single-line `|`
   - Lines 777-782: parenthesized `|` block -> single-line `|`

4. **Remove unnecessary future import**
   - Line 7: `from __future__ import annotations` - check if still needed after removing quoted refs

## Files to Change

- `systemf/src/systemf/surface/types.py`

## Why This Works

- Modern Python 3.12+ syntax (`X | None` vs `Optional[X]`)
- Follows style guide in `docs/styles/python.md`
- Cleaner, more readable type annotations
- No behavioral changes - purely syntactic
