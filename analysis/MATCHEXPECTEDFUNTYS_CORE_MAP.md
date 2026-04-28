# matchExpectedFunTys: Simplified Core Map

**Status**: Simplified - Core Mechanism Only  
**Last Updated**: 2026-04-09  
**Central Question**: How does type decomposition work through closure passing?

---

## The Core Pattern (No Extensions)

This document shows the **essential mechanism** without:
- ScopedTypeVariables
- DeepSubsumption  
- Linear types (multiplicity)
- All the special cases

---

## The Two Fundamental Paths

### Path A: Function WITH Type Signature

```
tcPolyCheck (for f :: forall a. a -> a)
    ↓
    -- Signature gives us the type directly
    poly_ty = forall a. a -> a
    
    -- SKOLEMISATION HAPPENS HERE (outside)
    tcSkolemise Shallow poly_ty $ \tv_prs rho_ty ->
        -- tv_prs = [(a, a_sk)]
        -- rho_ty = a_sk -> a_sk
        
        -- INVISIBLE types from signature
        invis_pat_tys = [ExpForAllPatTy a_sk]
        
        -- Now decompose rho_ty
        matchExpectedFunTys ... (Check rho_ty) $ \vis_pat_tys res_ty ->
            -- vis_pat_tys = [ExpFunPatTy a_sk]
            -- res_ty = a_sk
            
            -- COMBINE invisible + visible
            all_pat_tys = invis_pat_tys ++ vis_pat_tys
            
            -- Type-check the matches
            tcMatches ... all_pat_tys res_ty matches
```

**Key**: Skolemisation happens **before** matchExpectedFunTys via tcSkolemise

---

### Path B: Function WITHOUT Type Signature

```
tcMonoBinds (for f x = x)
    ↓
    -- No signature, type must be inferred
    exp_ty = fresh unification variable (alpha)
    
    -- SKOLEMISATION HAPPENS INSIDE
    matchExpectedFunTys ... (Infer exp_ty) $ \pat_tys res_ty ->
        -- pat_tys = [ExpFunPatTy beta]  (fresh beta)
        -- res_ty = gamma                  (fresh gamma)
        
        -- Type-check the matches
        tcMatches ... pat_tys res_ty matches
        
        -- After tcMatches fills in beta and gamma,
        -- matchExpectedFunTys fills exp_ty with (beta -> gamma)
```

**Key**: Skolemisation happens **inside** matchExpectedFunTys

---

## The Universal Closure Contract

Every closure passed to the type decomposer follows this pattern:

```haskell
-- THE CONTRACT:
decomposer :: SomeSigmaType 
           -> ([PatternType] -> ResultType -> TcM a)  -- THE CLOSURE
           -> TcM (Wrapper, a)

-- The decomposer does:
-- 1. Decompose the sigma type into pieces
-- 2. Call the closure with those pieces
-- 3. Return a wrapper + the closure's result

-- The closure does:
-- 1. Receive decomposed types
-- 2. Type-check using those types
-- 3. Return the type-checked result
```

---

## What Gets Passed to the Closure

### Types of Pattern Arguments

| Constructor | Meaning | Example |
|-------------|---------|---------|
| `ExpFunPatTy ty` | Visible function argument | `Int` in `Int -> Bool` |
| `ExpForAllPatTy bndr` | Invisible forall binder | `a` in `forall a. a -> a` |

### The Three Decomposers

| Function | Input Type | Closure Receives | When Used |
|----------|------------|------------------|-----------|
| `tcSkolemise` | `TcSigmaType` | `[ExpForAllPatTy]`, `TcRhoType` | Complete signatures |
| `matchExpectedFunTys` | `ExpSigmaType` | `[ExpPatType]`, `ExpRhoType` | Function bindings, lambdas |
| `tcSkolemiseGeneral` | `TcSigmaType` | `[(Name, InvisTVBinder)]`, `TcRhoType` | Internal skolemisation |

---

## Simplified Call Graph

```
TOP LEVEL: Type-checking a function definition
    │
    ├─ Has complete signature?
    │   ├─ YES → tcPolyCheck
    │   │          ↓
    │   │       tcSkolemise (skolemise signature)
    │   │          ↓ invokes closure
    │   │       matchExpectedFunTys (decompose function type)
    │   │          ↓ invokes closure
    │   │       tcMatches (type-check patterns and body)
    │   │
    │   └─ NO → tcMonoBinds
    │             ↓
    │          matchExpectedFunTys (skolemise + decompose)
    │             ↓ invokes closure
    │          tcMatches (type-check patterns and body)
    │
    └─ Lambda expression
          ↓
       tcLambdaMatches
          ↓
       matchExpectedFunTys
          ↓ invokes closure
       tcMatches
```

---

## The Wrapper Story (Simplified)

Every decomposer returns an `HsWrapper` that coerces between types:

```haskell
-- Example: f :: forall a. a -> a with body \x -> x

-- Original type: forall a. a -> a
-- After skolemisation: a_sk -> a_sk

wrapper :: (a_sk -> a_sk) ~~> (forall a. a -> a)
-- This wrapper "re-generalizes" the monomorphic skolemised type
-- back to the polymorphic signature type

-- In Core: 
-- f = /\ @(a :: Type) -> 
--       (\ (x :: a) -> x) |> (Sub (Sym (forall a. a -> a)))
```

---

## Essential Insight

The entire mechanism is about **two-phase type decomposition**:

1. **Phase 1**: Handle invisible binders (`forall a.`, constraints)
   - Creates skolems
   - Brings type variables into scope (if ScopedTypeVariables)
   
2. **Phase 2**: Handle visible binders (function arguments)
   - Decomposes `arg -> res` repeatedly
   - Ensures fixed RuntimeRep

The **closure** is the bridge between these phases - it receives the decomposed pieces and does the actual work.

---

## Without ScopedTypeVariables: Simplification

If we removed ScopedTypeVariables:

```
BEFORE (with ScopedTypeVariables):
tcPolyCheck → tcSkolemise → closure → matchExpectedFunTys → closure → tcMatches

AFTER (without ScopedTypeVariables):
tcPolyCheck ──────────────────→ matchExpectedFunTys → closure → tcMatches
                (skip tcSkolemise, let matchExpectedFunTys handle everything)
```

**Result**: Both paths (with/without signature) would use the same mechanism - `matchExpectedFunTys` would handle all skolemisation internally.

---

## Data Flow Summary (Minimal)

```
Input: Function definition (f x y = body)
       ├─ Maybe signature: forall a b. a -> b -> b
       └─ Match group: [[f, x, y]]

Step 1: Get expected type
        ├─ From signature? Use that type
        └─ No signature? Fresh meta-variable

Step 2: Decompose type
        ├─ Skolemise quantifiers → invisible pattern types
        └─ Peel off function args → visible pattern types

Step 3: Type-check
        └─ Combine all pattern types, type-check body

Step 4: Return
        ├─ Wrapper: coerces between decomposed and original type
        └─ Result: type-checked binding
```

---

## Files and Line Numbers (Reference)

| Concept | File | Lines | Purpose |
|---------|------|-------|---------|
| `matchExpectedFunTys` | Unify.hs | 792-945 | Main type decomposer |
| `tcSkolemise` | Unify.hs | 492-497 | Shallow skolemisation |
| `tcSkolemiseCompleteSig` | Unify.hs | 463-478 | Signature skolemiser |
| `tcFunBindMatches` | Match.hs | 103-137 | Function binding driver |
| `tcLambdaMatches` | Match.hs | 145-171 | Lambda driver |
| `tcPolyCheck` | Bind.hs | 549-627 | Complete signature handler |
| `tcMonoBinds` | Bind.hs | 1289-1399 | No signature handler |

---

## Key Terms (Simplified)

- **Skolem**: A rigid type variable - stands for a specific but unknown type
- **Rho type**: A type with no top-level `forall` (but may have `->`)
- **Sigma type**: A polymorphic type with possible `forall` and constraints
- **Wrapper**: A coercion that transforms one type to another
- **ExpType**: An "expected type" - either a concrete type or a hole to be filled
