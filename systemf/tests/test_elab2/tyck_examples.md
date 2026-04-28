# Bidirectional Type Checker Test Specification

Based on "Practical Type Inference for Arbitrary-Rank Types" (Peyton Jones et al., 2007)

## Notation

- **Source types**: `τ` (monomorphic), `σ` (polymorphic), `ρ` (weak prenex)
- **Core terms**: `e` (System F terms)
- **Wrappers**: `f` (coercions as wrapper structures)
- **Skolems**: `sk_a`, `sk_b` (rigid type constants)
- **Metas**: `?1`, `?2` (unification variables)

---

## Meta Variables vs Skolem Variables

This is a **critical distinction** in higher-rank type inference.

### Meta Variables (`?1`, `?2`, ...)

| Property | Description |
|----------|-------------|
| **Nature** | Unification variables (unknown types to be determined) |
| **Behavior** | Can be **unified** with any type via substitution |
| **Use Case** | Type inference for unknown types |
| **Example** | Inferring `λx.x` creates `?1 → ?1`, then `?1` is generalized to `∀a.a→a` |

**Key operation**: `unify(?1, Int)` succeeds by substituting `?1 ↦ Int`.

### Skolem Variables (`sk_a`, `sk_b`, ...)

| Property | Description |
|----------|-------------|
| **Nature** | Rigid type constants (represent "some specific but unknown type") |
| **Behavior** | **Cannot be unified** — they are rigid! |
| **Use Case** | Checking polymorphic types (subsumption, skolemization) |
| **Example** | Checking against `∀a.a→a` creates `sk_a → sk_a` where `sk_a` is rigid |

**Key operation**: `unify(sk_a, Int)` **FAILS** — `sk_a` is rigid and cannot be substituted.

### Why the Distinction Matters

**Meta variables** are for **inference** (discovering types):
- `λx.x` infers as `?1 → ?1`
- Later we learn `?1 = Int` from context
- We substitute and get `Int → Int`

**Skolem variables** are for **checking** (verifying subsumption):
- Checking `Int → Int ≤ ∀a.a → a`
- Skolemize: check `Int → Int ≤ sk_a → sk_a`
- `sk_a` is rigid — we **cannot** set `sk_a = Int`
- Instead, we check that `Int` and `sk_a` are **compatible as types**
- The wrapper records this relationship

### Common Mistake

```python
# WRONG: Thinking skolem can be unified
sk_a = make_skolem("a")
unify(sk_a, Int)  # ERROR: sk_a is rigid!

# CORRECT: Rigid equality check
check_equal(sk_a, Int)  # Verifies they're the same type (post-zonking)
```

### Anti-Test: `test_skolem_cannot_unify`

This test verifies that unification **fails** with skolem variables:

```python
sk_a = make_skolem("a")
unify(sk_a, Int)  # Raises TypeError: rigid type variable
```

**Expected behavior**: The type checker must throw an error when attempting to unify a skolem. This ensures the rigidity invariant is maintained.

**Why this matters**: If skolems could be unified, the distinction between `?1` (inference) and `sk_a` (checking) would collapse, breaking higher-rank type inference.

### In DEEP-SKOL

When checking `σ₁ ≤ σ₂`:
1. Skolemize `σ₂` to get `ρ₂` with skolems `ā`
2. Check `σ₁ ≤ ρ₂` with **rigid equality** (not unification)
3. The skolems represent the "forall-bound" positions
4. Wrapper converts the witness from `ρ₂` back to `σ₂`

---

## Wrapper Notation

A concise syntax for describing wrapper constructions in subsumption derivations.

### Variables

| Notation | Meaning |
|----------|---------|
| `m_a` | Meta variable created by instantiating `∀a` (from forall var `a`) |
| `m_1`, `m_2` | Fresh meta variables created during inference (numbered) |
| `s_a`, `s_b` | Skolem constants created from `∀a`, `∀b` during skolemization |

### Wrapper Operators

| Notation | Meaning | Wrapper Type |
|----------|---------|--------------|
| `ID` | Identity wrapper (no-op) | `WpHole` |
| `w1 <*> w2` | Compose wrappers left-to-right | `wp_compose(w1, w2)` |
| `t1 ~~> t2` | A wrapper translating terms of type `t1` to terms of type `t2` | — |
| `a ~ b` | Cast from type `a` to type `b` | `WpCast(a, b)` |
| `Fun(t, w_arg, w_res)` | Eta-expansion wrapper | `WpFun(t, w_arg, w_res)` |
| `TyLam(tv)` | Type abstraction | `WpTyLam(tv)` |
| `TyApp(t)` | Type application | `WpTyApp(t)` |

### Usage

**Wrapper type**: `σ₁ ~~> σ₂` denotes a coercion that transforms a term of type `σ₁` into a term of type `σ₂`.

**Composition**: The `<*>` operator composes wrappers sequentially:
```
(σ1 ~~> σ2) <*> (σ2 ~~> σ3)  =  (σ1 ~~> σ3)
```

**Example**: The subsumption check `∀ab.a→b→b ≤ ∀a.a→(∀b.b→b)` produces:
```
TyLam(s_a) <*> Fun(s_a, ID, TyLam(s_b) <*> Fun(s_b, ID, ID))
    <*> TyApp(m_b) <*> TyApp(m_a)
    : (∀ab.a→b→b ~~> ∀a.a→(∀b.b→b))
```

Where:
- `TyApp(m_b) <*> TyApp(m_a)` instantiates LHS to `m_a → m_b → m_b` (outer forall b wraps inner forall a)
- `TyLam(s_a) <*> ...` abstracts the skolemized RHS `s_a → s_b → s_b`
- The `Fun` wrappers handle function structure (eta expansion)

---

## Utility Rules — Wrapper Semantics

Wrapper-producing utility judgments and their semantic interpretation.

### Instantiate — `inst(σ) → (ρ, w)`

Produces a wrapper `w : σ ~~> ρ` that instantiates polymorphic types to monomorphic ones.

| Rule | Input `σ` | Output `ρ` | Wrapper `w` | Semantics |
|------|-----------|------------|-------------|-----------|
| **INST-MONO** | `τ` (no ∀) | `τ` | `ID` | Identity, no instantiation needed |
| **INST-POLY** | `∀a.ρ` | `ρ[m_a/a]` | `TyApp(m_a) <*> w_inner` | Instantiate `∀a` with fresh meta `m_a` |

**Example**: `inst(∀a.a→a) = (m_a→m_a, TyApp(m_a))`

**Direction**: The wrapper takes a term of the polymorphic type and produces a term of the instantiated type:
```
e : ∀a.a→a  ──TyApp(m_a)──>  e[m_a] : m_a→m_a
```

---

### Skolemize — `skolemise(σ) → (ρ, w)`

Produces a wrapper `w : ρ ~~> σ` that abstracts skolemized types back to polymorphic form.

| Rule | Input `σ` | Output `ρ` | Skolems | Wrapper `w` | Semantics |
|------|-----------|------------|---------|-------------|-----------|
| **SK-MONO** | `τ` | `τ` | `[]` | `ID` | Identity, no foralls to skolemize |
| **SK-POLY** | `∀a.ρ` | `ρ[s_a/a]` | `[s_a] ++ ss` | `TyLam(s_a) <*> w_inner` | Abstract `s_a` back to `∀a` |
| **SK-FUN** | `σ₁→σ₂` | `σ₁→ρ₂` | `ss` | `Fun(σ₁, ID, w_res)` | Eta-expand, delegate to result |

Where `w_inner` comes from recursive skolemization and `w_res = skolemise(σ₂)` when `σ₂` has prenex foralls.

**Direction**: The wrapper takes a term of the skolemized type and produces a term of the polymorphic type:
```
e : s_a→s_a  ──TyLam(s_a)──>  Λs_a.e : ∀a.a→a
```

**Critical distinction**: `skolemise` produces a wrapper in the **opposite direction** from `inst`:
- `inst` : `σ ~~> ρ` (polymorphic → monomorphic via instantiation)
- `skolemise` : `ρ ~~> σ` (skolemized → polymorphic via abstraction)

---

### Subsumption — `subs_check(σ₁, σ₂) → w` / `subs_check_rho(ρ₁, ρ₂) → w`

Produces a wrapper `w : σ₁ ~~> σ₂` witnessing that `σ₁` is at least as polymorphic as `σ₂`.

| Rule | Condition | Result Wrapper | Semantics |
|------|-----------|----------------|-----------|
| **SUBS-SPEC** | `σ₁ = ∀a.ρ₁` | `w_inner <*> TyApp(m_a)` | Instantiate LHS, continue |
| **SUBS-SKOL** | `σ₂ = ∀a.ρ₂` | `TyLam(s_a) <*> w_inner` | Skolemize RHS, abstract result |
| **SUBS-RHO** | Both rho | `subs_check_rho(ρ₁, ρ₂)` | Delegate to rho-checking |
| **SUBS-FUN** | `σ₁→σ₂ ≤ σ₃→ρ₄` | `Fun(σ₃, w_arg, w_res)` | Eta-expansion with contravariant arg |
| **SUBS-MONO** | `τ₁ = τ₂` | `ID` | Types unify, identity wrapper |

Where:
- `w_arg : σ₃ ~~> σ₁` (contravariant — argument types flip)
- `w_res : σ₂ ~~> ρ₄` (covariant — result types same direction)

**Composition structure**:
```
subs_check(∀ab.a→b→b, ∀a.a→(∀b.b→b))
  = skolemise_wrapper <*> subs_check_rho_wrapper <*> inst_wrapper
  = (TyLam(s_a) <*> Fun(s_a, ID, TyLam(s_b) <*> Fun(s_b, ID, ID)))
    <*> Fun(s_a, ID, Fun(s_b, ID, ID))
    <*> (TyApp(m_b) <*> TyApp(m_a))  -- outer forall b wraps inner forall a
  : (∀ab.a→b→b ~~> ∀a.a→(∀b.b→b))
```

---

## Figure 9: Subsumption and Skolemization (PR Rules)

### PRMONO — Monomorphic Type

| Aspect | Value |
|--------|-------|
| **Rule** | `pr(τ) = τ ↦ λx.x` |
| **Input** | `Int` |
| **Skolems** | `[]` |
| **Output Type** | `Int` |
| **Wrapper** | `WP_HOLE` |
| **Test** | `test_skolemise_mono` |

---

### PRPOLY — Polymorphic Type

#### Simple Case: `∀a. a → a`

| Aspect | Value |
|--------|-------|
| **Rule** | `pr(∀a.ρ) = ∀a.pr(ρ)` with wrapper composition |
| **Input** | `∀a. a → a` |
| **Skolems** | `[sk_a]` |
| **Output Type** | `sk_a → sk_a` |
| **Inner (PRFUN)** | `WpFun(sk_a, WP_HOLE, WP_HOLE)` |
| **Outer (PRPOLY)** | `WpCompose(WpTyLam(sk_a), WpFun(...))` |
| **Test** | `test_skolemise_prpoly` |

#### Nested: `∀a. ∀b. a → b → a`

| Aspect | Value |
|--------|-------|
| **Input** | `∀a. ∀b. a → b → a` |
| **Skolems** | `[sk_a, sk_b]` |
| **Output Type** | `sk_a → sk_b → sk_a` |
| **Innermost** | `WpFun(sk_b, WP_HOLE, WP_HOLE)` (PRFUN on `sk_b → sk_a`) |
| **Middle** | `WpFun(sk_a, WP_HOLE, inner)` (PRFUN on `sk_a → (sk_b → sk_a)`) |
| **Wrapper** | `WpCompose(WpTyLam(sk_a), WpCompose(WpTyLam(sk_b), middle))` |
| **Test** | `test_skolemise_nested` |

---

### PRFUN — Function Type with Prenex Result

#### Case: `Int → ∀a. a`

| Aspect | Value |
|--------|-------|
| **Rule** | `pr(σ₂) = ∀ā.ρ₂ ↦ f  /  pr(σ₁→σ₂) = ∀ā.(σ₁→ρ₂) ↦ λx.λy.f(x[ā]y)` |
| **Input** | `Int → ∀a. a` |
| **Skolems** | `[sk_a]` |
| **Output Type** | `Int → sk_a` |
| **Inner (PRPOLY)** | `WpTyLam(sk_a)` (simplified from `WpCompose(WpTyLam(sk_a), WP_HOLE)`) |
| **Wrapper** | `WpFun(Int, WP_HOLE, WpTyLam(sk_a))` |
| **Test** | `test_skolemise_prfun` |

#### Case: `(∀a. a→a) → Int` (Polymorphic Argument)

| Aspect | Value |
|--------|-------|
| **Input** | `(∀a. a→a) → Int` |
| **Skolems** | `[]` (forall in contravariant position, not prenex) |
| **Output Type** | `(∀a. a→a) → Int` (unchanged) |
| **Wrapper** | `WpFun(∀a.a→a, WP_HOLE, WP_HOLE)` (identity) |
| **Test** | `test_skolemise_prfun_poly_arg` |

---

### Complex Case: `∀a. a → ∀b. b → a`

| Aspect | Value |
|--------|-------|
| **Input** | `∀a. a → ∀b. b → a` |
| **Structure** | `∀a. (a → ∀b. (b → a))` |
| **Skolems** | `[sk_a, sk_b]` |
| **Output Type** | `sk_a → sk_b → sk_a` |
| **Innermost** | `WpFun(sk_b, WP_HOLE, WP_HOLE)` (PRFUN on `sk_b → sk_a`) |
| **Inner PRPOLY** | `WpCompose(WpTyLam(sk_b), innermost)` |
| **Middle PRFUN** | `WpFun(sk_a, WP_HOLE, inner_prpoly)` |
| **Outer PRPOLY** | `WpCompose(WpTyLam(sk_a), middle_prfun)` |
| **Test** | `test_skolemise_complex` |

---

## Wrapper Structure Summary

### Construction Rules

```
PRMONO(τ):     WP_HOLE

PRPOLY(∀a.ρ):  WpCompose(WpTyLam(sk_a), inner_wrap)
               where inner_wrap = pr(ρ)[sk_a/a]

PRFUN(σ₁→σ₂):  WpFun(σ₁, WP_HOLE, inner_wrap)
               where inner_wrap = pr(σ₂) if σ₂ has prenex foralls
```

### Simplification Rule

After construction, `WpCompose` is simplified:
- `WpCompose(w, WP_HOLE)` → `w`
- `WpCompose(WP_HOLE, w)` → `w`

This ensures minimal wrapper representation while preserving correctness.

### Examples with Simplification

| Type | Before Simplification | After Simplification |
|------|----------------------|----------------------|
| `∀a. a` | `WpCompose(WpTyLam(sk_a), WP_HOLE)` | `WpTyLam(sk_a)` |
| `Int → ∀a. a` | `WpFun(Int, WP_HOLE, WpCompose(WpTyLam(sk_a), WP_HOLE))` | `WpFun(Int, WP_HOLE, WpTyLam(sk_a))` |
| `∀a. a → a` | `WpCompose(WpTyLam(sk_a), WpFun(sk_a, WP_HOLE, WP_HOLE))` | *unchanged* (no WP_HOLE)

---

## INST — Instantiation Judgment

The `inst` method implements bidirectional instantiation (INST1/INST2 rules).

### INST1 — Infer Mode

| Input Type | Mode | Instantiated Type | Wrapper |
|------------|------|-------------------|---------|
| `∀a. a` | Infer | `?1` | `WpTyApp(?1)` |
| `Int` | Infer | `Int` | `WP_HOLE` |

### INST2 — Check Mode

| Input Type | Check Against | Wrapper |
|------------|---------------|---------|
| `∀a. a → a` | `Int → Int` | `WpTyApp(Int)` |

**Note**: Contravariant argument position triggers unification (`?1 := Int`).

---

## Figure 8: Bidirectional Type Checking Rules

Type-driven elaboration from source terms to System F core terms.

---

### INT — Integer Literal

**Rule**: Literals synthesize their type directly.

| Field | Value |
|-------|-------|
| **Rule** | INT |
| **Source** | `42` |
| **Mode** | Infer |
| **Expected Type** | `Int` |
| **Core Term** | `42` |
| **Wrapper** | `WP_HOLE` |
| **Test** | `test_int_literal` |

**Key Insight**: Literals are the base case—no computation, just return their fixed type.

---

### VAR — Variable Lookup

**Rule**: Look up variable in context, then instantiate polymorphic type.

| Field | Value |
|-------|-------|
| **Rule** | VAR |
| **Context** | `Γ = {id : ∀a.a→a}` |
| **Source** | `id` |
| **Mode** | Infer against `?1→?1` |
| **Expected Type** | `?1→?1` (after instantiation) |
| **Core Term** | `id[?1]` (type application) |
| **Test** | `test_var_simple`, `test_var_poly` |

**Key Insight**: Polymorphic variables are instantiated at use site via fresh metas.

---

### ABS1 — Lambda Inference

**Rule**: Infer lambda by creating fresh meta for argument, inferring body.

| Field | Value |
|-------|-------|
| **Rule** | ABS1 |
| **Source** | `λx.x` |
| **Mode** | Infer |
| **Argument Type** | Fresh meta `?1` |
| **Body Type** | `?1` (from `x` in context) |
| **Result Type** | `?1→?1` |
| **Core Term** | `λx:?1.x` |
| **Test** | `test_abs1_identity` |

**Key Insight**: ABS1 creates a fresh meta and lets unification discover the type.

---

### ABS2 — Lambda Checking

**Rule**: Check lambda against known function type.

| Field | Value |
|-------|-------|
| **Rule** | ABS2 |
| **Source** | `λx.x` |
| **Mode** | Check against `Int→Int` |
| **Decomposed** | Arg=`Int`, Res=`Int` |
| **Check Body** | `x` against `Int` (with `x:Int` in context) |
| **Result Type** | `Int→Int` |
| **Core Term** | `λx:Int.x` |
| **Test** | `test_abs2_identity` |

**Key Insight**: ABS2 decomposes the expected type and checks components.

---

### AABS1 — Annotated Lambda (Inference)

**Rule**: Lambda with explicit type annotation (infer mode).

| Field | Value |
|-------|-------|
| **Rule** | AABS1 |
| **Source** | `λx:Int.x` |
| **Mode** | Infer |
| **Annotation** | `Int` (arg type known) |
| **Body Check** | `x` against `Int` |
| **Result Type** | `Int→Int` |
| **Core Term** | `λx:Int.x` |
| **Test** | `test_aabs1_simple` |

**Key Insight**: Annotation provides the argument type; body is checked against result.

---

### AABS2 — Annotated Lambda (Checking)

**Rule**: Lambda with annotation, checked against expected type (may need coercion).

| Field | Value |
|-------|-------|
| **Rule** | AABS2 |
| **Source** | `λx:(∀a.a→a).x` |
| **Mode** | Check against `(Int→Int)→(Int→Int)` |
| **Annotation** | `∀a.a→a` (more polymorphic than expected) |
| **Arg Check** | Subsumption: `Int→Int ≤ ∀a.a→a` |
| **Core Term** | With coercion wrapper |
| **Test** | `test_aabs2_subsumption` |

**Key Insight**: Annotation may be more polymorphic than expected—requires subsumption.

---

### APP — Application

**Rule**: Infer function type, check argument, return result.

| Field | Value |
|-------|-------|
| **Rule** | APP |
| **Source** | `id 42` |
| **Context** | `id : ∀a.a→a` |
| **Fun Inferred** | `?1→?1` (instantiated) |
| **Arg Checked** | `42` against `?1` (unifies `?1=Int`) |
| **Result Type** | `Int` |
| **Core Term** | `id[Int] 42` |
| **Test** | `test_app_simple`, `test_app_poly` |

**Key Insight**: Application combines inference (fun), checking (arg), and unification.

---

### ANNOT — Type Annotation

**Rule**: Check term against annotated type, elaborates to polymorphic core.

| Field | Value |
|-------|-------|
| **Rule** | ANNOT |
| **Source** | `(λx.x :: ∀a.a→a)` |
| **Annotation** | `∀a.a→a` |
| **Skolemized** | `sk_a→sk_a` (for checking) |
| **Check Body** | `λx.x` against `sk_a→sk_a` |
| **Result Type** | `∀a.a→a` |
| **Core Term** | `Λsk_a.λx:sk_a.x` |
| **Test** | `test_annot_poly` |

**Key Insight**: Annotation uses skolemization to check polymorphic types.

---

### LET — Let Binding

**Rule**: Generalize binding type, extend context, check body.

| Field | Value |
|-------|-------|
| **Rule** | LET |
| **Source** | `let id = λx.x in id 42` |
| **Binding Inferred** | `id : ?1→?1` |
| **Generalized** | `id : ∀a.a→a` (free vars in Γ only) |
| **Body Checked** | `id 42` with `id:∀a.a→a` in context |
| **Result Type** | `Int` |
| **Core Term** | `let id = Λa.λx:a.x in id[Int] 42` |
| **Test** | `test_let_generalization`, `test_let_poly` |

**Key Insight**: LET is where polymorphism is introduced via generalization.

---

### GEN1 — Generalization (Inference Mode)

**Rule**: Generalize free metas not in context to foralls.

| Field | Value |
|-------|-------|
| **Rule** | GEN1 |
| **Source** | `λx.x` |
| **Inferred Type** | `?1→?1` |
| **Context** | `ftv(Γ) = ∅` (no free type vars) |
| **Generalized** | `∀a.a→a` |
| **Core Term** | `Λa.λx:a.x` |
| **Test** | `test_gen1_simple` |

**Key Insight**: GEN1 quantifies over metas that don't escape into the context.

---

### GEN2 — Generalization (Checking Mode)

**Rule**: Check against polymorphic type using skolemization.

| Field | Value |
|-------|-------|
| **Rule** | GEN2 |
| **Source** | `λx.x` |
| **Check Against** | `∀a.a→a` |
| **Skolemized** | `sk_a→sk_a` |
| **Check Body** | `λx.x` against `sk_a→sk_a` |
| **Result Type** | `∀a.a→a` |
| **Core Term** | `Λsk_a.λx:sk_a.x` |
| **Test** | `test_gen2_skolem` |

**Key Insight**: GEN2 uses skolemization to verify a term works for all types.

---

## Subsumption Rules

**Notation**: `σ₁ ≤ σ₂` means σ₁ is at least as polymorphic as σ₂ (σ₁ can be used where σ₂ is expected).

### MONO — Monomorphic Base Case

Direct unification when both types are monomorphic.

| Test | Coverage | Wrapper |
|------|----------|---------|
| `Int ≤ Int` | Identity | `WP_HOLE` |

---

### SPEC — Instantiate Left (LHS is ∀, RHS is ρ)

When LHS has outer foralls, instantiate with fresh metas.

| Test | Coverage | Wrapper |
|------|----------|---------|
| `∀a.a ≤ Int` | Simple instantiation | `WpTyApp(Int)` |
| `∀a.a → a ≤ Int → Int` | Instantiate in function | `WpTyApp(Int)` |
| `∀a.∀b.a → b ≤ Int → String` | Nested foralls | `WpCompose(WpTyApp(Int), WpTyApp(String))` |
| `Bool → (∀a.a → a) ≤ Bool → Int → Int` | Paper §4.6.2: instantiate nested ∀ in result | `WpTyApp(Int → Int)` |

---

### FUN — Function Subsumption (Contravariant Arg, Covariant Res)

For `σ₁ → σ₂ ≤ σ₃ → ρ₄`:
- **Arg**: `σ₃ ≤ σ₁` (flipped! contravariant)
- **Res**: `σ₂ ≤ ρ₄` (same direction, covariant)

| Test | Arg Check | Res Check | Wrapper |
|------|-----------|-----------|---------|
| `Int → String ≤ Int → String` | `Int ≤ Int` | `String ≤ String` | `WpFun(Int, WP_HOLE, WP_HOLE)` |
| `(Int→Int) → String ≤ (∀a.a→a) → String` | `∀a.a→a ≤ Int→Int` ✓ | `String ≤ String` | `WpFun(∀a.a→a, WpTyApp(Int), WP_HOLE)` |
| `(Int → Int) → Bool ≤ (∀a.a → a) → Bool` | Paper §4.6.2: contravariant arg | `Bool ≤ Bool` | `WpFun(∀a.a→a, WpTyApp(Int), WP_HOLE)` |

**Key insight**: A function accepting *polymorphic* arguments can be used where a function accepting *monomorphic* arguments is expected. The caller provides monomorphic, the function accepts polymorphic.

---

### DEEP-SKOL — Skolemize Right (RHS is ∀)

When RHS has foralls, skolemize to rigid constants and check subsumption. Uses **weak prenex conversion** `pr(σ)` to float ∀s from result position.

| Test | LHS | RHS (skolemized) | Result |
|------|-----|------------------|--------|
| `∀a.a → a ≤ ∀b.b → b` | `?1 → ?1` | `sk_b → sk_b` | unifies `?1 := sk_b` ✓ |
| `∀a.∀b.a → b ≤ ∀a.a → a` | `?1 → ?2` | `sk_a → sk_a` | fails: `?2 ≠ sk_a` (rigid) |
| `∀a.∀b.a → b ≤ ∀a.a → Int` | `?1 → ?2` | `sk_a → sk_a` | fails: `sk_a ≠ Int` (rigid) |

**Weak Prenex Equivalences** (Paper §4.6.2): These type pairs are equivalent under deep skolemization because `pr(∀a.a → (∀b.b → b)) = ∀ab.a → b → b`.

| Test | Direction | pr(RHS) | Result |
|------|-----------|---------|--------|
| `∀ab.a → b → b ≤ ∀a.a → (∀b.b → b)` | Forward | `∀ab.a → b → b` (already prenex) | ✓ |
| `∀a.a → (∀b.b → b) ≤ ∀ab.a → b → b` | Reverse | `∀ab.a → b → b` (floats ∀b) | ✓ |

---

### Anti-Tests (Must Fail)

| Test | Why It Fails |
|------|--------------|
| `Int ≤ ∀a.a` | RHS skolemizes to `sk_a`; `sk_a ≠ Int` (rigid) |
| `Int → String ≤ Int → Bool` | Different result types |
| `(∀a.a→a) → Int ≤ (Int→Int) → Int` | Arg check: `Int→Int ≤ ∀a.a→a` fails (not more polymorphic) |
| `Int → Int ≤ ∀a.a → a` | RHS skolemizes to `sk_a → sk_a`; `sk_a ≠ Int` (rigid) |
| `String ≤ Int` | Different types |

---

## Documentation Style Guide

### Separation of Concerns

This test suite uses a **two-tier documentation approach**:

| Location | Purpose | Content |
|----------|---------|---------|
| `tyck_examples.md` (this file) | **Full specification** | Detailed rule explanations, derivation steps, wrapper constructions, rationale |
| `test_*.py` | **Concise reference** | Rule identifier + pointer to spec |

### Docstring Convention

Test docstrings should be **minimal but informative**:

```python
def test_skolemise_prpoly():
    """PRPOLY: pr(∀a. a → a) = sk_a → sk_a ↦ Λsk_a

    Polymorphic type skolemizes to rigid variables with type lambda wrapper.
    """
```

**Pattern**: `<RULE>: <brief description>` followed by one-line insight.

### Why This Style?

1. **Single source of truth**: Detailed documentation lives in one place
2. **DRY principle**: Avoid duplicating specs across test files
3. **Maintainability**: Update spec in one place, tests stay clean
4. **Readability**: Tests are readable without scrolling through paragraphs
5. **Reference integrity**: Tests link to specific sections for traceability

### Adding New Tests

When adding a new test:

1. **Document in tyck_examples.md first**:
   - Add a new section under the appropriate rule category
   - Include the full derivation, wrapper structure, and rationale

2. **Write minimal test docstring**:
   - Identify the rule (e.g., PRPOLY, DEEP-SKOL)
   - Brief description of what the test checks
   - One-line insight or expected behavior

3. **Example**:
   ```python
   def test_new_case():
       """RULE-NAME: what the test verifies

       Key insight or expected outcome.
       """
   ```

This ensures the specification is comprehensive while keeping the test code focused and maintainable.