# Change Plan: Remove Field Initializers, Strict Non-Nullable Types

## Facts

Target: `systemf/src/systemf/surface/types.py`

Current state:
- All dataclasses use `frozen=True, kw_only=True`
- Most fields have default values or initializers
- Many fields are typed as `T | None` with `= None` defaults

## Design

### Semantic Analysis: What SHOULD be nullable/optional

**Truly optional (keep `| None`):**
- `location: Location | None` - synthetic nodes may lack location
- `param_doc: str | None` - parameter documentation is optional
- `docstring: str | None` - documentation is optional  
- `pragma: dict[str, str] | None` - pragmas are optional
- `type_ann: SurfaceType | None` in ValBind - type inference allows omission
- `type_annotation` in SurfaceTermDeclaration - top-level types required but internal nodes may vary
- `alias: str | None` in SurfaceImportDeclaration - optional import alias
- `items: list[str] | None` in SurfaceImportDeclaration - optional explicit imports

**Should become required (remove defaults, remove `| None`):**
- All `name: str = ""` → `name: str`
- All `index: int = 0` → `index: int`
- All `args: list[X] = field(default_factory=list)` → `args: list[X]`
- All `elements: list[X] = field(default_factory=list)` → `elements: list[X]`
- All `vars: list[str] = field(default_factory=list)` → `vars: list[str]`
- All `params: list[str] = field(default_factory=list)` → `params: list[str]`
- All `value: object = None` → `value: object`
- All `op: str = ""` → `op: str`

### Changes Required

**CRITICAL RULE: Only `location` field may have an initializer (`= None`)**

All other fields must:
1. Remove their initializer entirely (no `= ""`, `= None`, `field(default_factory=list)`)
2. Keep nullable types ONLY if semantically relevant (see list below)

**Semantically nullable (keep `| None`, but NO initializer):**
- `location` - only field with initializer `= None`
- `param_doc` - optional parameter documentation  
- `docstring` - optional documentation
- `pragma` - optional pragmas
- `type_ann` in ValBind - type inference allows omission
- `type_annotation` in SurfaceTermDeclaration/SurfacePrimOpDecl - signatures may omit types (TBD: should we require types?)
- `alias` in SurfaceImportDeclaration - optional import alias
- `items` in SurfaceImportDeclaration - optional explicit imports
- `var_type` in ScopedAbs - parameter type is optional

**NOT nullable (must have value):**
- `body` in SurfaceTermDeclaration - we don't support signature-only declarations, every term must have a body

**SurfaceNode:**
- `location: Location | None = field(default=None)` → `location: Location | None = None`

**SurfaceTypeVar:**
- `name: str = ""` → `name: str`

**SurfaceTypeArrow:**
- `arg: SurfaceType` - already required ✓
- `ret: SurfaceType` - already required ✓
- `param_doc: str | None = None` → `param_doc: str | None` (keep nullable but no default)

**SurfaceTypeForall:**
- `var: str` - already required ✓
- `body: SurfaceType` - already required ✓

**SurfaceTypeConstructor:**
- `name: str = ""` → `name: str`
- `args: list[SurfaceType] = field(default_factory=list)` → `args: list[SurfaceType]`

**SurfaceTypeTuple:**
- `elements: list[SurfaceType] = field(default_factory=list)` → `elements: list[SurfaceType]`

**SurfaceVar:**
- `name: str = ""` → `name: str`

**SurfaceAbs:**
- `params: list[tuple[str, SurfaceType | None]]` - already required ✓
- `body: SurfaceTerm` - already required ✓

**ScopedVar:**
- `index: int = 0` → `index: int`
- `debug_name: str = ""` → `debug_name: str`

**ScopedAbs:**
- `var_name: str = ""` → `var_name: str`
- `var_type: SurfaceType | None = None` → `var_type: SurfaceType | None`
- `body: SurfaceTerm | None = None` → `body: SurfaceTerm`

**SurfaceApp:**
- `func: SurfaceTerm` - already required ✓
- `arg: SurfaceTerm` - already required ✓

**SurfaceTypeAbs:**
- `vars: list[str] = field(default_factory=list)` → `vars: list[str]`
- `body: SurfaceTerm | None = None` → `body: SurfaceTerm`

**SurfaceTypeApp:**
- `func: SurfaceTerm | None = None` → `func: SurfaceTerm`
- `type_arg: SurfaceType | None = None` → `type_arg: SurfaceType`

**ValBind:**
- `name: str` - already required ✓
- `type_ann: SurfaceType | None` - already required, keep nullable (semantic) ✓
- `value: SurfaceTerm` - already required ✓

**ValBinds:**
- `bindings: list[ValBind]` - already required ✓
- `body: SurfaceTerm` - already required ✓

**ValBindsScoped:**
- `bindings: list[ValBind] = field(default_factory=list)` → `bindings: list[ValBind]`
- `body: SurfaceTerm | None = None` → `body: SurfaceTerm`

**SurfaceAnn:**
- `term: SurfaceTerm` - already required ✓
- `type: SurfaceType` - already required ✓

**SurfaceIf:**
- `cond: SurfaceTerm` - already required ✓
- `then_branch: SurfaceTerm` - already required ✓
- `else_branch: SurfaceTerm` - already required ✓

**SurfaceConstructor:**
- `name: str = ""` → `name: str`
- `args: list[SurfaceTerm] = field(default_factory=list)` → `args: list[SurfaceTerm]`

**SurfaceLit:**
- `prim_type: str = ""` → `prim_type: str`
- `value: object = None` → `value: object`

**GlobalVar:**
- `name: str = ""` → `name: str`

**SurfaceOp:**
- `left: SurfaceTerm | None = None` → `left: SurfaceTerm`
- `op: str = ""` → `op: str`
- `right: SurfaceTerm | None = None` → `right: SurfaceTerm`

**SurfaceTuple:**
- `elements: list[SurfaceTerm] = field(default_factory=list)` → `elements: list[SurfaceTerm]`

**SurfacePattern:**
- `constructor: str` - already required ✓
- `vars: list[SurfacePatternBase]` - already required ✓

**SurfacePatternTuple:**
- `elements: list[SurfacePatternBase] = field(default_factory=list)` → `elements: list[SurfacePatternBase]`

**SurfacePatternCons:**
- `head: SurfacePatternBase | None = None` → `head: SurfacePatternBase`
- `tail: SurfacePatternBase | None = None` → `tail: SurfacePatternBase`

**SurfaceLitPattern:**
- `prim_type: str = ""` → `prim_type: str`
- `value: object = None` → `value: object`

**SurfaceBranch:**
- `pattern: SurfacePatternBase` - already required ✓
- `body: SurfaceTerm` - already required ✓

**SurfaceCase:**
- `scrutinee: SurfaceTerm` - already required ✓
- `branches: list[SurfaceBranch]` - already required ✓

**SurfaceToolCall:**
- `tool_name: str = ""` → `tool_name: str`
- `args: list[SurfaceTerm] = field(default_factory=list)` → `args: list[SurfaceTerm]`

**SurfacePragma:**
- `directive: str = ""` → `directive: str`
- `raw_content: str = ""` → `raw_content: str`

**SurfaceConstructorInfo:**
- `name: str = ""` → `name: str`
- `args: list[SurfaceType] = field(default_factory=list)` → `args: list[SurfaceType]`
- `docstring: str | None = None` → `docstring: str | None`

**SurfaceDataDeclaration:**
- `name: str = ""` → `name: str`
- `params: list[str] = field(default_factory=list)` → `params: list[str]`
- `constructors: list[SurfaceConstructorInfo] = field(default_factory=list)` → `constructors: list[SurfaceConstructorInfo]`
- `docstring: str | None = None` → `docstring: str | None`
- `pragma: dict[str, str] | None = None` → `pragma: dict[str, str] | None`

**SurfaceTermDeclaration:**
- `name: str = ""` → `name: str`
- `type_annotation: SurfaceType | None = None` → `type_annotation: SurfaceType | None`
- `body: SurfaceTerm | None = None` → `body: SurfaceTerm` (REQUIRED - we don't support signature-only declarations)
- `docstring: str | None = None` → `docstring: str | None`
- `pragma: dict[str, str] | None = None` → `pragma: dict[str, str] | None`

**SurfacePrimTypeDecl:**
- `name: str = ""` → `name: str`
- `docstring: str | None = None` → `docstring: str | None`
- `pragma: dict[str, str] | None = None` → `pragma: dict[str, str] | None`

**SurfacePrimOpDecl:**
- `name: str = ""` → `name: str`
- `type_annotation: SurfaceType | None = None` → `type_annotation: SurfaceType | None`
- `docstring: str | None = None` → `docstring: str | None`
- `pragma: dict[str, str] | None = None` → `pragma: dict[str, str] | None`

**SurfaceImportDeclaration:**
- `module: str = ""` → `module: str`
- `qualified: bool = False` → keep with default (this is a flag, not a value)
- `alias: str | None = None` → `alias: str | None`
- `items: list[str] | None = None` → `items: list[str] | None`
- `hiding: bool = False` → keep with default (this is a flag)

## Impact

This will break a lot of code that constructs these AST nodes. All call sites will need to provide explicit values instead of relying on defaults.

However, the benefits are:
1. Type safety - can't forget to set a name
2. Explicitness - all construction is explicit
3. No hidden mutable defaults (default_factory bug risk)
4. Follows `plain-objects.md` guidance

## Files to Change

Primary: `systemf/src/systemf/surface/types.py`

Secondary (call sites that will break and need fixing):
- Parser code that creates these nodes
- Test code that constructs AST nodes
- Any transformation code that creates new nodes
- `pipeline.py:248` - remove `if body is not None` check (body always present now)
- `signature_collect_pass.py:117` - fix docstring example using `body=None`

## Strategy

Given the large impact, we should either:
1. Accept the breakage and fix all call sites in one go
2. Phase the changes by node type

For now, let's document the full plan and start with the types.py changes.
