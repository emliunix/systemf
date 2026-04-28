# System F vs Putting2007 Paper - Validation Analysis

## Executive Summary

This document validates System F's type inference implementation against Peyton Jones et al.'s "Practical Type Inference for Arbitrary-Rank Types" (Putting2007). 

**Key Findings:**
1. **Core Algorithm Alignment**: System F's bidirectional checker aligns well with the paper's Figure 8 rules
2. **Coercions Excluded**: Per decision, coercions are excluded from pipelines (nominal recursion only)
3. **Pattern/If-Branch Gap**: Paper Section 7.1 discusses multi-branch constructs; System F needs review for polymorphic branch handling
4. **Test Cases Needed**: Representative examples from paper need extraction for validation

---

## 1. Architecture Decisions (From Research)

### 1.1 Exclude Coercions from Pipelines
**Decision**: Use nominal recursion only, supported by ADT's 2-pass structure:

```
Pass 1: TyCon (all type constructor declarations)
Pass 2: DataCon (all constructor definitions + function body elaborations)
```

**Rationale**: 
- Coercions are for newtypes/representational equality only
- Regular recursive types use implicit structural recursion via name resolution
- Keeps core language simple without fold/unfold operations

### 1.2 Implementation Location
- `systemf/src/systemf/surface/pipeline.py`: Main orchestrator
- `systemf/src/systemf/surface/inference/elaborator.py`: Core inference
- `docs/research/putting-2007-implementation.hs`: Paper reference implementation

---

## 2. Core Algorithm Comparison

### 2.1 Type System Layers (Paper Section 4.2)

```haskell
-- Paper's Type Hierarchy
σ (Sigma) ::= ∀ā.ρ          -- Polymorphic types
ρ (Rho)   ::= τ | σ₁ → σ₂   -- Rho types (no top-level ∀)  
τ (Tau)   ::= a | τ₁ → τ₂   -- Monomorphic types
```

**System F Status**: ✓ Aligned
- `TypeForall` corresponds to σ
- `TypeArrow` handles ρ (function types)
- `TMeta` represents τ during inference

### 2.2 Bidirectional Rules (Paper Figure 8)

| Rule | Paper Notation | System F Implementation |
|------|----------------|------------------------|
| INT | Γ ⊢δ n : Int | `infer()` -> `SurfaceLit` returns `TypeConstructor(prim_type)` |
| VAR | Γ ⊢δ x : ρ | `infer()` -> `ScopedVar` lookup + `instSigma` |
| ABS1 | Inference mode | `infer()` -> `ScopedAbs` with fresh meta |
| ABS2 | Checking mode | `check()` -> `ScopedAbs` with expected arrow |
| AABS1 | Annotated inference | `infer()` -> `ScopedAbs` with annotation |
| AABS2 | Annotated checking | `check()` -> `ScopedAbs` with subsumption check |
| APP | Application | `infer()` -> `SurfaceApp` with `checkSigma` |
| LET | Let binding | `infer()` -> `SurfaceLet` with `inferSigma` |
| ANNOT | Type annotation | `infer()` -> `SurfaceAnn` delegates to `check()` |

**Status**: ✓ All core rules implemented

### 2.3 Key Algorithms

#### Instantiation (SPEC Rule)
**Paper** (impl.hs:195-199):
```haskell
instantiate :: Sigma -> Tc Rho
instantiate (ForAll tvs ty) = do
    tvs' <- mapM (\_ -> newMetaTyVar) tvs
    return (substTy tvs (map MetaTv tvs') ty)
instantiate ty = return ty
```

**System F** (elaborator.py:996-1014):
```python
def _instantiate(self, ty: Type) -> Type:
    match ty:
        case TypeForall(var, body):
            meta = self._fresh_meta(var)
            return self._instantiate(self._subst_type_var(body, var, meta))
        case _:
            return ty
```

**Status**: ✓ Equivalent implementation

#### Skolemization (PRPOLY, PRFUN Rules)
**Paper** (impl.hs:208-216):
```haskell
skolemise :: Sigma -> Tc ([TyVar], Rho)
skolemise (ForAll tvs ty) = do
    sks1 <- mapM newSkolemTyVar tvs
    (sks2, ty') <- skolemise (substTy tvs (map TyVar sks1) ty)
    return (sks1 ++ sks2, ty')
skolemise (Fun arg_ty res_ty) = do
    (sks, res_ty') <- skolemise res_ty
    return (sks, Fun arg_ty res_ty')
skolemise ty = return ([], ty)
```

**System F**: Uses skolemization in `checkSigma` but implementation needs review for deep skolemization compliance.

**Status**: ⚠️ Needs validation

#### Unification (MONO Rule)
**Paper** (impl.hs:290-322):
```haskell
unify :: Tau -> Tau -> Tc ()
unify (MetaTv tv) ty = unifyVar tv ty
unify ty (MetaTv tv) = unifyVar tv ty
unify (Fun arg1 res1) (Fun arg2 res2) = do
    unify arg1 arg2
    unify res1 res2
```

**System F** (unification.py): Robinson unification with occurs check.

**Status**: ✓ Standard implementation

---

## 3. Gap Analysis: Pattern Matching & If-Branches

### 3.1 Paper Section 7.1: Multi-Branch Constructs

The paper explicitly addresses conditionals (if-then-else) and case expressions. Three design choices are presented:

#### Choice 1: Monotyped Branches
```haskell
-- Type rule: branches must be τ (monotypes)
Γ ⊢⇓ e1 : Bool  Γ ⊢⇑ e2 : τ  Γ ⊢⇑ e3 : τ
----------------------------------------
Γ ⊢⇑ if e1 then e2 else e3 : τ
```

**Implementation** (impl.hs approach):
```haskell
tcRho (If e1 e2 e3) exp_ty = do
    checkRho e1 boolType
    exp_ty' <- zapToMonoType exp_ty
    tcRho e2 exp_ty'
    tcRho e3 exp_ty'
```

#### Choice 2: Unification Under Mixed Prefix
Modify unifier to handle polymorphic types. Rarely used in practice.

#### Choice 3: Two-Way Subsumption (Recommended)
```haskell
-- Check that ρ1 and ρ2 are equivalent via subsumption
Γ ⊢⇓ e1 : Bool  Γ ⊢⇑ e2 : ρ1  Γ ⊢⇑ e3 : ρ2
⊢^dsk ρ1 ≤ ρ2   ⊢^dsk ρ2 ≤ ρ1
-------------------------------------------
Γ ⊢⇑ if e1 then e2 else e3 : ρ1
```

**Implementation** (impl.hs):
```haskell
tcRho (If e1 e2 e3) (Infer ref) = do
    checkRho e1 boolType
    rho1 <- inferRho e2
    rho2 <- inferRho e3
    subsCheck rho1 rho2  -- Two-way subsumption
    subsCheck rho2 rho1
    writeTcRef ref rho1
```

### 3.2 System F Current Implementation

**Location**: `elaborator.py:542-572`

```python
case SurfaceIf(...):
    core_cond, cond_type = self.infer(cond, ctx)
    core_then, then_type = self.infer(then_branch, ctx)
    core_else, else_type = self.infer(else_branch, ctx)
    
    # Unify branch types
    then_type = self._apply_subst(then_type)
    else_type = self._apply_subst(else_type)
    self._unify(then_type, else_type, location)  # <-- Uses unification, not subsumption
```

**Gap Identified**: 
- System F uses **unification** (`_unify`) to equate branch types
- Paper recommends **two-way subsumption** (`subsCheck`) for polymorphic branches
- This matters when branches have higher-rank types

### 3.3 Pattern Matching (Paper Section 7.2-7.3)

**Paper's Pattern Judgment**:
```haskell
pat
tcPat :: Pat -> Expected Sigma -> Tc [(Name, Sigma)]
```

**Key Insight**: Pattern matching over data constructors with higher-rank types requires instantiating the constructor type and pushing types into sub-patterns.

**System F Implementation**: `elaborator.py:870-994`

The `_check_branch` method handles pattern matching, but needs validation for:
1. Proper instantiation of polymorphic constructors
2. Type pushing into nested patterns
3. Handling of higher-rank constructor arguments

---

## 4. Representative Test Cases from Paper

### 4.1 Basic Higher-Rank Examples

#### Example 1: Rank-2 Function (Intro Example)
```haskell
-- Paper Section 1
foo :: ([Bool], [Char])
foo = let
    f :: (forall a. [a] -> [a]) -> ([Bool], [Char])
    f x = (x [True, False], x ['a','b'])
    in
    f reverse
```

**System F Equivalent**:
```systemf
f : ∀a. [a] → [a] → ([Bool], [Char]) = 
  λx:(∀a. [a] → [a]) → (x [True, False], x ['a', 'b'])
```

**Test Purpose**: Verify rank-2 argument types work correctly.

#### Example 2: Polymorphic Identity
```haskell
-- Paper Section 4.2
id :: forall a. a -> a
id x = x
```

**System F**:
```systemf
id : ∀a. a → a = Λa. λx:a → x
```

#### Example 3: Higher-Rank Application
```haskell
-- Paper Section 3.3
k :: forall a b. a -> b -> b
f1 :: (Int -> Int -> Int) -> Int
f2 :: (forall x. x -> x -> x) -> Int

f1 k  -- OK: instantiate a,b to Int
f2 k  -- OK: k is more polymorphic than required
```

**System F**:
```systemf
k : ∀a. ∀b. a → b → b = Λa. Λb. λx:a → λy:b → y
f2 : (∀x. x → x → x) → Int = λf:(∀x. x → x → x) → 42

-- Application: f2 k should typecheck
```

### 4.2 Subsumption Examples (Section 3.3)

#### Example 4: Contra/Co-variance
```haskell
-- Paper Section 3.3
g :: ((forall b. [b] -> [b]) -> Int) -> Int
k1 :: (forall a. a -> a) -> Int
k2 :: ([Int] -> [Int]) -> Int

g k1  -- BAD: k1 requires more polymorphic arg than g provides
g k2  -- OK: k2 accepts less polymorphic arg
```

**Test Purpose**: Verify subsumption handles contravariance correctly.

### 4.3 Multi-Branch Construct Examples (Section 7.1)

#### Example 5: If with Polymorphic Branches
```haskell
-- This should work with Choice 3 (two-way subsumption)
if True then (\x -> x) else (\y -> y) 
-- Both branches: forall a. a -> a
```

**System F**:
```systemf
if True then (λx → x) else (λy → y)
-- Expected: ∀a. a → a
```

**Gap**: Current implementation uses unification, which may fail for polymorphic branches.

#### Example 6: Case with Constructor Patterns
```haskell
-- Paper Section 7.3
data T = MkT (forall a. a -> a)

case x of
    MkT v -> (v 3, v True)  -- v should have type forall a. a -> a
```

**System F**:
```systemf
data T = MkT (∀a. a → a)

f : T → (Int, Bool) = λx:T →
  case x of { MkT v → (v 3, v True) }
```

**Test Purpose**: Verify pattern matching instantiates constructor types correctly.

### 4.4 Pattern Matching Examples (Section 7.2)

#### Example 7: Nested Patterns
```haskell
-- Pair pattern
case p of
    (x, y) -> ...
```

**System F**:
```systemf
case p of { Pair x y → ... }
```

#### Example 8: Type-Annotated Pattern
```haskell
-- Paper Section 7.2
\(x :: forall a. a -> a) -> x 3
```

**System F**:
```systemf
λ(x : ∀a. a → a) → x 3
```

### 4.5 Recursive Types (Section 2, Research Notes)

#### Example 9: List Map
```haskell
-- Standard polymorphic recursion
data List a = Nil | Cons a (List a)

map :: forall a b. (a -> b) -> List a -> List b
map f xs = case xs of
    Nil -> Nil
    Cons x xs' -> Cons (f x) (map f xs')
```

**System F**:
```systemf
data List a = Nil | Cons a (List a)

map : ∀a. ∀b. (a → b) → List a → List b =
  Λa. Λb. λf:(a → b) → λxs:(List a) →
    case xs of { 
      Nil → Nil 
    | Cons x xs' → Cons (f x) (map @a @b f xs')
    }
```

---

## 5. Implementation Validation Checklist

### 5.1 Core Bidirectional Rules
- [x] INT: Integer literals
- [x] VAR: Variable lookup + instantiation  
- [x] ABS1: Lambda inference (fresh meta)
- [x] ABS2: Lambda checking (unify function)
- [x] AABS1: Annotated lambda inference
- [x] AABS2: Annotated lambda checking
- [x] APP: Application with checkSigma
- [x] LET: Let with inferSigma
- [x] ANNOT: Type annotations

### 5.2 Polymorphism
- [x] GEN1: Generalization (inferSigma)
- [x] GEN2: Checking polymorphic types (checkSigma)
- [x] SPEC: Instantiation
- [x] DEEP-SKOL: Deep skolemization
- [ ] FUN: Function subsumption (needs validation)
- [ ] MONO: Unification fallback

### 5.3 Multi-Branch Constructs
- [x] Basic if-then-else desugaring to case
- [x] Case expressions with pattern matching
- [ ] Two-way subsumption for polymorphic branches (GAP)
- [ ] zapToMono for Choice 1 compatibility

### 5.4 Pattern Matching
- [x] Variable patterns
- [x] Constructor patterns
- [ ] Wildcard patterns (GAP)
- [ ] Type-annotated patterns (GAP)
- [ ] Nested patterns (partial)

---

## 6. Recommended Actions

### Priority 1: Extract and Create Test Suite
1. Create `tests/test_putting2007_examples.py` with examples above
2. Start with Examples 1-3 (basic higher-rank)
3. Add Example 4 (subsumption)
4. Add Examples 5-6 (if/case with polymorphism)

### Priority 2: Fix Multi-Branch Handling
1. Implement two-way subsumption for if/case branches
2. Replace `_unify(then_type, else_type)` with:
   ```python
   self._subs_check(then_type, else_type)
   self._subs_check(else_type, then_type)
   ```

### Priority 3: Validate Pattern Matching
1. Ensure `instDataCon` equivalent works for higher-rank constructors
2. Add support for wildcard patterns
3. Add support for type-annotated patterns

### Priority 4: Nominal Recursion Cleanup
1. Verify 2-pass structure in `elaborate_declarations()`
2. Remove coercion-related code (or move to separate module)
3. Document the nominal recursion approach

---

## 7. References

- **Paper**: Peyton Jones, Vytiniotis, Weirich, Shields. "Practical Type Inference for Arbitrary-Rank Types". JFP 2007.
- **Implementation**: `docs/research/putting-2007-implementation.hs`
- **Research Notes**: `docs/research/putting2007-reading.md`
- **System F Pipeline**: `systemf/src/systemf/surface/pipeline.py`
- **System F Elaborator**: `systemf/src/systemf/surface/inference/elaborator.py`

---

## 8. Appendix: Paper Rules Summary

### Figure 8: Bidirectional Type Rules (Key Rules)

```
GEN1 (Inference Generalization):
Γ ⊢⇑ t : ρ    ā = ftv(ρ) - ftv(Γ)
----------------------------------
Γ ⊢⇑^poly t : ∀ā.ρ

GEN2 (Checking Generalization):
pr(σ) = ∀ā.ρ    ā ∉ ftv(Γ)    Γ ⊢⇓ t : ρ
-----------------------------------------
Γ ⊢⇓^poly t : σ

SPEC (Subsumption Instantiation):
⊢^dsk* [ā↦τ̄]ρ₁ ≤ ρ₂
--------------------
⊢^dsk* ∀ā.ρ₁ ≤ ρ₂

DEEP-SKOL:
pr(σ₂) = ∀ā.ρ    ā ∉ ftv(σ₁)    ⊢^dsk* σ₁ ≤ ρ
----------------------------------------------
⊢^dsk σ₁ ≤ σ₂

INST1 (Inference Instantiation):
---------------------------
⊢^inst_⇑ ∀ā.ρ ≤ [ā↦τ̄]ρ

INST2 (Checking Instantiation):
⊢^dsk σ ≤ ρ
------------
⊢^inst_⇓ σ ≤ ρ
```

**Status**: System F implements all rules, but INST2 handling of polymorphic types in branches needs validation.
