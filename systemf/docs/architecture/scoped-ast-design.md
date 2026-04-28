# Scoped-Extended Surface AST Design

## Idea

Instead of creating a separate `ScopedTerm` hierarchy, **extend Surface AST** with scoped variants:

```python
# Surface AST (names)
SurfaceVar(name="x")
SurfaceAbs(var="x", body=...)

# After scope checking (indices + names)
ScopedVar(index=1, debug_name="x")
ScopedAbs(var_name="x", body=...)
```

**Benefits**:
- Reuse existing surface AST structure
- No code duplication for constructors, applications, etc.
- Can mix scoped and unscoped during transformation
- Clear distinction: names vs indices

---

## Implementation

### Extend Surface Types

```python
# src/systemf/surface/types.py

@dataclass(frozen=True)
class SurfaceVar(SurfaceTerm):
    """Variable reference by name (before scope checking)."""
    name: str

@dataclass(frozen=True)
class ScopedVar(SurfaceTerm):
    """Variable reference by de Bruijn index (after scope checking).
    
    Replaces SurfaceVar during scope checking.
    """
    index: int           # De Bruijn index (0 = nearest binder)
    debug_name: str      # Original name for error messages

@dataclass(frozen=True)
class SurfaceAbs(SurfaceTerm):
    """Lambda with parameter name (before scope checking)."""
    var: str
    var_type: Optional[SurfaceType]
    body: SurfaceTerm

@dataclass(frozen=True)
class ScopedAbs(SurfaceTerm):
    """Lambda with parameter name preserved (after scope checking).
    
    Replaces SurfaceAbs during scope checking.
    """
    var_name: str        # Original parameter name
    var_type: Optional[SurfaceType]
    body: SurfaceTerm

# Type variables too
@dataclass(frozen=True)
class SurfaceTypeVar(SurfaceType):
    name: str

@dataclass(frozen=True)
class ScopedTypeVar(SurfaceType):
    index: int
    debug_name: str
```

### Type Aliases for Clarity

```python
# Before scope checking
UnscopedTerm = SurfaceVar | SurfaceAbs | SurfaceApp | ...
UnscopedType = SurfaceTypeVar | SurfaceTypeArrow | ...

# After scope checking  
ScopedTerm = ScopedVar | ScopedAbs | SurfaceApp | ...
ScopedType = ScopedTypeVar | SurfaceTypeArrow | ...

# Mixed (during transformation)
MixedTerm = SurfaceVar | ScopedVar | SurfaceAbs | ScopedAbs | ...
```

### Scope Checking as Transformation

```python
class ScopeChecker:
    """Transforms Surface AST to Scoped AST."""
    
    def check_term(self, term: SurfaceTerm, ctx: ScopeContext) -> SurfaceTerm:
        """Returns term with all Vars/Abs converted to scoped versions."""
        match term:
            case SurfaceVar(name, location):
                # Convert to scoped
                try:
                    index = ctx.lookup_term(name)
                    return ScopedVar(location, index, name)
                except ScopeError:
                    raise ScopeError(f"Undefined variable '{name}'", location)
            
            case SurfaceAbs(var, var_type, body, location):
                # Convert parameter and body
                new_ctx = ctx.extend_term(var)
                scoped_body = self.check_term(body, new_ctx)
                return ScopedAbs(location, var, var_type, scoped_body)
            
            case SurfaceApp(func, arg, location):
                # Recursively check function and argument
                scoped_func = self.check_term(func, ctx)
                scoped_arg = self.check_term(arg, ctx)
                return SurfaceApp(location, scoped_func, scoped_arg)
            
            # ... other cases pass through or transform recursively
            
            case _:
                # Constructors, literals, etc. pass through unchanged
                return term
```

### Detection Functions

```python
def is_scoped_term(term: SurfaceTerm) -> bool:
    """Check if term has been scope-checked."""
    match term:
        case ScopedVar() | ScopedAbs() | ScopedTypeAbs():
            return True
        case SurfaceApp(func, arg, _):
            return is_scoped_term(func) and is_scoped_term(arg)
        case SurfaceLet(bindings, body, _):
            return all(is_scoped_term(b[2]) for b in bindings) and is_scoped_term(body)
        # ... etc for other composite terms
        case _:
            return False

def is_fully_scoped(term: SurfaceTerm) -> bool:
    """Check if term has NO remaining SurfaceVar/SurfaceAbs."""
    match term:
        case SurfaceVar() | SurfaceAbs() | SurfaceTypeAbs():
            return False
        case ScopedVar() | ScopedAbs() | ScopedTypeAbs():
            return True
        case SurfaceApp(func, arg, _):
            return is_fully_scoped(func) and is_fully_scoped(arg)
        # ... etc
```

---

## Advantages Over Separate Hierarchy

### 1. Reuse Structure

**Separate hierarchy** (bad):
```python
# Duplicate all term types
@dataclass class ScopedVar: ...
@dataclass class ScopedAbs: ...
@dataclass class ScopedApp: ...
# ... 15 more types
```

**Extended surface** (good):
```python
# Only add scoped variants for binding constructs
@dataclass class ScopedVar: ...
@dataclass class ScopedAbs: ...
# SurfaceApp, SurfaceConstructor, etc. work for both!
```

### 2. Incremental Transformation

Can scope-check part of a program:

```python
# Before
let x = 5 in x + y

# After scope checking (y is global, x is local)
let x = 5 in (ScopedVar 0 "x") + (SurfaceVar "y")
```

### 3. Pattern Matching Reuse

Type elaborator can pattern match on both:

```python
def elaborate(term: SurfaceTerm, ctx: Context):
    match term:
        case ScopedVar(index, debug_name, location):
            # Scope-checked: use index
            ty = ctx.lookup_type(index)
            return Core.Var(location, index, debug_name), ty
        
        case SurfaceVar(name, location):
            # Shouldn't happen after scope checking
            raise ElaborationError(f"Unscoped variable: {name}", location)
        
        case SurfaceApp(func, arg, location):
            # Works for both scoped and unscoped subterms
            core_func, ty_func = elaborate(func, ctx)
            core_arg, ty_arg = elaborate(arg, ctx)
            # ...
```

### 4. Type Safety with Protocols

```python
from typing import Protocol

class HasLocation(Protocol):
    source_loc: Location

class Scoped(Protocol):
    """Marker protocol for scope-checked terms."""
    pass

# ScopedVar, ScopedAbs implement Scoped
```

---

## Updated Pipeline

```python
def elaborate_program(decls: list[SurfaceDeclaration]):
    # Phase 1: Scope checking (transforms Var/Abs)
    scoped_decls = []
    for decl in decls:
        scoped_decl = scope_checker.check_declaration(decl)
        assert is_fully_scoped(scoped_decl)  # All vars scoped
        scoped_decls.append(scoped_decl)
    
    # Phase 2: Type elaboration (assumes scoped)
    core_decls = []
    for decl in scoped_decls:
        core_decl = type_elaborator.elaborate_declaration(decl)
        core_decls.append(core_decl)
    
    # Phase 3: LLM pragma
    final_decls = [llm_pass.process(d) for d in core_decls]
    
    return Module(final_decls)
```

---

## Type Checking the Transformation

```python
# Before scope checking
def check_term_unscoped(term: UnscopedTerm, ctx: ScopeContext) -> ScopedTerm:
    ...

# After scope checking  
def elaborate_scoped(term: ScopedTerm, ctx: TypeContext) -> Core.Term:
    ...
```

Or use runtime assertions:

```python
def elaborate(term: SurfaceTerm, ctx: TypeContext) -> Core.Term:
    """Precondition: term is fully scoped."""
    assert is_fully_scoped(term), f"Term not scope-checked: {term}"
    ...
```

---

## Summary

**Instead of**:
```
surface/types.py      - Surface AST (names)
scope/types.py        - Scoped AST (indices)  # Duplicate!
```

**We do**:
```
surface/types.py      - Extended AST
  ├── SurfaceVar      - Name-based
  ├── ScopedVar       - Index-based (NEW)
  ├── SurfaceAbs      - Name-based
  ├── ScopedAbs       - Index-based (NEW)
  ├── SurfaceApp      - Works for both
  ├── SurfaceConstructor  - Works for both
  └── ...
```

**Benefits**:
- Less code duplication
- Can mix scoped/unscoped during development
- Easier to debug (see intermediate state)
- Reuse pattern matching logic
- Clear transformation: names → indices
