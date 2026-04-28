# Type System Concepts

**Understanding the two-level design of System F.**

---

## The Core Insight: Two Languages

System F has a **two-level architecture** that separates the language users write from the language the machine executes:

```
┌─────────────────────────────────────────────────────────────┐
│  SURFACE LANGUAGE                                            │
│  - Implicit type instantiation: id 3                         │
│  - Type annotations optional                                 │
│  - Convenient syntax                                         │
│  - Requires inference                                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
                         Elaboration
                    (Bidirectional + Unification)
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  CORE LANGUAGE                                               │
│  - Explicit type application: id[Int] 3                      │
│  - All types explicit                                        │
│  - Minimal syntax                                            │
│  - Directly executable                                       │
└─────────────────────────────────────────────────────────────┘
```

## Why Two Levels?

### System F Core (Explicit)

The theoretical foundation (Girard-Reynolds polymorphic lambda calculus):

```haskell
-- Type abstraction: Λ (capital lambda)
id = Λa. λx:a. x        -- "for all types a, id takes an a and returns a"

-- Type application: explicit @Type
id @Int 3               -- MUST specify @Int
id @String "hello"      -- MUST specify @String
```

**Advantages:**
- Simple, unambiguous semantics
- Easy to formalize and prove correct
- Direct execution model

**Disadvantages:**
- Verbose (must write type applications everywhere)
- Poor ergonomics for programmers

### Surface Language (Implicit)

The practical language programmers actually write:

```haskell
-- Type annotation
id :: forall a. a -> a

-- Implicit instantiation - compiler figures out the types
id 3                    -- No @Int needed!
id "hello"              -- No @String needed!
```

**Advantages:**
- Concise, readable code
- Type inference reduces boilerplate
- Familiar to Haskell/OCaml programmers

**Disadvantages:**
- Requires complex elaboration
- Type inference is undecidable in general
- Sometimes needs annotations

## The Gap Between Surface and Core

Surface code **cannot** directly execute. It must be **elaborated** into Core:

```
Surface:     id 3
             ↓
         Elaborator asks:
         - What is id's type? → forall a. a -> a
         - What is 3's type?  → Int
         - How to instantiate? → a = Int
             ↓
Core:        id[Int] 3
```

This elaboration is where **bidirectional type checking** and **unification** work together.

## Key Distinctions

| Aspect | Surface | Core |
|--------|---------|------|
| **Type application** | Implicit | Explicit |
| **Annotations** | Optional | Required |
| **Meta-variables** | TMeta (existential) | None |
| **Execution** | No | Yes |
| **Inference** | Yes | No |

## What Elaboration Does

The elaborator transforms Surface AST into Core AST:

1. **Resolves names** → de Bruijn indices
2. **Infers types** → bidirectional checking
3. **Solves constraints** → unification
4. **Inserts explicit types** → TApp nodes

**Example transformation:**

```haskell
-- Surface AST
SurfaceApp(
    func=SurfaceVar("id"),
    arg=SurfaceIntLit(3)
)

-- ↓ Elaboration

-- Core AST
App(
    func=TApp(
        func=Global("id"),
        type_arg=TypeConstructor("Int", [])
    ),
    arg=Lit(prim_type="Int", value=3)
)
```

## Learning Path

To understand how elaboration works:

1. **[Bidirectional Checking](./bidirectional-checking.md)** - The two-mode type system
2. **[Unification](./unification.md)** - Solving type constraints
3. **[Implicit Instantiation](./implicit-instantiation.md)** - How they combine for polymorphism

## References

- **Pierce & Turner (1998)**: "Local Type Inference" - Foundation of bidirectional checking
- **Dunfield & Krishnaswami (2013)**: "Complete and Easy Bidirectional Typechecking for Higher-Rank Polymorphism"
- **Wells (1999)**: Proved System F type inference is undecidable
