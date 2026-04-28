# Trace: deeplySkolemise on Nested Forall Type

## Example Type

**Input**: `σ = ∀a. a → ∀b. b → a`

**Prenex form**: `∀a b. a → b → a`

This document traces GHC's `deeplySkolemise` function step by step, showing both type conversion and wrapper construction.

---

## Thread 1: Type Conversion

### Initial State

```
ty = ∀a. a → ∀b. b → a
subst = empty
```

### Step 1: First Call to `tcDeepSplitSigmaTy_maybe`

**Input**: `∀a. a → ∀b. b → a`

`tcSplitSigmaTyBndrs` extracts:
- `tvs = [a]` (binder for `a`)
- `theta = []` (no constraints)
- `rho = a → ∀b. b → a`

**Result**: `Just ([], [a], [], a → ∀b. b → a)`

- `arg_tys = []` (no function args yet)
- `bndrs = [a]` (the forall binder)
- `theta = []`
- `ty' = a → ∀b. b → a` (rest of type)

### Step 2: Create Skolem for `a`

```haskell
(subst', bndrs1) <- tcInstSkolTyVarBndrsX skol_info subst [a]
```

- `subst' = [a := s₁]` (s₁ is fresh skolem)
- `bndrs1 = [s₁]` (skolem binder)

**Apply substitution**:
- `arg_tys' = []` (nothing to substitute)
- `ty' with subst' = s₁ → ∀b. b → s₁`

### Step 3: Recursive Call to `go`

**Input**: `ty = s₁ → ∀b. b → s₁` (with substitution `[a := s₁]`)

`tcSplitFunTy_maybe` splits:
- `arg_ty = s₁`
- `res_ty = ∀b. b → s₁`

Then `go res_ty` calls `tcDeepSplitSigmaTy_maybe` on `∀b. b → s₁`:

`tcSplitSigmaTyBndrs` extracts:
- `tvs = [b]`
- `theta = []`
- `rho = b → s₁`

**Result**: `Just ([], [b], [], b → s₁)`

### Step 4: Create Skolem for `b`

```haskell
(subst'', bndrs2) <- tcInstSkolTyVarBndrsX skol_info subst' [b]
```

- `subst'' = [a := s₁, b := s₂]`
- `bndrs2 = [s₂]`

**Apply substitution**:
- `ty' with subst'' = s₂ → s₁`

### Step 5: Recursive Call to `go` (Base Case)

**Input**: `ty = s₂ → s₁`

`tcSplitFunTy_maybe` splits:
- `arg_ty = s₂`
- `res_ty = s₁`

`go s₁`:
- `tcDeepSplitSigmaTy_maybe s₁ = Nothing` (no foralls)
- Returns: `(idHsWrapper, [], [], s₁)`

### Step 6: Unwind Recursion - Second Level

Back to processing `b → s₁`:

```haskell
return ( mkWpEta (b → s₁) [id_b] (mkWpTyLams [s₂] <.> idHsWrapper)
       , [b := s₂]
       , []
       , mkScaledFunTys [s₂] s₁ )  -- = s₂ → s₁
```

**Result at this level**:
- `wrap = mkWpEta (b → s₁) [id_b] (WpTyLam s₂)`
- `tvs_prs = [b := s₂]`
- `ev_vars = []`
- `rho = s₂ → s₁`

### Step 7: Unwind Recursion - First Level

Back to processing `a → ∀b. b → a`:

```haskell
return ( mkWpEta (s₁ → ∀b. b → s₁) [id_a] 
                  (WpTyLam s₁ <.> wrap_from_level_2)
       , [a := s₁] ++ [b := s₂]
       , []
       , mkScaledFunTys [s₁] (s₂ → s₁) )  -- = s₁ → s₂ → s₁
```

**Final type conversion**:
- Input: `∀a. a → ∀b. b → a`
- Output: `s₁ → s₂ → s₁` (rho type with skolems)

---

## Thread 2: Wrapper Construction

### Step 1: Deepest Level (Base Case)

**Type**: `s₁` (result type)

```haskell
return (idHsWrapper, [], [], s₁)
```

**Wrapper**: `WpHole` (identity)

### Step 2: Wrapper for `b` Level

**Type**: `b → s₁` becomes `s₂ → s₁`

`mkWpEta` creates:

```haskell
mkWpEta (b → s₁) [id_b] (WpTyLam s₂)
  = WpFun { mult_co = reflexive
          , arg_wrap = WpHole
          , res_wrap = WpTyLam s₂
          , arg_type = b   -- becomes s₂
          , res_type = s₁ }
```

**Meaning**: 
```
λ(y : s₂). (WpTyLam s₂) [id_b y]
= λ(y : s₂). Λs₂. y
```

Wait - that's not right. Let me trace `mkWpEta` more carefully.

### Correct Trace of mkWpEta

From `GHC/Tc/Types/Evidence.hs:428-445`:

```haskell
mkWpEta orig_fun_ty xs wrap = go orig_fun_ty xs
  where
    go _      []       = wrap
    go fun_ty (id:ids) =
      WpFun { mult_co = ...
            , arg_wrap = idHsWrapper
            , res_wrap = go res_ty ids
            , arg_type = idType id
            , res_type = res_ty }
      where res_ty = funResultTy fun_ty
```

For `mkWpEta (b → s₁) [id_b] (WpTyLam s₂)`:

1. `go (b → s₁) [id_b]`:
   - `res_ty = s₁`
   - Returns: `WpFun { arg_wrap = id, res_wrap = go s₁ [], ... }`

2. `go s₁ []`:
   - Returns: `WpTyLam s₂`

**Result**:
```
WpFun { arg_wrap = WpHole
      , res_wrap = WpTyLam s₂
      , arg_type = b
      , res_type = s₁ }
```

**Desugaring**:
```haskell
(WpFun {arg_wrap=id, res_wrap=WpTyLam s₂}) [e]
= λ(y : s₂). (WpTyLam s₂) [e y]
= λ(y : s₂). Λs₂. (e y)
```

### Step 3: Wrapper for `a` Level (Top)

**Type**: `a → ∀b. b → a` becomes `s₁ → s₂ → s₁`

```haskell
mkWpEta (a → (∀b. b → a)) [id_a] (WpTyLam s₁ <.> wrap_b)
```

Where `wrap_b` is the wrapper from Step 2.

**Composition**:
```
WpTyLam s₁ <.> wrap_b 
= WpCompose (WpTyLam s₁) wrap_b
```

**Full wrapper construction**:
```
WpFun { arg_wrap = WpHole
      , res_wrap = WpCompose (WpTyLam s₁) wrap_b
      , arg_type = a
      , res_type = ∀b. b → a }
```

### Final Wrapper Structure

```
WpFun
  { arg_wrap = WpHole
  , res_wrap = WpCompose
                 (WpTyLam s₁)
                 (WpFun
                   { arg_wrap = WpHole
                   , res_wrap = WpTyLam s₂
                   , arg_type = s₂
                   , res_type = s₁ })
  , arg_type = s₁
  , res_type = s₂ → s₁ }
```

### Wrapper Application

When applied to `e :: s₁ → s₂ → s₁`:

```haskell
wrap e = λ(x : s₁). Λs₁. 
          (λ(y : s₂). Λs₂. e x y)
```

**Step by step**:
1. `WpFun` takes `e` and creates `λ(x : s₁). ...`
2. `WpTyLam s₁` abstracts: `Λs₁. (inner_wrapper [e x])`
3. Inner `WpFun` creates `λ(y : s₂). ...`
4. Inner `WpTyLam s₂` abstracts: `Λs₂. (e x y)`

**Final elaboration**:
```haskell
Λs₁. λ(x : s₁). Λs₂. λ(y : s₂). e x y
  :: ∀s₁. s₁ → ∀s₂. s₂ → s₁
```

---

## Summary

| Step | Type Being Processed | Skolems Created | Wrapper Built |
|------|---------------------|-----------------|---------------|
| 1 | `∀a. a → ∀b. b → a` | `s₁` (for `a`) | Started outer WpFun |
| 2 | `a → ∀b. b → a` | - | - |
| 3 | `∀b. b → a` | `s₂` (for `b`) | Started inner WpFun |
| 4 | `b → a` | - | - |
| 5 | `a` | - | WpHole (base case) |
| 6 | Unwind `b` level | - | WpFun + WpTyLam s₂ |
| 7 | Unwind `a` level | - | WpFun + WpTyLam s₁ |

**Final Result**:
- **Type**: `s₁ → s₂ → s₁` (with free skolems)
- **Wrapper**: `Λs₁. λ(x:s₁). Λs₂. λ(y:s₂). [...]`
- **Wrapper Type**: `(s₁ → s₂ → s₁) → (∀s₁. s₁ → ∀s₂. s₂ → s₁)`

The wrapper converts from the skolemised type back to the polymorphic type by:
1. Creating type abstractions for each skolem
2. Eta-expanding at function types to properly scope the type abstractions
