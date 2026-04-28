# Polymorphic Recursive Binding Groups in GHC

**Scope:** How GHC typechecks and desugars recursive binding groups where bindings may have polymorphic types. Covers `AbsBinds`, `ABE`, SCC analysis, and Core translation.

---

## 1. Overview

When typechecking a recursive binding group like:

```haskell
f x = ... g ...
g y = ... f ...
```

GHC must solve a tension:
- **Inside** the group, recursive calls must see *monomorphic* types (so metas can unify)
- **Outside** the group, calls should see *polymorphic* types (so callers can instantiate)

The solution is a two-level representation: **monomorphic IDs** inside the group, **polymorphic IDs** outside, bridged by `AbsBinds`.

---

## 2. Key Data Types

### 2.1 `AbsBinds`

Location: `compiler/GHC/Hs/Binds.hs:167`

```haskell
data AbsBinds = AbsBinds {
    abs_tvs      :: [TyVar],       -- Quantified type variables
    abs_ev_vars  :: [EvVar],       -- Evidence variables (dictionaries)
    abs_exports  :: [ABExport],    -- Poly/mono pairs (see below)
    abs_ev_binds :: [TcEvBinds],   -- Evidence bindings
    abs_binds    :: LHsBinds GhcTc -- Monomorphic bindings
}
```

`AbsBinds` appears in the **typechecker output**. It represents a binding group that has been typechecked and generalized, but not yet desugared to Core.

### 2.2 `ABExport` (AbsBinds Export)

Location: `compiler/GHC/Hs/Binds.hs:201`

```haskell
data ABExport = ABE {
    abe_poly  :: Id,         -- Exported polymorphic id
    abe_mono  :: Id,         -- Internal monomorphic id
    abe_wrap  :: HsWrapper,  -- Poly -> mono conversion (usually identity)
    abe_prags :: TcSpecPrags -- SPECIALISE pragmas
}
```

Each `ABE` connects one external polymorphic name to its internal monomorphic counterpart.

**Wrapper shape:** `abe_wrap :: (forall abs_tvs. abs_ev_vars => abe_mono) ~ abe_poly`

### 2.3 `MonoBindInfo`

Location: `compiler/GHC/Tc/Gen/Bind.hs:1379`

```haskell
data MonoBindInfo = MBI {
    mbi_poly_name :: Name,
    mbi_sig       :: Maybe TcIdSigInst,
    mbi_mono_id   :: TcId,    -- The monomorphic id created during tcLhs
    mbi_mono_mult :: Mult
}
```

Used during `tcMonoBinds` to track the LHS-created monomorphic IDs.

---

## 3. The Typechecking Pipeline

### 3.1 Entry Point: `tcValBinds`

```haskell
tcValBinds top_lvl grps sigs thing_inside
  = do { (poly_ids, sig_fn) <- tcTySigs sigs
       ; tcExtendSigIds poly_ids $         -- Complete sigs in env FIRST
         tcBindGroups grps $               -- Process SCC groups
           thing_inside }
```

**Key insight:** Complete signatures are added to the env **before** any binding group is processed. This enables polymorphic recursion.

### 3.2 SCC Analysis: `tcBindGroups`

Bindings are processed one SCC at a time. Environment is extended after each group.

### 3.3 Recursive Groups: `tc_rec_group`

For groups marked `Recursive`, GHC does a **second SCC analysis**:

```haskell
sccs = stronglyConnCompFromEdgedVerticesUniq (mkEdges sig_fn binds)
```

Where `mkEdges` **omits edges to variables with complete signatures**:

```haskell
mkEdges sig_fn binds
  = [ DigraphNode bind key [key | n <- freeVars bind
                                , Just key <- [lookup n]
                                , no_sig n ]  -- ← omit signatured targets
    | ... ]
```

This breaks dependencies on signatured variables, allowing them to be typechecked separately (enabling polymorphic recursion).

### 3.4 Generalization Plans

`tcPolyBinds` selects a plan per sub-group:

| Plan | Condition | Behavior |
|------|-----------|----------|
| `CheckGen` | Exactly 1 binding with complete signature | Skolemise signature, check RHS |
| `InferGen` | Partial sigs or generalization enabled | Push level N+1, infer, quantify |
| `NoGen` | MonoLocalBinds, no signatures | No generalization |

### 3.5 `tcMonoBinds`: The Two-Phase Core

**Phase 1 — `tcLhs`: Create monomorphic IDs**

```haskell
tcMonoBinds _ sig_fn no_gen binds
  = do { tc_binds <- mapM (wrapLocMA (tcLhs sig_fn no_gen)) binds
       ; let mono_infos = getMonoBindInfo tc_binds
```

For each binder:
- No signature: `mono_id` gets a fresh meta type (`newOpenFlexiTyVarTy`)
- Partial signature: `mono_id` gets instantiated signature type (`tcInstSig`)
- Complete signature: already in scope from `tcExtendSigIds`

**Phase 2 — `tcExtendRecIds`: Add mono IDs to env, check RHSs**

```haskell
rhs_id_env = [ (name, mono_id)
             | MBI { mbi_poly_name = name, mbi_mono_id = mono_id } <- mono_infos
             , no_complete_sig ]

binds' <- tcExtendRecIds rhs_id_env $
          mapM (wrapLocMA tcRhs) tc_binds
```

All RHSs are checked with **all monomorphic IDs in scope**.

**Phase 3 — `tcPolyInfer`: Generalize**

```haskell
tcPolyInfer ...
  = do { (tclvl, wanted, (binds', mono_infos))
             <- pushLevelAndCaptureConstraints $
                tcMonoBinds ... bind_list
       ; ((qtvs, ...), residual)
             <- captureConstraints $
                simplifyInfer top_lvl tclvl ... wanted
       ; ... }
```

Metas created at level N+1 are quantified together. All bindings in the group share the same quantified type variables.

---

## 4. Desugaring to Core

### 4.1 The Naive Translation

Conceptually (from Note [AbsBinds]):

```haskell
-- AbsBinds { abs_tvs = [a], abs_exports = [ABE f fm, ABE g gm],
--            abs_binds = BIND[fm,gm] }

f = fwrap [ /\a. letrec { BIND[fm,gm] } in fm ]
g = gwrap [ /\a. letrec { BIND[fm,gm] } in gm ]
```

This duplicates the entire binding group per export. GHC avoids this.

### 4.2 The Actual Translation: Tuple-Based

From `dsAbsBinds` general case (`compiler/GHC/HsToCore/Binds.hs:380`):

```haskell
poly_tup = /\a. \d. letrec { fm = rhs_f
                           ; gm = rhs_g }
                    in (fm, gm)

f = /\a. \d. case (poly_tup a d) of (fm, gm) -> fm
g = /\a. \d. case (poly_tup a d) of (fm, gm) -> gm
```

Where `rhs_f` and `rhs_g` internally reference `fm` and `gm`.

**Structure:**

| Level | Binding | Role |
|-------|---------|------|
| Inner `letrec` | `fm = rhs_f[fm,gm]` | Monomorphic recursive bindings |
| Inner `letrec` | `gm = rhs_g[fm,gm]` | Monomorphic recursive bindings |
| `poly_tup` | Returns `(fm, gm)` | Packages monomorphic ids |
| Export `f` | Selects `fm` from tuple | Polymorphic wrapper |
| Export `g` | Selects `gm` from tuple | Polymorphic wrapper |

### 4.3 Special Case: No TyVars, No Dicts

When the group is monomorphic (`null tyvars && null dicts`):

```haskell
-- No tuple needed. Direct mapping:
f = rhs_f[f,g]
g = rhs_g[g,f]
```

Poly IDs and mono IDs have the **same type**. The `AbsBinds` collapses to a simple `letrec`.

### 4.4 Single Export Optimization

For the common case of one export (most non-recursive and self-recursive bindings):

```haskell
f = /\a. \d. letrec { fm = rhs[fm] } in fm
```

No tuple is created — the body directly returns the monomorphic id.

---

## 5. Strict Bindings Difference

From Note [Desugar Strict binds] (`compiler/GHC/HsToCore/Binds.hs`):

### Lazy Case

```haskell
poly_tup = /\a. letrec { fm = rhs_f
                       ; gm = rhs_g }
                in (fm, gm)
```

Tuple exports only the selectors (`fm`, `gm`).

### Strict Case (`!` or `-XStrict`)

When bindings are strict, the RHS computation must be forced. But the computation (`tm` for pattern bindings) is inside `poly_tup`, not visible in the body.

**Solution:** Include the computation in the tuple:

```haskell
poly_tup = /\a. letrec { tm = rhs[fm,gm]
                       ; fm = ...
                       ; gm = ... }
                in (tm, fm, gm)   -- tm IS INCLUDED
```

Then the body can extract and `seq` it:

```haskell
body' = let (tm, fm, gm) = poly_tup a in tm `seq` <body>
```

**Key difference:** Strict bindings may need to export auxiliary computation variables that lazy bindings can leave hidden inside the `letrec`.

---

## 6. Lifecycle Summary

| Phase | Mono ID | Poly ID |
|-------|---------|---------|
| **tcLhs** | Created with meta type | Not yet exists |
| **tcExtendRecIds** | In env for recursive refs | Not in env |
| **tcRhs** | Used inside RHS expressions | Not used |
| **tcPolyInfer** | Type gets zonked | Created by `mkExport` |
| **AbsBinds** | `abs_binds` | `abs_exports` |
| **Desugaring** | Bound in inner `letrec` | Exported selector |
| **Final Core** | Inside `poly_tup` body | External name |

---

## 7. Implications for elab3

### What You Need

1. **Two-phase typechecking:** Create mono IDs first, extend env, then check RHSs
2. **Level push:** Single level push for the entire recursive group, not per-binding
3. **Joint generalization:** Collect metas from ALL RHSs, quantify together
4. **Core representation:** Either:
   - Add `AbsBinds`-like node (poly/mono pair + inner binds)
   - Or use tuple encoding (helper + selectors)

### What You Can Skip (Initially)

- Second SCC analysis for polymorphic recursion (GHC does this to maximize polymorphism)
- Evidence variables / dictionary abstraction (unless you have type classes)
- Strict binding force-variable machinery
- Specialization pragmas (`abe_prags`)

### Minimal Viable Design

```python
@dataclass
class CoreAbsBinds:
    ty_vars: list[TyVar]
    exports: list[tuple[Id, Id]]  # (poly_id, mono_id)
    binds: Rec                     # inner monomorphic bindings
```

Or skip `AbsBinds` entirely for monomorphic-only recursive groups.

---

## 8. References

| File | Line | Content |
|------|------|---------|
| `compiler/GHC/Hs/Binds.hs` | 167 | `AbsBinds` data type |
| `compiler/GHC/Hs/Binds.hs` | 201 | `ABExport` data type |
| `compiler/GHC/Hs/Binds.hs` | 220 | Note [AbsBinds] |
| `compiler/GHC/Hs/Binds.hs` | 260 | Note [ABExport wrapper] |
| `compiler/GHC/Tc/Gen/Bind.hs` | 255 | `tcValBinds` entry point |
| `compiler/GHC/Tc/Gen/Bind.hs` | 372 | `tc_rec_group` |
| `compiler/GHC/Tc/Gen/Bind.hs` | 452 | `tcPolyBinds` plan selection |
| `compiler/GHC/Tc/Gen/Bind.hs` | 1289 | `tcMonoBinds` general case |
| `compiler/GHC/Tc/Gen/Bind.hs` | 875 | `mkExport` |
| `compiler/GHC/HsToCore/Binds.hs` | 263 | `dsAbsBinds` |
| `compiler/GHC/HsToCore/Binds.hs` | 552 | Note [The no-tyvar no-dict case] |
| `compiler/GHC/HsToCore/Binds.hs` | 658 | Note [Desugar Strict binds] |
