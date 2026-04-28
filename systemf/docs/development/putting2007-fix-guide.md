# Fixing the Type Inference Gaps Against Putting 2007

**Date**: 2026-03-06
**Tests**: `tests/test_surface/test_putting2007_gaps.py` (10 failing, 8 passing)
**Paper**: Peyton Jones et al., "Practical Type Inference for Arbitrary-Rank Types" (JFP 2007)
**Reference impl**: `docs/research/putting-2007-implementation.hs`

---

## Overview

The Python elaborator (`src/systemf/surface/inference/elaborator.py`) has 6 gaps
relative to the paper's algorithm.  They are **ordered by dependency** — fixing
Gap 5 first unblocks Gap 4, which unblocks Gap 2, etc.

Recommended fix order:

```
5 (rigid skolems)
  → 6 (forall alpha-equiv)
    → 4 (skolem escape check)
      → 2 (checkSigma / GEN2)
        → 3 (instSigma / VAR instantiation)
          → 1 (inferSigma / GEN1)
```

Each section below gives:
- **What's wrong** (current behaviour vs paper)
- **Paper reference** (rule name, Haskell function, line numbers)
- **Files to change**
- **Exact code changes** with before/after
- **How to verify** (which tests should flip to green)

---

## Gap 5 — Rigid Skolem Type Variables

### What's wrong

`_skolemise` creates `TypeVar("_skol_a_0")` — a regular type variable.
Two problems:
1. Same name on repeated calls → accidental unification
2. Meta variables can unify with a skolem (it's just a TypeVar)

The paper uses a distinct `SkolemTv` constructor that unification refuses
to touch.

### Paper reference

```haskell
-- putting-2007-implementation.hs L59-61
data TyVar = BoundTv String       -- Bound type variable (from forall)
           | SkolemTv String Uniq -- Skolem constant (rigid, existential)
           deriving (Eq, Show)

-- L170-173
newSkolemTyVar :: TyVar -> Tc TyVar
newSkolemTyVar tv = do
    uniq <- newUnique
    return (SkolemTv (tyVarName tv) uniq)
```

Key: `SkolemTv` carries a unique id so two skolemisations never collide,
and `Eq` only matches when both name and unique are equal.

### Files to change

1. `src/systemf/core/types.py` — add `TypeSkolem`
2. `src/systemf/surface/inference/unification.py` — reject skolem unification
3. `src/systemf/surface/inference/elaborator.py` — `_skolemise` creates `TypeSkolem`

### Changes

#### 1. Add `TypeSkolem` to `types.py`

After the `TypeVar` class, add:

```python
@dataclass(frozen=True)
class TypeSkolem(Type):
    """Rigid (skolem) type variable.

    Created during skolemisation (GEN2, DEEP-SKOL).  A skolem is a
    placeholder for "any type" — it must NOT unify with anything except
    itself (same name AND same unique id).

    Paper: SkolemTv String Uniq  (putting-2007-implementation.hs L60)
    """

    name: str
    unique: int

    def __str__(self) -> str:
        return f"${self.name}_{self.unique}"

    def free_vars(self) -> set[str]:
        return {str(self)}

    def substitute(self, subst: dict[str, Type]) -> Type:
        return self
```

Add `TypeSkolem` to the `TypeRepr` union at the bottom of the file.

#### 2. Reject skolem unification in `unification.py`

Import `TypeSkolem`.  Add cases **before** the existing `TypeVar` cases:

```python
# In the unify() match block, add BEFORE the TypeVar cases:

# Skolem vs skolem: must be identical (name + unique)
case TypeSkolem(name1, u1), TypeSkolem(name2, u2):
    if name1 == name2 and u1 == u2:
        return subst
    raise UnificationError(t1, t2, location, None)

# Skolem vs anything else (including Meta): rigid, cannot unify
case TypeSkolem(), _:
    raise UnificationError(t1, t2, location, None)

case _, TypeSkolem():
    raise UnificationError(t1, t2, location, None)
```

Also update `_occurs_check_recursive` and `Substitution.apply_to_type` to
handle `TypeSkolem` (treat it like `TypeVar` — no children, return self).

#### 3. Use `TypeSkolem` in `_skolemise`

The elaborator needs a counter for unique ids.  Add to `__init__`:

```python
def __init__(self):
    self.subst: Substitution = Substitution.empty()
    self._meta_counter: int = 0
    self._skolem_counter: int = 0  # NEW
```

Add a helper:

```python
def _fresh_skolem(self, name: str) -> TypeSkolem:
    """Create a fresh rigid skolem constant."""
    uid = self._skolem_counter
    self._skolem_counter += 1
    return TypeSkolem(name, uid)
```

Rewrite `_skolemise` to use it:

```python
def _skolemise(self, ty: Type) -> tuple[list[TypeSkolem], Type]:
    """Weak prenex conversion + skolemisation.

    Paper: skolemise (putting-2007-implementation.hs L208-217)
    """
    match ty:
        case TypeForall(var, body):
            # PRPOLY: replace bound var with fresh rigid skolem
            sk = self._fresh_skolem(var)
            body2 = self._subst_type_var(body, var, sk)
            more_sks, rho = self._skolemise(body2)
            return ([sk] + more_sks, rho)

        case TypeArrow(arg, ret, doc):
            # PRFUN: skolemise the return type, hoist skolems
            sks, ret2 = self._skolemise(ret)
            return (sks, TypeArrow(arg, ret2, doc))

        case _:
            # PRMONO
            return ([], ty)
```

Return type changes from `list[str]` to `list[TypeSkolem]`.

### Verify

```
test_distinct_skolemisations_dont_unify  → PASS
test_skolem_does_not_unify_with_concrete_type  → PASS
```

---

## Gap 6 — TypeForall Unification (Alpha-Equivalence)

### What's wrong

```python
# unification.py current code
case TypeForall(var1, body1), TypeForall(var2, body2):
    if var1 == var2:
        return unify(body1, body2, subst, location)
    else:
        return unify(body1, body2, subst, location)  # BUG: no rename!
```

When `var1 ≠ var2`, the bodies contain different `TypeVar` names that won't
match.  `∀a. a→a` vs `∀b. b→b` fails because `TypeVar("a") ≠ TypeVar("b")`.

### Paper reference

The paper **never unifies forall types directly** — it routes through
instantiation + subsumption.  But since the Python code does have a direct
path, the minimal fix is alpha-rename before comparing bodies.

### Files to change

`src/systemf/surface/inference/unification.py`

### Changes

Replace the `TypeForall` case in `unify()`:

```python
case TypeForall(var1, body1), TypeForall(var2, body2):
    if var1 == var2:
        return unify(body1, body2, subst, location)
    else:
        # Alpha-rename: replace var2 with var1 in body2
        renamed_body2 = _subst_type_var_in_type(body2, var2, TypeVar(var1))
        return unify(body1, renamed_body2, subst, location)
```

Add a local helper (or import `_subst_type_var` from elaborator, but a
standalone function is cleaner):

```python
def _subst_type_var_in_type(ty: Type, var: str, replacement: Type) -> Type:
    """Substitute free occurrences of TypeVar(var) with replacement."""
    match ty:
        case TypeVar(name) if name == var:
            return replacement
        case TypeVar(_) | TMeta(_) | PrimitiveType(_) | TypeSkolem():
            return ty
        case TypeArrow(arg, ret, doc):
            return TypeArrow(
                _subst_type_var_in_type(arg, var, replacement),
                _subst_type_var_in_type(ret, var, replacement),
                doc,
            )
        case TypeForall(bv, body) if bv == var:
            return ty  # shadowed
        case TypeForall(bv, body):
            return TypeForall(bv, _subst_type_var_in_type(body, var, replacement))
        case TypeConstructor(name, args):
            return TypeConstructor(
                name,
                [_subst_type_var_in_type(a, var, replacement) for a in args],
            )
        case _:
            return ty
```

(Import `TypeSkolem` if doing Gap 5 first.)

### Verify

```
test_alpha_equivalent_foralls_unify  → PASS
test_non_alpha_equivalent_foralls_dont_unify  → PASS  (already passes)
test_check_against_alpha_renamed_forall  → PASS  (already passes)
```

---

## Gap 4 — Skolem Escape Check

### What's wrong

```python
# elaborator.py L1141-1143  (_subs_check)
if skol_tvs:
    # For now, simplified check - in full implementation would check
    # that skol_tvs don't appear in the final types
    pass  # ← STUBBED OUT
```

### Paper reference

```haskell
-- putting-2007-implementation.hs L557-565
subsCheck :: Sigma -> Sigma -> Tc ()
subsCheck sigma1 sigma2 = do
    (skol_tvs, rho2) <- skolemise sigma2
    subsCheckRho sigma1 rho2
    esc_tvs <- getFreeTyVars [sigma1, sigma2]
    let bad_tvs = filter (`elem` esc_tvs) skol_tvs
    check (null bad_tvs) (text "Subsumption check failed")
```

After the subsumption body, **zonk** (apply subst to) `sigma1` and `sigma2`,
collect all `TypeSkolem` values that appear free, and check that none of the
skolems we created are among them.

### Files to change

`src/systemf/surface/inference/elaborator.py`

### Changes

Add a helper to collect skolems in a type (after Gap 5, skolems are
`TypeSkolem` instances):

```python
def _free_skolems(self, ty: Type) -> set[TypeSkolem]:
    """Collect all TypeSkolem values that appear in ty."""
    ty = self._apply_subst(ty)
    match ty:
        case TypeSkolem() as sk:
            return {sk}
        case TypeArrow(arg, ret, _):
            return self._free_skolems(arg) | self._free_skolems(ret)
        case TypeForall(_, body):
            return self._free_skolems(body)
        case TypeConstructor(_, args):
            result: set[TypeSkolem] = set()
            for a in args:
                result |= self._free_skolems(a)
            return result
        case _:
            return set()
```

Replace the `pass` in `_subs_check`:

```python
def _subs_check(self, sigma1: Type, sigma2: Type, location=None) -> None:
    skol_tvs, rho2 = self._skolemise(sigma2)
    self._subs_check_rho(sigma1, rho2, location)

    # Skolem escape check
    if skol_tvs:
        sigma1_resolved = self._apply_subst(sigma1)
        sigma2_resolved = self._apply_subst(sigma2)
        escaped = self._free_skolems(sigma1_resolved) | self._free_skolems(sigma2_resolved)
        bad = [sk for sk in skol_tvs if sk in escaped]
        if bad:
            raise TypeMismatchError(
                expected=sigma2,
                actual=sigma1,
                location=location,
                term=None,
                context="subsumption check failed: type not polymorphic enough",
            )
```

### Verify

```
test_mono_not_subsumes_poly  → PASS  (already passes, now for the right reason)
test_subsumption_rejects_wrong_direction  → PASS  (already passes)
test_poly_subsumes_mono_should_succeed  → PASS
```

The tests already pass by accident (unification catches the symptom), but
after this fix they pass for the correct reason, and edge cases that
unification wouldn't catch are now covered.

---

## Gap 2 — `checkSigma` / GEN2 (Check Mode Must Skolemise)

### What's wrong

When `check()` encounters a `TypeForall` expected type for a lambda, it
**instantiates** (creates flexible metas):

```python
# elaborator.py L737-746
case TypeForall(_, _) as forall_type:
    instantiated = self._instantiate(forall_type)    # WRONG
    instantiated = self._apply_subst(instantiated)
    return self.check(term, instantiated, ctx)
```

The paper's GEN2 rule **skolemises** (creates rigid constants) and then
checks the body against the rho type, followed by a skolem escape check.

### Paper reference

```haskell
-- putting-2007-implementation.hs L535-553
checkSigma :: Term -> Sigma -> Tc ()
checkSigma expr sigma = do
    (skol_tvs, rho) <- skolemise sigma       -- Skolemise, don't instantiate!
    checkRho expr rho                        -- Check body against rho
    env_tys <- getEnvTypes                   -- Get all types in Γ
    esc_tvs <- getFreeTyVars (sigma : env_tys)
    let bad_tvs = filter (`elem` esc_tvs) skol_tvs
    check (null bad_tvs) (text "Type not polymorphic enough")
```

### Files to change

`src/systemf/surface/inference/elaborator.py`

### Changes

Add a new method `check_sigma` that wraps the skolemise-check-escape
pattern.  Then change `check()` to call it when the expected type has
a top-level forall.

#### New method

```python
def check_sigma(self, term, sigma: Type, ctx: TypeContext) -> core.Term:
    """GEN2: Check term against a polymorphic type by skolemising.

    Paper: checkSigma (putting-2007-implementation.hs L535-553)
    """
    skol_tvs, rho = self._skolemise(sigma)
    core_term = self.check(term, rho, ctx)

    # Skolem escape check
    if skol_tvs:
        # Collect all types in the environment
        env_skolems: set[TypeSkolem] = set()
        for t in ctx.term_types:
            env_skolems |= self._free_skolems(t)
        sigma_skolems = self._free_skolems(self._apply_subst(sigma))
        escaped = env_skolems | sigma_skolems
        bad = [sk for sk in skol_tvs if sk in escaped]
        if bad:
            raise TypeMismatchError(
                expected=sigma,
                actual="<term>",
                location=term.location if hasattr(term, 'location') else None,
                term=term,
                context="type not polymorphic enough",
            )

    return core_term
```

#### Change `check()` lambda handling

Replace the `TypeForall` case inside `check()` for `ScopedAbs`:

```python
# BEFORE (wrong — instantiates):
case TypeForall(_, _) as forall_type:
    instantiated = self._instantiate(forall_type)
    instantiated = self._apply_subst(instantiated)
    return self.check(term, instantiated, ctx)

# AFTER (correct — skolemises via GEN2):
case TypeForall(_, _):
    return self.check_sigma(term, expected, ctx)
```

Also update the **fall-through** case at the bottom of `check()` to handle
`TypeForall` expected types properly for non-lambda terms:

```python
case _:
    # For other cases: if expected is a forall, use check_sigma
    match expected:
        case TypeForall(_, _):
            return self.check_sigma(term, expected, ctx)
        case _:
            core_term, inferred_type = self.infer(term, ctx)
            # ... existing unification logic ...
```

#### Also use `check_sigma` in APP rule

The APP rule checks the argument with `Γ ⊢^poly_⇓ u : σ`.  The `^poly`
means `checkSigma`, not `checkRho`.  In the APP case of `infer()`:

```python
# BEFORE:
core_arg = self.check(arg, param_type, ctx)

# AFTER:
core_arg = self.check_sigma(arg, param_type, ctx)
```

(Only needed when `param_type` is a sigma.  Since `check_sigma` calls
`_skolemise` which is a no-op for non-forall types, it's safe to always
use `check_sigma` here.)

### Verify

```
test_check_lambda_against_forall_should_reject  → PASS
test_check_const_against_id_type_should_reject  → PASS  (already passes)
test_check_valid_id_against_forall_should_accept  → PASS  (already passes)
test_checking_wrong_function_against_poly_annotation  → PASS
```

---

## Gap 3 — `instSigma` Dispatch (VAR Rule Instantiation)

### What's wrong

The VAR rule in `infer()` returns the type from the context as-is:

```python
case ScopedVar(location=location, index=index, debug_name=debug_name):
    var_type = ctx.lookup_term_type(index)
    var_type = self._apply_subst(var_type)
    core_term = core.Var(location, index, debug_name)
    return (core_term, var_type)  # Returns ∀a. a→a, not _m→_m!
```

The paper's VAR rule uses `instSigma` which, in synthesis mode (INST1),
instantiates foralls to rho types.

### Paper reference

```haskell
-- putting-2007-implementation.hs L429-433
tcRho (Var v) exp_ty = do
    v_sigma <- lookupVar v
    instSigma v_sigma exp_ty     -- INST1 in synth mode → instantiate

-- L615-632
instSigma :: Sigma -> Expected Rho -> Tc ()
instSigma t1 (Check t2) = subsCheckRho t1 t2   -- INST2: subsumption
instSigma t1 (Infer ref) = do                   -- INST1: instantiate
    t1' <- instantiate t1
    writeTcRef ref t1'
```

### Files to change

`src/systemf/surface/inference/elaborator.py`

### Changes

In the `ScopedVar` case of `infer()`, instantiate before returning:

```python
case ScopedVar(location=location, index=index, debug_name=debug_name):
    try:
        var_type = ctx.lookup_term_type(index)
        var_type = self._apply_subst(var_type)
        # INST1: instantiate sigma → rho in synthesis mode
        var_type = self._instantiate(var_type)
        var_type = self._apply_subst(var_type)
        core_term = core.Var(location, index, debug_name)
        return (core_term, var_type)
    except IndexError:
        raise TypeError(...)
```

Do the same for `GlobalVar`:

```python
case GlobalVar(location=location, name=name):
    # ... constructor lookup (already instantiates) ...

    # For global variables:
    try:
        var_type = ctx.lookup_global(name)
        var_type = self._apply_subst(var_type)
        # INST1: instantiate sigma → rho
        var_type = self._instantiate(var_type)
        var_type = self._apply_subst(var_type)
        core_term = core.Global(location, name)
        return (core_term, var_type)
    except NameError:
        raise TypeError(...)
```

**Important**: The APP rule currently has its own forall instantiation:

```python
case SurfaceApp(location=location, func=func, arg=arg):
    core_func, func_type = self.infer(func, ctx)
    func_type = self._apply_subst(func_type)
    # This block becomes redundant after fixing VAR:
    match func_type:
        case TypeForall(_, _):
            func_type = self._instantiate(func_type)
            func_type = self._apply_subst(func_type)
```

After fixing the VAR rule, `infer(func, ctx)` already returns a rho type,
so the APP-level instantiation becomes a no-op.  You can leave it for
safety (instantiate is idempotent on rho types) or remove it.

### Verify

```
test_infer_var_instantiates_forall  → PASS
test_infer_poly_var_applied_to_int  → PASS
```

---

## Gap 1 — `inferSigma` / GEN1 (Let-Bound Polymorphism)

### What's wrong

The LET rule in `infer()` calls `self.infer(value, ...)` which returns a
rho type (with unresolved metas).  It stores this rho directly in the
context.  The paper calls `inferSigma` which generalises the rho to a
sigma by quantifying over meta variables not in the environment.

### Paper reference

```haskell
-- putting-2007-implementation.hs L505-510
tcRho (Let var rhs body) exp_ty = do
    var_ty <- inferSigma rhs        -- GEN1: generalise!
    extendVarEnv var var_ty (tcRho body exp_ty)

-- L520-531
inferSigma :: Term -> Tc Sigma
inferSigma e = do
    exp_ty <- inferRho e             -- Infer rho type
    env_tys <- getEnvTypes           -- All types in Γ
    env_tvs <- getMetaTyVars env_tys -- Meta vars in Γ
    res_tvs <- getMetaTyVars [exp_ty] -- Meta vars in result
    let forall_tvs = res_tvs \\ env_tvs  -- Generalisable metas
    quantify forall_tvs exp_ty       -- Bind them with ∀

-- L226-234
quantify :: [MetaTv] -> Rho -> Tc Sigma
quantify tvs ty = do
    mapM_ bind (tvs `zip` new_bndrs)   -- Bind each meta to a BoundTv
    ty' <- zonkType ty                   -- Resolve all metas
    return (ForAll new_bndrs ty')        -- Wrap in ForAll
```

### Files to change

`src/systemf/surface/inference/elaborator.py`

### Changes

#### Add helper: collect meta variables in a type

```python
def _collect_metas(self, ty: Type) -> set[int]:
    """Collect all TMeta ids that appear (after applying subst)."""
    ty = self._apply_subst(ty)
    match ty:
        case TMeta(id=mid):
            return {mid}
        case TypeArrow(arg, ret, _):
            return self._collect_metas(arg) | self._collect_metas(ret)
        case TypeForall(_, body):
            return self._collect_metas(body)
        case TypeConstructor(_, args):
            result: set[int] = set()
            for a in args:
                result |= self._collect_metas(a)
            return result
        case _:
            return set()
```

#### Add `infer_sigma` method

```python
def infer_sigma(self, term, ctx: TypeContext) -> tuple[core.Term, Type]:
    """GEN1: Infer a term's type and generalise over free metas.

    Paper: inferSigma (putting-2007-implementation.hs L520-531)
    """
    core_term, rho = self.infer(term, ctx)
    rho = self._apply_subst(rho)

    # Collect metas in the environment (must NOT generalise these)
    env_metas: set[int] = set()
    for t in ctx.term_types:
        env_metas |= self._collect_metas(t)
    for t in ctx.globals.values():
        env_metas |= self._collect_metas(t)

    # Collect metas in the result type
    res_metas = self._collect_metas(rho)

    # Generalisable = in result but not in environment
    forall_metas = res_metas - env_metas

    if not forall_metas:
        return (core_term, rho)

    # Quantify: bind each generalisable meta to a fresh bound variable
    # and replace it in the type
    binder_names = _fresh_binder_names(len(forall_metas), rho)
    meta_to_var: dict[int, str] = {}
    for mid, name in zip(sorted(forall_metas), binder_names):
        meta_to_var[mid] = name
        # Extend the substitution so the meta resolves to the bound var
        self.subst = self.subst.extend(TMeta(mid), TypeVar(name))

    # Apply substitution to get the type with TypeVars instead of TMetas
    generalised_body = self._apply_subst(rho)

    # Wrap in foralls (outermost first)
    result_type = generalised_body
    for name in reversed(binder_names):
        result_type = TypeForall(name, result_type)

    return (core_term, result_type)
```

Add a module-level helper to generate binder names:

```python
def _fresh_binder_names(count: int, ty: Type) -> list[str]:
    """Generate fresh binder names not already used in ty."""
    used = ty.free_vars()
    candidates = (
        [chr(c) for c in range(ord('a'), ord('z') + 1)]
        + [f"{chr(c)}{i}" for i in range(1, 100) for c in range(ord('a'), ord('z') + 1)]
    )
    result = []
    for name in candidates:
        if name not in used and len(result) < count:
            result.append(name)
    return result
```

#### Change LET rule to use `infer_sigma`

```python
# In infer(), SurfaceLet case:
case SurfaceLet(location=location, bindings=bindings, body=body):
    new_ctx = ctx
    core_bindings = []

    for var_name, var_type_ann, value in bindings:
        # GEN1: infer and generalise
        core_value, value_type = self.infer_sigma(value, new_ctx)

        # If there's a type annotation, check against it
        if var_type_ann is not None:
            ann_type = self._surface_to_core_type(var_type_ann, new_ctx)
            ann_type = self._apply_subst(ann_type)
            value_type = self._apply_subst(value_type)
            self._unify(ann_type, value_type, location)

        final_type = self._apply_subst(value_type)
        new_ctx = new_ctx.extend_term(final_type)
        core_bindings.append((var_name, core_value))

    core_body, body_type = self.infer(body, new_ctx)
    # ... rest unchanged ...
```

Also update the LET case in `check()` to use `infer_sigma` for the RHS.

### Verify

```
test_let_poly_used_at_two_types  → PASS
test_let_generalises_identity_type  → PASS
test_paper_example_let_poly_application  → PASS
test_paper_church_numerals  → PASS  (already passes)
```

---

## Combined Test Expectations

After all 6 gaps are fixed, the full test file should show:

```
tests/test_surface/test_putting2007_gaps.py  — 18 passed, 0 failed
```

Specifically:

| Test | Gap | Expected |
|------|-----|----------|
| `test_let_poly_used_at_two_types` | 1 | PASS |
| `test_let_generalises_identity_type` | 1 | PASS |
| `test_check_lambda_against_forall_should_reject` | 2 | PASS |
| `test_check_const_against_id_type_should_reject` | 2 | PASS |
| `test_check_valid_id_against_forall_should_accept` | 2 | PASS |
| `test_infer_var_instantiates_forall` | 3 | PASS |
| `test_infer_poly_var_applied_to_int` | 3 | PASS |
| `test_mono_not_subsumes_poly` | 4 | PASS |
| `test_subsumption_rejects_wrong_direction` | 4 | PASS |
| `test_poly_subsumes_mono_should_succeed` | 4 | PASS |
| `test_distinct_skolemisations_dont_unify` | 5 | PASS |
| `test_skolem_does_not_unify_with_concrete_type` | 5 | PASS |
| `test_alpha_equivalent_foralls_unify` | 6 | PASS |
| `test_non_alpha_equivalent_foralls_dont_unify` | 6 | PASS |
| `test_check_against_alpha_renamed_forall` | 6 | PASS |
| `test_paper_example_let_poly_application` | 1+3 | PASS |
| `test_checking_wrong_function_against_poly_annotation` | 2+4 | PASS |
| `test_paper_church_numerals` | 1+2+3 | PASS |

---

## Regression Risk

These changes touch core inference logic.  Run the **full** test suite
after each gap fix:

```bash
uv run pytest tests/ --tb=short -q
```

Expected: 642 passed (existing) + gap tests flipping to green.

Watch for regressions in:
- `tests/test_surface/test_inference.py` — main inference tests
- `tests/test_surface/test_putting2007_examples.py` — existing paper tests
- `tests/test_pipeline.py` — end-to-end pipeline

The most likely regression is from **Gap 3** (VAR instantiation).  If
existing tests pass a polymorphic variable and expect a `TypeForall` back,
they'll now get a `TMeta → TMeta`.  Audit any test that checks
`isinstance(ty, TypeForall)` after `infer()` on a variable.

---

## Cross-Reference to Paper

| Gap | Paper Rule | Paper Section | Haskell Function | Haskell Line |
|-----|-----------|---------------|-----------------|--------------|
| 1 | GEN1 | §4.7.3 | `inferSigma`, `quantify` | L520-234 |
| 2 | GEN2 | §4.7.3 | `checkSigma` | L535-553 |
| 3 | INST1 | §4.7.3 | `instSigma` | L615-632 |
| 4 | DEEP-SKOL | §4.6 | `subsCheck` | L557-565 |
| 5 | SkolemTv | §4.5 | `newSkolemTyVar` | L170-173 |
| 6 | (alpha) | §5.6 | (never unifies forall) | L290-302 |

---

## Cross-Reference to LaTeX Rules

| Gap | LaTeX Rule | LaTeX Section |
|-----|-----------|---------------|
| 1 | GEN1 | §6 (`Γ ⊢^poly_⇑`) |
| 2 | GEN2 | §6 (`Γ ⊢^poly_⇓`) |
| 3 | INST1, INST2 | §7 (`⊢^inst_δ`) |
| 4 | DEEP-SKOL | §9 (`⊢^dsk`) |
| 5 | (infrastructure) | §8 (`pr(σ)`) |
| 6 | (infrastructure) | §10 (`⊢^dsk*` MONO) |