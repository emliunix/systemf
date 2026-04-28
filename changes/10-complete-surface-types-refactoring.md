# Change Plan: Complete Surface Types Refactoring

**Related to:** Change 9 (strict-types-no-initializers)  
**Status:** Completed with expanded scope  
**Date:** 2026-04-01

## Original Plan vs Actual Changes

### Original Scope (from change 9)
- Remove all field initializers from dataclasses in `types.py` (except `location`)
- Make fields strictly non-nullable unless semantically relevant
- Add `@override` decorator to all `__str__` methods

### Expanded Scope (discovered during implementation)
During the refactoring, several additional issues were discovered that required fixes:

1. **SurfaceConstructorInfo** had default values and wasn't using `@dataclass` decorator properly
2. **Multiple test files** had implicit dependencies on default field values
3. **SurfaceTypeArrow** calls were missing `param_doc` parameter
4. **SurfacePattern** calls were missing `vars` parameter
5. **Various declaration types** were missing required fields

## Changes Made

### Core Types File
**File:** `systemf/src/systemf/surface/types.py`

Changes:
1. Removed all `= ""`, `= None`, `field(default_factory=list)` initializers
2. Added `@override` decorator to all `__str__` methods
3. Fixed duplicate `@override` decorators (33 duplicates removed)
4. Made `SurfaceConstructorInfo` a proper `@dataclass` with required fields:
   - Changed from `name: str = ""` to `name: str`
   - Changed from `args: list[SurfaceType] = field(default_factory=list)` to `args: list[SurfaceType]`
   - Changed from `docstring: str | None = None` to `docstring: str | None`
5. Maintained backwards compatibility for `SurfaceAbs` and `SurfaceTypeAbs` via custom `__init__`

### Test Files Fixed

1. **systemf/tests/test_surface/test_inference.py**
   - Added `param_doc=None` to `SurfaceTypeArrow` calls

2. **systemf/tests/test_surface/test_parser/test_expressions.py**
   - Added `vars=[]` to `SurfacePattern` calls

3. **systemf/tests/test_surface/test_parser/test_multiple_decls.py**
   - Added `vars=[]` to `SurfacePattern` calls
   - Changed `vars=["z", "zs"]` to proper `SurfacePattern` objects
   - Added `args=[]` to `SurfaceTypeConstructor` calls
   - Added `param_doc=None` to `SurfaceTypeArrow` calls
   - Added `docstring=None, pragma=None` to `SurfaceTermDeclaration` calls
   - Added `params=[], docstring=None, pragma=None` to `SurfaceDataDeclaration` calls
   - Added `args=[], docstring=None` to `SurfaceConstructorInfo` calls

4. **systemf/tests/test_surface/test_parser/test_declarations.py**
   - Added `alias=None, items=None` to `SurfaceImportDeclaration` calls

5. **systemf/tests/test_elaborator_rules.py**
   - Added `param_doc=None` to `SurfaceTypeArrow` calls

6. **systemf/tests/test_surface/test_putting2007_examples.py**
   - Added `param_doc=None` to `SurfaceTypeArrow` calls

7. **systemf/tests/test_surface/test_putting2007_gaps.py**
   - Added `param_doc=None` to `SurfaceTypeArrow` calls

8. **systemf/tests/test_pipeline.py**
   - Added `param_doc=None` to `SurfaceTypeArrow` calls

## Semantically Nullable Fields (Preserved)

These fields remain nullable as they are semantically meaningful:
- `location: Location | None = None` - only field with initializer
- `param_doc: str | None` - optional parameter documentation
- `docstring: str | None` - optional declaration documentation
- `pragma: dict[str, str] | None` - optional compiler pragma
- `type_ann` in `ValBind` - optional type annotation
- `type_annotation` in declarations - optional type signature
- `alias`, `items` in `SurfaceImportDeclaration` - optional import modifiers
- `var_type` in `ScopedAbs` - optional type annotation

## Backwards Compatibility

Maintained for:
- `SurfaceAbs.__init__` - supports old `var=` parameter
- `SurfaceTypeAbs.__init__` - supports old `var=` parameter

## Validation

The changes ensure:
1. All AST nodes require explicit field initialization
2. No implicit defaults that could hide errors
3. Type checker will catch missing fields at call sites
4. Clear semantic distinction between required and optional fields

## Commits

- 068c72d refactor(systemf): strict field initialization in surface types
- 6d35bda fix(systemf): remove duplicate @override decorators
- e58826f test(systemf): fix SurfacePattern calls to include vars argument
- a52581a test(systemf): add missing param_doc=None to SurfaceTypeArrow calls
- e3e955b test(systemf): add missing args=[] to SurfaceTypeConstructor calls
- c8c860d test(systemf): add missing fields to declaration calls
- 7131f99 refactor(systemf): remove defaults from SurfaceConstructorInfo and fix test calls
- 45816e7 test(systemf): fix remaining SurfaceTypeArrow calls missing param_doc
