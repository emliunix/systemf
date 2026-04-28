# Multi-Pass Elaborator Implementation Plan (Final)

## New Decisions

1. **All at once implementation** - No gradual migration, system works when complete
2. **Core AST keeps names** - `debug_name` in `Var`, `var_name` in `Abs` (already done)
3. **Scope checking is mandatory** - Separates name resolution from type checking
4. **Scoped AST stores indices + names** - For error messages
5. **Elaborate directly to typed Core** - No untyped intermediate
6. **No verification pass** - Trust the elaborator
7. **LLM pragma as dedicated pass** - Keep main elaborator clean

---

## Pipeline

```
Surface AST ──► Scoped AST ──► Core AST ──► (LLM Pass)
  (names)        (dbi+names)   (typed)
```

**Three phases**:
1. **Scope** - Name → de Bruijn index + preserve names
2. **Inference** - Type checking, elaborate to typed Core
3. **LLM** - Pragma extraction (optional)

---

## Phase 1: Scope Checking

**Duration**: 2-3 days

### 1.1 Create Scoped AST (`surface/scoped/types.py`)

```python
@dataclass(frozen=True)
class ScopedTerm:
    source_loc: Location

@dataclass(frozen=True)
class ScopedVar(ScopedTerm):
    """Variable with de Bruijn index AND original name."""
    index: int
    original_name: str

@dataclass(frozen=True)
class ScopedAbs(ScopedTerm):
    """Lambda with original parameter name."""
    var_name: str
    body: ScopedTerm

# ... etc for all term types

@dataclass(frozen=True)
class ScopedTypeVar(ScopedType):
    """Type variable with index and name."""
    index: int
    original_name: str
```

### 1.2 Create Scope Context (`surface/scoped/context.py`)

```python
@dataclass
class ScopeContext:
    """Tracks name → de Bruijn index mapping."""
    
    term_names: list[str]  # Index 0 = most recent
    type_names: list[str]
    globals: set[str]
    
    def lookup_term(self, name: str) -> int:
        """Get de Bruijn index for name."""
        for i, n in enumerate(self.term_names):
            if n == name:
                return i
        raise ScopeError(f"Undefined variable '{name}'")
    
    def extend_term(self, name: str) -> "ScopeContext":
        """Add binding, becomes index 0."""
        return ScopeContext([name] + self.term_names, ...)
```

### 1.3 Implement Scope Checker (`surface/scoped/checker.py`)

```python
class ScopeChecker:
    def check_term(self, term: SurfaceTerm, ctx: ScopeContext) -> ScopedTerm:
        match term:
            case SurfaceVar(name, location):
                try:
                    index = ctx.lookup_term(name)
                    return ScopedVar(location, index, name)
                except ScopeError:
                    raise ScopeError(f"Undefined variable '{name}'", location)
            
            case SurfaceAbs(var, _, body, location):
                new_ctx = ctx.extend_term(var)
                scoped_body = self.check_term(body, new_ctx)
                return ScopedAbs(location, var, scoped_body)
            
            # ... etc
```

### 1.4 Handle Top-Level Declarations

```python
def check_declaration(self, decl: SurfaceDeclaration) -> ScopedDeclaration:
    match decl:
        case SurfaceTermDeclaration(name, type_ann, body, ...):
            # Scope check type annotation
            scoped_type = self.check_type(type_ann) if type_ann else None
            
            # Scope check body
            scoped_body = self.check_term(body, ctx)
            
            return ScopedTermDeclaration(name, scoped_type, scoped_body, ...)
```

---

## Phase 2: Type Elaboration (Inference)

**Duration**: 3-4 days

### 2.1 Create Type Elaborator (`surface/inference/elaborator.py`)

Move logic from current elaborator but:
- Input is `ScopedTerm` (not `SurfaceTerm`)
- Output is typed `Core.Term`
- Assumes names already resolved (uses indices directly)

```python
class TypeElaborator:
    def elaborate_term(self, term: ScopedTerm, ctx: TypeContext) -> tuple[Core.Term, Type]:
        match term:
            case ScopedVar(index, original_name, location):
                ty = ctx.lookup_type(index)
                return Core.Var(location, index, original_name), ty
            
            case ScopedAbs(var_name, body, location):
                # Create fresh meta for argument type
                arg_ty = self.fresh_meta()
                
                # Check body with extended context
                new_ctx = ctx.extend_term(arg_ty)
                core_body, body_ty = self.elaborate_term(body, new_ctx)
                
                # Build typed lambda
                result_ty = TypeArrow(arg_ty, body_ty)
                core_term = Core.Abs(location, var_name, arg_ty, core_body)
                
                return core_term, result_ty
```

### 2.2 Handle Top-Level Declaration Collection

**Key for mutual recursion**: Collect all signatures first, then elaborate bodies.

```python
def elaborate_module(self, decls: list[ScopedDeclaration]) -> Module:
    # Step 1: Collect all type signatures
    signatures = {}
    for decl in decls:
        if isinstance(decl, ScopedTermDeclaration):
            if decl.type_annotation:
                ty = self.elaborate_type(decl.type_annotation)
                signatures[decl.name] = ty
    
    # Step 2: Elaborate all bodies (with all signatures in scope)
    declarations = []
    for decl in decls:
        match decl:
            case ScopedTermDeclaration(name, _, body, ...):
                # Add all signatures to context
                ctx = TypeContext.empty()
                for sig_name, sig_ty in signatures.items():
                    ctx = ctx.extend_global(sig_name, sig_ty)
                
                # Elaborate body
                core_body, inferred_ty = self.elaborate_term(body, ctx)
                
                # Use annotation if present, else inferred
                final_ty = signatures.get(name, inferred_ty)
                
                declarations.append(
                    Core.TermDeclaration(name, final_ty, core_body, ...)
                )
```

### 2.3 Unification

```python
def unify(self, t1: Type, t2: Type) -> None:
    """Unify two types, updating metavariables."""
    t1 = self.resolve(t1)
    t2 = self.resolve(t2)
    
    if isinstance(t1, TypeVar) and t1.name.startswith("?"):
        self.solve_meta(t1.name, t2)
    elif isinstance(t2, TypeVar) and t2.name.startswith("?"):
        self.solve_meta(t2.name, t1)
    elif isinstance(t1, TypeArrow) and isinstance(t2, TypeArrow):
        self.unify(t1.arg, t2.arg)
        self.unify(t1.ret, t2.ret)
    elif t1 != t2:
        raise UnificationError(t1, t2)
```

---

## Phase 3: LLM Pragma Pass

**Duration**: 1 day

### 3.1 Create LLM Pass (`surface/llm/pass.py`)

```python
class LLMPragmaPass:
    def process(self, decl: Core.TermDeclaration, surface_decl: SurfaceTermDeclaration) -> Core.TermDeclaration:
        if not surface_decl.pragma:
            return decl
        
        # Extract pragma parameters
        params = self.parse_pragma(surface_decl.pragma)
        
        # Replace body with PrimOp
        new_body = Core.PrimOp(
            location=decl.body.source_loc,
            name=f"llm.{decl.name}"
        )
        
        return Core.TermDeclaration(
            name=decl.name,
            type_annotation=decl.type_annotation,
            body=new_body,
            pragma=surface_decl.pragma,
            docstring=surface_decl.docstring,
            param_docstrings=surface_decl.param_docstrings
        )
```

---

## Phase 4: Pipeline Orchestration

**Duration**: 1 day

### 4.1 Create Pipeline (`surface/pipeline.py`)

```python
def elaborate_program(decls: list[SurfaceDeclaration]) -> Result[Module, list[SystemFError]]:
    """Full elaboration pipeline."""
    
    scope_checker = ScopeChecker()
    type_elaborator = TypeElaborator()
    llm_pass = LLMPragmaPass()
    
    # Phase 1: Scope checking
    scoped_decls = []
    for decl in decls:
        try:
            scoped_decls.append(scope_checker.check_declaration(decl))
        except ScopeError as e:
            return Err([e])
    
    # Phase 2: Type elaboration
    try:
        module = type_elaborator.elaborate_module(scoped_decls)
    except TypeError as e:
        return Err([e])
    
    # Phase 3: LLM pragma processing
    final_decls = []
    for i, core_decl in enumerate(module.declarations):
        surface_decl = decls[i]
        if isinstance(core_decl, Core.TermDeclaration):
            final_decl = llm_pass.process(core_decl, surface_decl)
            final_decls.append(final_decl)
        else:
            final_decls.append(core_decl)
    
    return Ok(Module(declarations=final_decls, ...))
```

---

## Phase 5: Cleanup

**Duration**: 1 day

### 5.1 Delete Old Elaborator

- Remove `surface/elaborator.py`
- Update `surface/__init__.py` exports
- Update all imports

### 5.2 Update Tests

- Move elaborator tests to `tests/surface/test_scope.py` and `tests/surface/test_inference.py`
- Update integration tests
- All tests must pass

### 5.3 Update REPL

- Use new pipeline API
- Verify error messages show source locations and names

---

## Module Structure

```
src/systemf/surface/
├── __init__.py              # Public API
├── types.py                 # Surface AST (existing)
├── parser/                  # Parser (existing)
│   └── ...
├── scope/                   # Phase 1: Scope checking
│   ├── __init__.py
│   ├── types.py             # ScopedTerm, ScopedType
│   ├── checker.py           # ScopeChecker
│   ├── context.py           # ScopeContext
│   └── errors.py            # ScopeError
├── inference/               # Phase 2: Type elaboration
│   ├── __init__.py
│   ├── elaborator.py        # TypeElaborator
│   ├── context.py           # TypeContext
│   ├── unification.py       # Unification
│   └── errors.py            # TypeError
├── llm/                     # Phase 3: LLM pragma
│   ├── __init__.py
│   └── pass.py              # LLMPragmaPass
└── pipeline.py              # Orchestration

src/systemf/core/
├── ast.py                   # Core AST (updated with names)
├── types.py                 # Type representations
├── context.py               # Type checking context
└── errors.py                # Error hierarchy
```

---

## Testing Strategy

### Unit Tests per Phase

```python
# tests/surface/test_scope.py
class TestScopeChecker:
    def test_variable_lookup(self):
        surface = SurfaceVar("x", loc)
        ctx = ScopeContext(term_names=["y", "x"])
        scoped = scope_checker.check_term(surface, ctx)
        assert scoped == ScopedVar(loc, index=1, original_name="x")
    
    def test_undefined_variable(self):
        surface = SurfaceVar("z", loc)
        ctx = ScopeContext(term_names=["x"])
        with pytest.raises(ScopeError) as e:
            scope_checker.check_term(surface, ctx)
        assert "Undefined variable 'z'" in str(e.value)

# tests/surface/test_inference.py
class TestTypeElaborator:
    def test_identity_function(self):
        scoped = ScopedAbs(loc, "x", ScopedVar(loc, 0, "x"))
        core, ty = elaborator.elaborate_term(scoped, Context.empty())
        assert isinstance(core, Core.Abs)
        assert core.var_name == "x"
        assert isinstance(ty, TypeArrow)
```

### Integration Tests

```python
# tests/test_pipeline.py
class TestFullPipeline:
    def test_end_to_end(self):
        source = """
        let id = \\x -> x
        let result = id 5
        """
        decls = parse_program(source)
        result = elaborate_program(decls)
        assert result.is_ok()
        
        module = result.unwrap()
        assert "id" in module.global_types
        assert "result" in module.global_types
```

---

## Error Messages

**Goal**: Every error shows:
1. **Location**: File, line, column
2. **Name**: Original variable name
3. **Context**: The problematic term

**Example**:
```
error: Type mismatch
  --> test.sf:5:10
  |
5 |   x + "hello"
  |   ^
  |
  = expected: Int
  = actual: String
  = in term: x
```

---

## Implementation Order

**Week 1**:
- Day 1-2: Scoped AST + Scope Context
- Day 3-4: Scope Checker + tests
- Day 5: Top-level declarations in scope checker

**Week 2**:
- Day 1-2: Type Elaborator structure
- Day 3-4: Move logic from old elaborator
- Day 5: Unification + tests

**Week 3**:
- Day 1: Top-level collection (mutual recursion)
- Day 2: LLM Pass
- Day 3: Pipeline orchestration
- Day 4: Delete old elaborator, update imports
- Day 5: Fix tests, REPL integration

---

## Success Criteria

System is complete when:
1. ✅ All surface terms can be scope-checked
2. ✅ All scoped terms can be elaborated to typed Core
3. ✅ Variable names preserved through all phases
4. ✅ Source locations attached to all errors
5. ✅ All 486+ tests pass
6. ✅ REPL works with new pipeline
7. ✅ Error messages show names and locations
8. ✅ Old elaborator deleted

**No partial functionality.** It either works correctly or it doesn't work.
