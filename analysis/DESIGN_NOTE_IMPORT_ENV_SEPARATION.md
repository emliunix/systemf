# Design Note: GlobalRdrEnv and TypeEnv Separation

**Purpose:** Explain why the separation between GlobalRdrEnv and TypeEnv is essential for imports.

**Date:** 2024-03-28
**Status:** Design Principle

## The Core Insight

GlobalRdrEnv and TypeEnv are **not redundant** - they serve fundamentally different purposes:

- **GlobalRdrEnv**: "How do I find the right Name?"
- **TypeEnv**: "What is the type/definition of this Name?"

## Why Separation Enables Imports

### The Problem

When module B imports A:
```haskell
-- Module B
import A as X

y = X.foo 1
```

We need to:
1. Parse "X.foo" and resolve it to A's "foo"
2. Know that "X" is an alias for module A
3. Handle shadowing: if B defines its own "foo", it should shadow A.foo
4. Know whether X.foo is accessible (qualified import) or if bare "foo" should work too

### The Solution: GlobalRdrEnv

```haskell
data GlobalRdrElt = GRE
  { gre_name :: Name          -- The actual Name (A.foo with unique)
  , gre_imp  :: Bag ImportSpec  -- HOW it got into scope
  -- ImportSpec tracks:
  --   is_as :: ModuleName     -- The alias ("X")
  --   is_qual :: Bool         -- Qualified-only?
  --   is_mod :: Module        -- Actual module (A)
  }
```

**Building B's GlobalRdrEnv from import:**
```
1. Load A's interface
2. A exports: [Name(A.foo, uniq=42), Name(A.bar, uniq=43)]

3. For each export, create GRE:
   GRE { gre_name = Name(A.foo, 42)
       , gre_imp = [ImpSpec { is_as = "X"
                           , is_qual = False  -- unqualified also ok
                           , is_mod = A }]
       }

4. Add to GlobalRdrEnv:
   "foo" -> [GRE(A.foo, from=A via X)]
```

**Resolving "X.foo":**
```
lookupGRE env (Qual "X" "foo")
  -> lookupOccEnv env "foo" = [GRE(A.foo, ...)]
  -> pickQualGRE "X" = filter (\is -> is_as is == "X") gre_imp
  -> Returns GRE(A.foo)  -- Found!
  -> Get Name(A.foo, 42)
```

### Then: TypeEnv

Once we have `Name(A.foo, 42)`, typechecking needs the actual type:

```haskell
type TypeEnv = NameEnv TyThing  -- Name -> TyThing

data TyThing = AnId Id          -- Contains type and unfolding
             | ATyCon TyCon     -- Type constructor
             | ...
```

**Lookup:**
```
TypeEnv lookup: Name(A.foo, 42) -> TyThing(AnId id)
idType id -> Int -> Int  -- The type!
```

## Why Not Just One Environment?

**Option 1: Just TypeEnv**
- Key: OccName ("foo")
- Value: TyThing
- **Problem**: Can't handle "X.foo" vs "Y.foo" vs bare "foo"
- **Problem**: No way to track import provenance (alias, qualified, etc.)
- **Problem**: Shadowing becomes impossible (which "foo" wins?)

**Option 2: Just GlobalRdrEnv with TyThings**
- Key: OccName
- Value: (Name, TyThing)
- **Problem**: TyThings are LARGE (contain code, types)
- **Problem**: GlobalRdrEnv rebuilt frequently (on every import change)
- **Problem**: Separating renamer from typechecker becomes impossible

**The GHC Design: Best of Both**
```
GlobalRdrEnv: Small, frequently rebuilt
  - OccName -> GRE(Name)  -- Just names + import info

TypeEnv: Large, stable
  - Name -> TyThing       -- Actual definitions

Name is the bridge (just an Int)
```

## The Flow for Your Implementation

```python
# 1. User imports module A
import_module(hpt, cache, "A", alias="X", qualified=False)

# 2. Load A's interface
a_exports = load_interface("A")  # [Name(A.foo), Name(A.bar)]

# 3. Build GREs
for name in a_exports:
    spec = ImportSpec(is_as="X", is_qual=False, is_mod="A")
    gre = GRE(name=name, imp=[spec])
    add_to_rdr_env(rdr_env, name.surface_name, gre)

# 4. Typechecking user's "X.foo 1"
rdr_name = RdrName(Qual "X" "foo")
name = resolve_rdr_name(rdr_env, rdr_name)  # Name(A.foo, 42)

# 5. Get type
tything = type_env.lookup(name)  # TyThing(AnId)
type = get_type(tything)  # Int -> Int
```

## Design Trade-offs for systemf

**Option A: Follow GHC (Separate Envs)**
- Pros: Full import flexibility (aliases, qualified, hiding)
- Cons: Two lookup structures to maintain
- Best for: Complex module systems

**Option B: Simplified (Single Env)**
```python
# Just map qualified names to (Term, Type)
env: dict[str, (Term, Type)]  # "A.foo" -> (lam, Int->Int)

# On import:
for name, term in module.exports.items():
    key = f"{alias}.{name}" if qualified else name
    env[key] = (term, type)
```
- Pros: Simple, no Name indirection
- Cons: No bare name access for qualified imports, no shadowing history
- Best for: Simple module systems

**Recommendation:** Start with Option B (single env), move to Option A if you need:
- Import aliases (`import A as X`)
- Selective imports (`import A (foo, bar)`)
- Hiding imports (`import A hiding (baz)`)
- Unqualified access to qualified imports

## Key Takeaway

The GlobalRdrEnv/TypeEnv separation enables:
1. **Flexible import syntax** (aliases, qualified/unqualified)
2. **Collision detection** (same name from multiple modules)
3. **Shadowing** (local defs override imports)
4. **Efficient rebuilds** (RdrEnv small, TypeEnv large and stable)

Without this separation, imports become "flat namespace merging" with limited control.
