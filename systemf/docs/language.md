# System F Language Specification (Elab3)

**Status:** Design Document  
**Purpose:** Defines the type system and core language for the module-aware elaborator.

## Overview

The elaborator (elab3) builds on elab2's type system but adds:
- Module-scoped Names with globally unique IDs
- Reader environment for name resolution
- Module system integration

## Type System

### Types (Ty)

From elab2 (reused):

```python
# Type hierarchy
Ty
├── TyCon(name: str)           # Concrete type constructors: Int, Bool, String
├── TyVar                      # Type variables
│   ├── BoundTv(name: str)     # Bound by forall
│   └── SkolemTv(name, uniq)   # Rigid skolem constants
├── TyFun(arg: Ty, result: Ty) # Function types (a -> b)
├── TyForall(vars, body)       # Polymorphic types
├── MetaTv(uniq, ref)          # Unification variables
└── TyConApp(name, args)       # Applied type constructors
```

**Key Types:**
- `INT = TyCon("Int")`
- `STRING = TyCon("String")`

### Names

Global identifiers with unique IDs:

```python
@dataclass(frozen=True)
class Name:
    surface: str    # Human-readable name
    unique: int     # Globally unique ID
    module: str     # Defining module
```

Names use the `unique` field for O(1) equality comparison.

## Core Terms (CoreTm)

System F core language:

```python
CoreTm
├── CoreLit(value: Lit)              # Literals
├── CoreVar(name: str, ty: Ty)       # Variables with type
├── CoreLam(name, ty, body)          # Lambda abstraction
├── CoreApp(fun, arg)                # Application
├── CoreTyLam(var, body)             # Type abstraction
├── CoreTyApp(fun, tyarg)            # Type application
└── CoreLet(binding, body)           # Let binding

Binding
├── NonRec(name, expr)               # Non-recursive: let x = e in b
└── Rec(bindings: [(name, expr)])    # Recursive: letrec { x = e1; y = e2 } in b
```

**Key change:** Let bindings now use a `Binding` type that distinguishes recursive from non-recursive bindings. Recursive bindings support mutual recursion - all names are in scope for all expressions.

## TyThings

Tagged union of "things" in the type environment:

```python
TyThing
├── AnId(name, term, type_scheme)    # Term-level binding
├── ATyCon(name, arity, constructors) # Type constructor
└── ACon(name, tag, arity, parent)   # Data constructor
```

## Literals

```python
Lit
├── LitInt(value: int)      # Integer literals
└── LitString(value: str)   # String literals
```

## Wrapper System

Wrappers represent type-driven transformations from surface to core:

```python
Wrapper
├── WpHole                           # Identity
├── WpCast(ty_from, ty_to)          # Type cast
├── WpFun(arg_ty, wp_arg, wp_res)   # Function wrapper
├── WpTyApp(ty_arg)                 # Type application
├── WpTyLam(ty_var)                 # Type abstraction
└── WpCompose(wp_g, wp_f)           # Composition
```

## Integration with Module System

### Name Resolution Flow

1. **Surface name** (string) → **ReaderEnv** → **Resolved Name** (Name)
2. **Name** → **TypeEnv** → **TyThing** (definition)

### Module Components

- **HPT**: Maps module names → Module
- **NameCache**: Stable allocation of (module, surface) → Name
- **ReaderEnv**: Surface name → list of RdrElt (with provenance)

## Builtin Types

Pre-allocated Uniques for builtin types:

```python
BUILTIN_UNIQUES = {
    "Int": 1,
    "Bool": 2,
    "String": 3,
    "List": 4,
    "Pair": 5,
    # Primitives start at 100
    "int_plus": 100,
    "int_minus": 101,
    ...
}
```

## Design Decisions

1. **Reuse elab2 Ty**: The type system is identical to elab2. We import from there.
2. **New Name type**: Module-scoped with unique IDs (different from elab2's Name).
3. **Separate CoreTm**: Core language is similar but integrated with new Name type.
4. **TyThings carry Names**: For convenient access during type checking.

## Files

- `types.py`: Name, TyThing, DataConInfo
- `core.py`: CoreTm AST (adapted from elab2)
- `mod.py`: Module, HPT, NameCache
- `reader_env.py`: ReaderEnv, RdrElt, ImportSpec
- `repl.py`: REPL, REPLSession
