# Visible Type Application & Scoped Type Variables

**Status:** Partial Implementation  
**Date:** 2026-03-09  
**Files:** `src/systemf/surface/inference/bidi_inference.py`, `src/systemf/surface/inference/elab_bodies_pass.py`

## References

1. **Eisenberg et al., "Visible Type Application", ESOP 2016**
   - Paper: https://www.seas.upenn.edu/~sweirich/papers/esop2016-type-app.pdf
   - Extended version: https://richarde.dev/papers/2016/type-app/visible-type-app-extended.pdf
   - GHC Documentation: https://downloads.haskell.org/ghc/9.6.5/docs/users_guide/exts/type_applications.html

2. **Eisenberg, Breitner, et al., "Type Variables in Patterns", ICFP 2018**
   - Extends scoped type variables to pattern matching
   - https://dl.acm.org/doi/10.1145/3242744.3242753

3. **Peyton Jones et al., "Practical type inference for arbitrary-rank types", JFP 2007**
   - Foundation: Bidirectional type checking for higher-rank polymorphism
   - Our base implementation follows this paper

## Overview

System F implements **visible type application**, an extension to the Hindley-Milner type system that allows explicit type instantiation via the `@` operator (e.g., `id @Int`). This feature was introduced by Eisenberg et al. (2016) as an extension to GHC.

**Key insight from Eisenberg 2016:**
> "Visible type application lets the caller write the type argument directly (e.g., `read @Int "5"`), making code clearer and eliminating the need for auxiliary proxy values."

Visible type application requires **scoped type variables** (1998, GHC 4.02) - type variables bound by `forall` in type annotations are available within the annotated expression.

## Syntax

```systemf
-- Polymorphic identity with scoped type variable
id :: forall a. a -> a = \x -> (x :: a)  -- 'a' is bound for the body

-- Explicit instantiation
int_id :: Int -> Int = id @Int

-- Higher-rank with scoped type variable
usePoly :: (forall a. a -> a) -> Int
usePoly = \(f :: forall a. a -> a) -> f @a 42  -- 'a' bound by param annotation
```

## Bidirectional Typing Rules

We extend Putting 2007's bidirectional system with Eisenberg 2016's rules:

### 1. Type Application (B_TApp)

$$
\frac{\Gamma \vdash e \Rightarrow \forall a.\, \sigma}{\Gamma \vdash e @\tau \Rightarrow \sigma[\tau/a]} \text{(B\_TApp)}
$$

Where:
- $e$ synthesizes a polymorphic type $\forall a.\, \sigma$
- The visible type application $@\tau$ instantiates $a$ with $\tau$
- The result type is $\sigma$ with $\tau$ substituted for $a$

### 2. Declaration with Scoped Type Variables (DECL-SCOPE)

$$
\frac{\Gamma, \overline{a} \vdash e \Leftarrow \sigma \quad \text{where declaration has type } \forall \overline{a}.\, \sigma}{\Gamma \vdash \text{decl} :: \forall \overline{a}.\, \sigma = e} \text{(DECL-SCOPE)}
$$

The type variables bound by `forall` in the declaration signature are available when type-checking the body.

### 3. Type Annotation with Scoped Variables (ANN-SCOPE)

$$
\frac{\Gamma, \overline{a} \vdash e \Leftarrow \rho \quad \text{where annotation is } \forall \overline{a}.\, \rho}{\Gamma \vdash (e :: \forall \overline{a}.\, \rho) \Rightarrow \forall \overline{a}.\, \rho} \text{(ANN-SCOPE)}
$$

A type annotation binds its forall-quantified variables for checking the annotated expression.

### 4. Lambda with Annotated Parameter (LAM-ANN-SCOPE)

$$
\frac{\Gamma, \overline{a} \vdash \sigma \text{ type} \quad \Gamma, x:\sigma, \overline{a} \vdash e \Leftarrow \sigma_r \quad \text{where } \sigma = \forall \overline{a}.\, \rho}{\Gamma \vdash \lambda(x::\sigma).\, e \Leftarrow \sigma \to \sigma_r} \text{(LAM-ANN-SCOPE)}
$$

When a lambda parameter has a polymorphic type annotation, those type variables are in scope for the lambda body.

### 5. Pattern Matching with Polymorphic Fields (PAT-POLY)

$$
\frac{\Gamma \vdash C : \forall \overline{a}.\, \tau_1 \to \dots \to \tau_n \to T \quad \Gamma, \overline{x_i:\tau_i} \vdash e \Rightarrow \sigma'}{\Gamma \vdash \text{case } e_0 \text{ of } C\, \overline{x} \to e \Rightarrow \sigma'} \text{(PAT-POLY)}
$$

Pattern variables bound to polymorphic constructor arguments retain their polymorphic types (not instantiated eagerly).

## Implementation

### Current Status

**Implemented:**
- ✅ B_TApp: Type application on globals (`id @Int`)
- ✅ Basic bidirectional inference (Putting 2007)

**Missing / Broken:**
- ❌ DECL-SCOPE: Context not extended with forall-bound vars before body checking
- ❌ ANN-SCOPE: `(x :: a)` doesn't recognize `a` from enclosing forall
- ❌ LAM-ANN-SCOPE: Lambda param annotations don't bind type variables for body
- ❌ PAT-POLY: Pattern variables eagerly instantiated, losing polymorphism

### Key Implementation Detail

**Problem:** When looking up a polymorphic global variable (like `id`), the elaborator was **instantiating** the type immediately (replacing `forall a. a -> a` with a fresh meta `_a -> _a`). This broke type applications because the forall was lost.

**Solution:** In `SurfaceTypeApp` handling, special-case `GlobalVar` to **not instantiate** the type. Keep the forall so the type application can substitute the type argument.

```python
case SurfaceTypeApp(location=location, func=func, type_arg=type_arg):
    # Special case: if func is a GlobalVar, don't instantiate
    match func:
        case GlobalVar(name=name):
            if name in ctx.globals:
                func_type = ctx.globals[name]  # Keep the forall!
                func_type = self._apply_subst(func_type)
                core_func = core.Global(location, name)
        case _:
            # Normal case: instantiate as usual
            core_func, func_type = self.infer(func, ctx)
            func_type = self._apply_subst(func_type)
    
    # Now func_type should be a forall
    match func_type:
        case TypeForall(var, body_type):
            # Substitute type argument
            core_type_arg = self._surface_to_core_type(type_arg, ctx)
            result_type = self._subst_type_var(body_type, var, core_type_arg)
            return (core.TApp(location, core_func, core_type_arg), result_type)
```

### Required Changes

#### 1. Declaration-Level Context Extension

File: `src/systemf/surface/inference/elab_bodies_pass.py`

```python
def collect_forall_vars(ty: Type) -> list[str]:
    """Extract all forall-bound type variables from a type."""
    vars = []
    while isinstance(ty, TypeForall):
        vars.append(ty.var)
        ty = ty.body
    return vars

def extend_with_forall_vars(ctx, ty):
    """Extend context with all forall-bound vars in type."""
    for var in collect_forall_vars(ty):
        ctx = ctx.extend_type(var)
    return ctx

# In elab_bodies_pass:
for decl in term_decls:
    expected_type = signatures[decl.name]
    
    # EXTEND context with forall-bound vars from THIS declaration
    scoped_ctx = extend_with_forall_vars(type_ctx, expected_type)
    
    # Check body with scoped context
    core_body = bidi.check(decl.body, expected_type, scoped_ctx)
```

#### 2. Annotation-Level Context Extension

File: `src/systemf/surface/inference/bidi_inference.py`

```python
case SurfaceAnn(location=loc, term=inner, type=ann_type):
    # Extract forall vars from annotation
    ann_vars = collect_forall_vars(ann_type)
    
    # Extend context with annotation's forall vars
    ann_ctx = ctx
    for var in ann_vars:
        ann_ctx = ann_ctx.extend_type(var)
    
    # Convert annotation with extended context
    core_ann = self._surface_to_core_type(ann_type, ann_ctx)
    
    # Check inner term with extended context
    core_inner = self.check(inner, core_ann, ann_ctx)
```

#### 3. Lambda Parameter Context Extension

File: `src/systemf/surface/inference/bidi_inference.py`

```python
case ScopedAbs(location=loc, var_name=var, var_type=param_type, body=body):
    if param_type is not None:
        # Extract forall vars from param annotation
        param_vars = collect_forall_vars(param_type)
        
        # Extend context with param's forall vars for body checking
        body_ctx = ctx
        for pv in param_vars:
            body_ctx = body_ctx.extend_type(pv)
        
        # Convert param type (original context for param position)
        core_param_type = self._surface_to_core_type(param_type, ctx)
        
        # Check body with extended context
        new_ctx = body_ctx.extend_term(core_param_type)
        core_body = self.check(body, ret_type, new_ctx)
```

## Difference from Putting 2007

**Putting 2007 (base algorithm):**
- No explicit type application syntax
- Type instantiation is always **implicit** via unification
- Type variables introduced only via explicit type abstraction ($\Lambda$)
- When using a polymorphic function, the type system automatically picks the right instantiation

**Eisenberg 2016 + Scoped Type Variables:**
- Adds explicit $e @\tau$ syntax for type application
- Programmer can specify type arguments explicitly
- Type variables introduced via `forall` in annotations scope over the annotated expression
- Falls back to implicit instantiation when not specified
- Distinguishes **specified** variables (user-written forall) from **inferred** variables

## Status

**Type Application on Globals:** ✅ FIXED
```python
source = '''
id :: forall a. a -> a = \x -> x
int_id :: Int -> Int = id @Int
'''
# Works correctly!
```

**Scoped Type Variables:** ❌ NOT IMPLEMENTED
```systemf
id :: forall a. a -> a = \x -> (x :: a)  -- 'a' not recognized in annotation
```

## Limitations

1. **Specified vs. Inferred:** Our current implementation doesn't distinguish between:
   - **Specified variables:** `forall a.` (user-written, can be instantiated via `@`)
   - **Inferred variables:** From generalization (cannot be instantiated via `@`)
   
   Full Eisenberg System V tracks this distinction.

2. **Single variable:** Current implementation handles `forall a. ...` but not `forall a b. ...` (multiple variables).

3. **Pattern Type Signatures:** Not yet implemented (requires 2018 paper extensions).

## Research Notes

### Partial Type Signatures (Eisenberg 2016, Section 6.3)

**Status:** Pleasing feature - needs investigation

Eisenberg 2016 notes a pleasing synergy between visible type application and GHC's partial type signature feature (wildcards written as `_`). This allows users to write:

```haskell
f @_ @[Int] True []  -- GHC infers 'a' is Bool, but visibly instantiates 'b' to [Int]
```

**Key insight:** The combination of visible type application with type wildcards enables "partial explicit instantiation" where some type arguments are inferred and others are explicitly provided.

**Investigation needed:**
- How would this interact with our bidirectional type checking?
- Can we support `f @_ @Int` where the first wildcard is inferred?
- Implementation complexity vs. benefit trade-off

Reference: Eisenberg et al., "Visible Type Application", ESOP 2016, Section 6.3

## Test Cases

### Working
```systemf
-- Basic type application
id :: forall a. a -> a = \x -> x
int_id :: Int -> Int = id @Int
use_id :: Int = id @Int 42
```

### Not Working (Needs Scoped Type Variables)
```systemf
-- Scoped type variable in annotation
id :: forall a. a -> a = \x -> (x :: a)

-- Scoped type variable in lambda param
usePoly :: (forall a. a -> a) -> Int
usePoly = \(f :: forall a. a -> a) -> f @a 42

-- Pattern matching with polymorphic fields
data PolyBox = PolyBox (forall a. a -> a)
unbox :: PolyBox -> Int
unbox (PolyBox f) = f 42  -- f should be polymorphic
```

## See Also

- `src/systemf/surface/inference/bidi_inference.py` - Main implementation
- `docs/research/putting-2007-implementation.hs` - Reference implementation
- `docs/research/systemf-putting2007-validation.md` - Putting 2007 validation results
- Eisenberg, R. A., Weirich, S., & Ahmed, A. (2016). Visible Type Application. In *Programming Languages and Systems* (pp. 229-254). Springer.
- Eisenberg, R. A., Breitner, J., et al. (2018). Type Variables in Patterns. In *Proceedings of the 11th ACM SIGPLAN International Symposium on Haskell* (pp. 1-13).
- Peyton Jones, S., Vytiniotis, D., Weirich, S., & Shields, M. (2007). Practical type inference for arbitrary-rank types. *Journal of Functional Programming*, 17(1), 1-82.
