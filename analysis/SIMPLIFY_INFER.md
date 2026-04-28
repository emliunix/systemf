# simplifyInfer: Generalization at Let Bindings

This document explains the `simplifyInfer` function, which is responsible for **generalization** - converting monomorphic types into polymorphic types by quantifying over type variables and constraints.

## Function Signature

**Location:** `GHC/Tc/Solver.hs:932`

```haskell
simplifyInfer :: TopLevelFlag          -- (1) Syntactically top-level
              -> TcLevel               -- (2) Used when generating the constraints
              -> InferMode             -- (3) How to handle quantification
              -> [TcIdSigInst]         -- (4) Any signatures (possibly partial)
              -> [(Name, TcTauType)]   -- (5) Variables to be generalised, and their tau-types
              -> WantedConstraints     -- (6) Constraints collected from RHS
              -> TcM ([TcTyVar],       -- (a) Quantify over these type variables
                      [EvVar],         -- (b) ... and these constraints (fully zonked)
                      TcEvBinds,       -- (c) ... binding these evidence variables
                      Bool)            -- (d) True <=> the residual constraints are insoluble
```

## Arguments Explained

### 1. `TopLevelFlag` - Is this a top-level binding?

```haskell
data TopLevelFlag = TopLevel | NotTopLevel
```

- **`TopLevel`**: The binding is at the module level (e.g., `f x = x + 1` at the top of a module)
- **`NotTopLevel`**: The binding is nested inside a function or let-expression

**Why it matters:**
- Top-level bindings can have more general types due to the "let should not be generalized" (LG) rule
- The Monomorphism Restriction (MR) only applies to top-level bindings
- GHC is more conservative about generalizing nested bindings

### 2. `TcLevel` - The type checking level

```haskell
newtype TcLevel = TcLevel Int
```

- Represents the **nesting depth** where the constraints were generated
- Used to determine which type variables are "touchable" (can be unified)
- Variables from outer levels are "untouchable" - they cannot be unified with concrete types

**Example:**
```haskell
f x = let y = x + 1 in y
-- The constraint `Num a` for `x + 1` is generated at a deeper level than f's parameters
```

### 3. `InferMode` - How aggressive to be about quantification

```haskell
data InferMode = ApplyMR         -- Apply Monomorphism Restriction
               | EagerDefaulting -- :type +d mode; refuse to quantify over defaultable constraints
               | NoRestrictions  -- Quantify over any constraint that satisfies pickQuantifiablePreds
```

**Three modes:**

| Mode | Use Case | Behavior |
|------|----------|----------|
| `ApplyMR` | Standard top-level bindings with MR on | Restrict generalization for bindings affected by MR |
| `EagerDefaulting` | GHCi's `:type +d` | Default constraints eagerly, refuse to quantify over defaultable ones |
| `NoRestrictions` | Normal inference | Quantify over any constraint that meets the criteria |

### 4. `[TcIdSigInst]` - Type signatures (if any)

```haskell
-- TcIdSigInst represents an instantiated type signature
-- e.g., if the user wrote `f :: forall a. Num a => a -> a`
-- and we're checking `f = \x -> x + 1`, this holds the signature info
```

- **Complete signatures**: The user provided the full type (e.g., `f :: Int -> Int`)
- **Partial signatures**: The user provided a partial type (e.g., `f :: _ -> Int` or `f :: Num a => a -> _`)
- **Empty list**: No signature provided - we're doing full inference

**Why it matters:**
- Signatures guide generalization - we must respect the user's specified type
- Partial signatures constrain which type variables can be quantified

### 5. `[(Name, TcTauType)]` - Variables and their monomorphic types

```haskell
-- name_taus = [(name, tau_type)]
-- e.g., [("f", Int -> Int), ("g", Bool)]
```

- **`Name`**: The identifier being bound (e.g., the name "f" for `f x = x`)
- **`TcTauType`**: The monomorphic (tau) type inferred for the RHS
  - This type may contain unification variables (meta type variables)
  - It has NOT been zonked yet (may contain "holes")

**This is the input from `tcInferSigma` or `tcMonoBinds`!**

Example from `tcPolyInfer` (GHC/Tc/Gen/Bind.hs:714):
```haskell
tcPolyInfer ... = do
  { (tclvl, wanted, (binds', mono_infos)) <- pushLevelAndCaptureConstraints $
                                              tcMonoBinds ...
  ; let name_taus = [ (mbi_poly_name info, idType (mbi_mono_id info))
                    | info <- mono_infos ]
  ; ...
  ; ((qtvs, givens, ev_binds, insoluble), residual)
       <- captureConstraints $
          simplifyInfer top_lvl tclvl infer_mode sigs name_taus wanted
```

### 6. `WantedConstraints` - Constraints from the RHS

```haskell
-- Constraints collected during type checking of the right-hand side
-- e.g., [Num a, Ord b, Show c] from expressions like `(x + 1, y > z, show w)`
```

These are the **unsolved constraints** that remain after type checking the expression body. They include:
- **Class constraints**: `Num a`, `Ord b`, etc.
- **Equality constraints**: `a ~ Int`, `F a ~ Bool`, etc.
- **Implication constraints**: Nested constraints from local bindings

## Return Values Explained

### (a) `[TcTyVar]` - Quantified type variables (qtvs)

```haskell
-- e.g., [a, b] for the type `forall a b. Num a => a -> b -> a`
```

These are the **type variables to generalize over** - they become forall-bound in the final type.

**How they're chosen:**
1. Collect all free type variables in the monomorphic types
2. Filter out "untouchable" variables (from outer scopes)
3. Sort by dependency order (so independent variables come first)
4. Include only those not mentioned in "remaining" constraints

### (b) `[EvVar]` - Quantified constraints (theta)

```haskell
-- bound_theta_vars :: [EvVar]
-- e.g., [d :: Num a] for the constraint `Num a`
```

These are **evidence variables** for the constraints that should be part of the type context.

**What makes a constraint quantifiable:**
- Must mention at least one quantified type variable (the "Q" condition)
- Must not be a "solved" constraint (we filter those out)
- Must satisfy `pickQuantifiablePreds` (various criteria)

**Examples:**
```haskell
-- Input monomorphic type: a -> a
-- Collected constraint: Num a
-- If 'a' is quantified, then `Num a` becomes part of the type:
--   forall a. Num a => a -> a

-- If no constraints mention quantified vars, result is [] (no context)
```

### (c) `TcEvBinds` - Evidence bindings

```haskell
data TcEvBinds = TcEvBinds EvBindsVar
```

These bind the evidence variables to actual **dictionary values** at usage sites.

**What happens:**
- When we call `f :: forall a. Num a => a -> a` with `f (1 :: Int)`
- GHC needs a `Num Int` dictionary
- The `TcEvBinds` maps the evidence variable `d :: Num a` to the actual `Num Int` instance

**Note:** The comment says "fully zonked" - all type variables in the evidence have been resolved.

### (d) `Bool` - Are residual constraints insoluble?

```haskell
definite_error :: Bool  -- True <=> insoluble
```

- **`True`**: There are definitely errors in the constraints (e.g., `Int ~ Bool`)
- **`False`**: Constraints are either solvable or deferred

**Usage:**
- Used to suppress duplicate error messages
- If `True`, GHC knows the type is definitely wrong and can be more permissive about subsequent errors

## The Generalization Algorithm

Here's what `simplifyInfer` does step by step:

### Step 1: Solve Constraints

```haskell
ev_binds_var <- TcM.newTcEvBinds
wanted_transformed <- runTcSWithEvBinds ev_binds_var $
                       setTcLevelTcS rhs_tclvl $
                       solveWanteds (mkSimpleWC psig_evs `andWC` wanteds)
```

1. Create a new evidence bindings variable
2. Run the constraint solver (`solveWanteds`)
3. This unifies type variables, simplifies constraints, and generates evidence

### Step 2: Zonk the Constraints

```haskell
wanted_transformed <- TcM.liftZonkM $ TcM.zonkWC wanted_transformed
```

Replace all mutable type variable references with their actual types.

### Step 3: Decide Quantification

```haskell
(qtvs, bound_theta, co_vars) <- decideQuantification
                                   top_lvl rhs_tclvl infer_mode
                                   skol_info name_taus partial_sigs
                                   wanted_dq
```

1. **Collect candidate type variables** from the monomorphic types
2. **Filter** by the "Q" condition (must be mentioned in wanted constraints)
3. **Sort** by dependency order
4. **Pick quantifiable predicates** (constraints mentioning qtvs)

### Step 4: Create Evidence Variables

```haskell
bound_theta_vars <- mapM TcM.newEvVar bound_theta
```

Create fresh evidence variables for each quantified constraint.

### Step 5: Emit Residual Constraints

```haskell
emitResidualConstraints rhs_tclvl skol_info ev_binds_var
                        co_vars qtvs bound_theta_vars wanted_transformed
```

Any constraints that couldn't be quantified are emitted as residual constraints for the enclosing scope to handle.

### Step 6: Return Results

```haskell
return (qtvs, bound_theta_vars, TcEvBinds ev_binds_var, definite_error)
```

## Example Walkthrough

```haskell
-- Source code:
f x = x + 1

-- Step 1: Type check RHS
tcMonoBinds infers:
  name_taus = [("f", a -> a)]  -- x :: a, result :: a
  wanteds = [Num a]           -- from (+) :: Num a => a -> a -> a

-- Step 2: Call simplifyInfer
simplifyInfer TopLevel tclvl NoRestrictions [] [("f", a -> a)] [Num a]

-- Step 3: Solve constraints
-- The solver finds that `a` needs to be `Num`
-- No unification happens yet because `a` is at the current level

-- Step 4: Decide quantification
-- qtvs = [a]  -- 'a' is a candidate (free in the type, at current level)
-- bound_theta = [Num a]  -- mentions 'a', so we quantify over it

-- Step 5: Create evidence
d :: Num a  -- fresh evidence variable

-- Step 6: Return
qtvs = [a]
bound_theta_vars = [d]  -- where d :: Num a
ev_binds = ...
definite_error = False

-- Final polymorphic type:
-- f :: forall a. Num a => a -> a
```

## Relationship to the Paper

The paper "Practical Type Inference for Higher-Rank Types" has a rule called **GEN** for generalization:

```
Γ ⊢↑ e : ρ     ā = ftv(ρ) - ftv(Γ)
---------------------------------
Γ ⊢↑ e : ∀ā.ρ
```

`simplifyInfer` implements a more sophisticated version of this:
- Handles constraints (theta), not just type variables
- Deals with partial type signatures
- Respects the Monomorphism Restriction
- Uses levels instead of simple free-variable subtraction

## Key Invariants

1. **The returned type variables are sorted**: Independent variables come before dependent ones
2. **The constraints are fully zonked**: No mutable references remain
3. **Evidence variables are fresh**: Created specifically for this generalization
4. **Residual constraints are emitted**: Non-quantifiable constraints become implications

## See Also

- `tcPolyInfer` (GHC/Tc/Gen/Bind.hs:714) - Main caller for let-bindings
- `tcRnExpr` (GHC/Tc/Module.hs:2615) - Caller for GHCi's `:type`
- `decideQuantification` - The actual quantification algorithm
- `emitResidualConstraints` - How remaining constraints are handled

---

*Document based on GHC source code analysis*
