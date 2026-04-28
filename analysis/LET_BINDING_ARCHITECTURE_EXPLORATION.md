# GHC Let Binding Type Inference Architecture

**Status:** Validated  
**Last Updated:** 2026-04-10  
**Central Question:** How does GHC typecheck let bindings using the Levels/Expect/Closure/Meta-Skolem model?

---

## Base Model: The 4 Universal Aspects

All type inference in GHC is built on these 4 fundamental mechanisms:

### 1. LEVELS (TcLevel Hierarchy)

**The invariant:** Meta variables can only be unified at their creation level.

```
Level N (Outer scope)
  ├─ Signatures processed
  ├─ Complete sigs added to env  
  └─ pushLevelAndCaptureConstraints → Level N+1
      
Level N+1 (Binding RHS)
  ├─ Metas created here
  ├─ Type inference happens
  └─ simplifyInfer → back to Level N
      
Level N (Generalized)
  └─ Quantified types produced
```

**Key Functions:**
- `pushLevelAndCaptureConstraints` - bumps level, brackets computation
- `isTouchableMetaTyVar` - checks if meta is at current level
- `checkConstraints` - builds implication, may push to N+2

**Evidence:** `compiler/GHC/Tc/Utils/TcType.hs:870-885`

```haskell
newtype TcLevel = TcLevel Int  -- 0 = outermost
pushTcLevel (TcLevel n) = TcLevel (n + 1)
```

---

### 2. EXPECT (Check vs Infer Mode)

**The invariant:** Mode determines variable creation and flow direction.

| Aspect | Check Mode | Infer Mode |
|--------|------------|------------|
| **Direction** | Top-down | Bottom-up |
| **Has expected type?** | Yes | No |
| **Creates** | Skolems (rigid) | Metas (flexible) |
| **Function suffix** | `xxxCheck` | `xxxInfer` or no suffix |
| **Dispatch** | Pattern match on `ExpType` | Pattern match on `ExpType` |

**Evidence:** `compiler/GHC/Tc/Utils/TcType.hs:491-498`

```haskell
data ExpType = Check TcType      -- Expected type provided
             | Infer InferResult  -- Hole to fill
```

**Critical:** Same function behaves differently based on mode:
- `matchExpectedFunTys (Check ...)` → may skolemise
- `matchExpectedFunTys (Infer ...)` → creates metas

---

### 3. CLOSURE (CPS Pattern)

**The invariant:** Environment extension via `thing_inside` callback.

**Structure:**
```haskell
withExtendedEnv :: Env -> (Env -> TcM a) -> TcM a
withExtendedEnv env thing_inside = do
  { new_env <- extendEnv env
  ; result <- thing_inside new_env   -- Callback
  ; return result }
```

**Un-CPS'd Flow:**
```
Sequential:  A → B → C → D
CPS:         A → withX $ \env -> 
                  B → withY $ \env' ->
                      C → D
```

**Key Pattern:** Results flow back through the closure, environment extends downward.

---

### 4. META vs SKOLEM

**The invariant:** Metas unify, skolems don't (rigid).

| | MetaTv | SkolemTv |
|--|--------|----------|
| **Mutability** | Mutable (IORef) | Immutable |
| **Unification** | Yes | No (rigid) |
| **Created by** | `newMetaTyVarX` | `tcInstSkolTyVarsX` |
| **Use case** | Unknown types | Polymorphic checking |
| **Level** | Current level | Current level + 1 |

**CRITICAL DISTINCTION:**
- `newMetaTyVarTyVarX` creates **TyVarTv** - still a **META** (can unify with tyvars)
- `skolemiseRequired` creates **SkolemTv** - rigid, cannot unify

**Evidence:** `compiler/GHC/Tc/Utils/TcMType.hs:995-997`

```haskell
newMetaTyVarTyVarX = new_meta_tv_x TyVarTv  -- Meta, NOT skolem!
```

---

## Function Analysis by 4 Aspects

### tcValBinds (Entry Point)

**Levels:** Maintains Level N throughout, delegates level push to sub-functions.

**Expect:** Takes `thing_inside` - body is checked in whatever mode caller specifies.

**Closure:** Classic CPS - processes bindings, then calls `thing_inside` with extended env.

**Meta/Skolem:** Doesn't create vars directly - delegates to `tcPolyBinds`.

**Evidence:** `compiler/GHC/Tc/Gen/Bind.hs:255-290`

```haskell
tcValBinds top_lvl grps sigs thing_inside
  = do { (poly_ids, sig_fn) <- tcTySigs sigs          -- Level N
       ; tcExtendSigIds poly_ids $                     -- Level N
         tcBindGroups grps $                           -- Level N
           thing_inside }                              -- Body with full env
```

**Analysis:**
- **Level N:** All processing at outer level
- **Closure:** `tcExtendSigIds` → `tcBindGroups` → `thing_inside`
- **Expect:** Passes through to body
- **Meta/Skolem:** Delegated

---

### tcTySigs (Signature Processing)

**Levels:** Level N - signatures processed at outer level.

**Expect:** N/A - just instantiates signatures, not checking terms.

**Closure:** No closure - returns results directly.

**Meta/Skolem:** Creates `poly_id` for complete sigs (these are polymorphic types, not vars).

**Evidence:** `compiler/GHC/Tc/Gen/Sig.hs:165-180`

```haskell
tcTySigs hs_sigs
  = do { ty_sigs_s <- mapM tcTySig hs_sigs
       ; let poly_ids = mapMaybe completeSigPolyId_maybe ty_sigs
       ; return (poly_ids, lookupNameEnv env) }
```

**Analysis:**
- **Level N:** Complete sigs visible at outer level
- **Meta/Skolem:** Creates poly types (not vars)
- **Key:** Complete sigs in env BEFORE bindings processed

---

### tcPolyCheck (CheckGen Plan)

**Levels:** N → N+1 → N

**Expect:** CHECK mode - has expected type from signature.

**Closure:** `tcSkolemiseCompleteSig` with callback.

**Meta/Skolem:** Creates skolems (rigid) from signature.

**Evidence:** `compiler/GHC/Tc/Gen/Bind.hs:585`

```haskell
tcPolyCheck ctx sig_fn prag_fn rec_tc bind sig
  = do { ...
       ; tcSkolemiseCompleteSig sig $ \invis_pat_tys rho_ty ->  -- Closure!
           tcFunBindMatches ... (mkCheckExpType rho_ty) }       -- Check mode!
```

**Analysis:**
- **Level:** Signature instantiated (skolems created), then checked at N+1
- **Expect:** CHECK - `mkCheckExpType rho_ty`
- **Closure:** `\invis_pat_tys rho_ty -> ...`
- **Meta/Skolem:** `tcSkolemiseCompleteSig` creates **skolems** (rigid)

---

### tcPolyInfer (InferGen Plan)

**Levels:** N → N+1 → N (explicit level push)

**Expect:** INFER mode - synthesizes types.

**Closure:** `pushLevelAndCaptureConstraints` brackets N+1 inference.

**Meta/Skolem:** Creates metas at N+1, quantifies to skolems on return.

**Evidence:** `compiler/GHC/Tc/Gen/Bind.hs:721-742`

```haskell
tcPolyInfer ...
  = do { (tclvl, wanted, (binds', mono_infos))
             <- pushLevelAndCaptureConstraints $        -- Level N+1!
                tcMonoBinds rec_tc tc_sig_fn LetLclBndr bind_list
       ; ((qtvs, givens, ev_binds, insoluble), residual)
             <- captureConstraints $
                simplifyInfer top_lvl tclvl ... wanted   -- Quantify at N
       ; ... }
```

**Analysis:**
- **Level:** N → N+1 (push) → N (return and quantify)
- **Expect:** INFER - `tcMonoBinds` creates metas
- **Closure:** `pushLevelAndCaptureConstraints` brackets N+1
- **Meta/Skolem:** Metas created at N+1, `quantifyTyVars` converts to skolems

---

### tcMonoBinds (InferGen Helper)

**Levels:** Runs at Level N+1 (already pushed by caller).

**Expect:** INFER mode - creates metas for unknown types.

**Closure:** `tcExtendRecIds` for recursive references.

**Meta/Skolem:** 
- No sig: `newOpenFlexiTyVarTy` → TauTv (meta)
- Partial sig: `tcInstSig` → TyVarTv (meta, NOT skolem!)

**Evidence:** `compiler/GHC/Tc/Gen/Bind.hs:1314-1315` (closure pattern)

```haskell
tcMonoBinds _ sig_fn no_gen binds
  = do { tc_binds <- mapM (wrapLocMA (tcLhs sig_fn no_gen)) binds
       ; let mono_infos = getMonoBindInfo tc_binds
       ; binds' <- tcExtendRecIds rhs_id_env $
                   mapM (wrapLocMA tcRhs) tc_binds }
```

**Analysis:**
- **Level:** N+1 (inference level)
- **Expect:** INFER - creates metas
- **Closure:** `tcExtendRecIds` for recursive env
- **Meta/Skolem:** 
  - No sig: fresh TauTv meta
  - Partial sig: `tcInstSig` creates TyVarTv (meta!)

---

### tcInstSig (Partial Signature Instantiation)

**Levels:** Runs at caller's level (N+1 for InferGen).

**Expect:** N/A - just instantiation.

**Closure:** N/A.

**Meta/Skolem:** Creates **TyVarTvs** (metas!), NOT skolems.

**Evidence:** `compiler/GHC/Tc/Gen/Sig.hs:506-518`

```haskell
tcInstSig hs_sig@(TcCompleteSig (CSig { sig_bndr = poly_id }))
  = do { (tv_prs, theta, tau) <- tcInstTypeBndrs (idType poly_id)
       ; return (TISI { sig_inst_skols = tv_prs, ... }) }
```

**Evidence:** `compiler/GHC/Tc/Utils/Instantiate.hs:541`

```haskell
-- In tcInstTypeBndrs
do { (subst', tv') <- newMetaTyVarTyVarX subst tv  -- TyVarTv META!
   ; ... }
```

**Analysis:**
- **Meta/Skolem:** TyVarTvs are **META variables** (can unify with tyvars)
- **CRITICAL:** These are NOT skolems despite the name "skols" in field
- **Why:** Pattern matching with multiple complete sigs - need TyVarTvs to prevent unwanted unification

---

### matchExpectedFunTys (Function Type Decomposition)

**Levels:** Depends on mode - may push to N+2 in Check mode.

**Expect:** DISPATCHES on Check vs Infer!

**Closure:** Callback receives `pat_tys` and `rhs_ty`.

**Meta/Skolem:** 
- Infer: `new_infer_arg_ty` → TauTv metas
- Check: `skolemiseRequired` → SkolemTv (skolems!)

**Evidence:** `compiler/GHC/Tc/Utils/Unify.hs:809-822` (Infer)

```haskell
matchExpectedFunTys herald _ctxt arity (Infer inf_res) thing_inside
  = do { arg_tys <- mapM (new_infer_arg_ty herald) [1 .. arity]  -- METAS!
       ; res_ty  <- newInferExpType (ir_inst inf_res)            -- META!
       ; result  <- thing_inside (map ExpFunPatTy arg_tys) res_ty
       ; ... }
```

**Evidence:** `compiler/GHC/Tc/Utils/Unify.hs:835-851` (Check)

```haskell
check n_req rev_pat_tys ty
  | isSigmaTy ty = do { ...
                      ; (n_req', wrap_gen, tv_nms, bndrs, given, inner_ty) 
                          <- skolemiseRequired skol_info n_req ty  -- SKOLEMS!
                      ; (ev_binds, (wrap_res, result))
                          <- checkConstraints ... $
                             check n_req' (reverse (...) ++ rev_pat_tys) inner_ty }
```

**Analysis:**
- **Level:** Infer - stays at N+1; Check - pushes to N+2 via `checkConstraints`
- **Expect:** CRITICAL distinction - Infer creates metas, Check skolemises
- **Closure:** `thing_inside` receives decomposed types
- **Meta/Skolem:** Mode determines variable type

---

## Call Hierarchy (Reorganized by 4 Aspects)

```
Level N
│
├─► tcValBinds
│   │
│   ├─► tcTySigs [Level N]                    ─┐
│   │   ├─ Creates poly_ids (complete sigs)    │
│   │   └─ Returns sig_fn                      │ No level push
│   │                                          │ No expect mode
│   ├─► tcExtendSigIds [Level N]               │ (pure processing)
│   │   └─ Adds complete sigs to env           │
│   │                                          │
│   └─► tcBindGroups [Level N]                ─┘
│       │
│       ├─► For each SCC group:
│       │   └─► tc_group
│       │       │
│       │       ├─► decideGeneralisationPlan    ─┐ PLAN SELECTION
│       │       │   │                            │
│       │       │   ├─ Exactly 1 binding with    │ CheckGen
│       │       │   │   complete signature       │ (Check mode)
│       │       │   └──────► tcPolyCheck ────────┤
│       │       │                                │
│       │       │   ├─ Partial sigs OR           │ InferGen
│       │       │   │   generalization enabled   │ (Infer mode)
│       │       │   └──────► tcPolyInfer ────────┤
│       │       │                                │
│       │       │   └─ MonoLocalBinds,           │ NoGen
│       │       │       no signatures            │ (No gen)
│       │       │       └──► tcPolyNoGen ────────┘
│       │       │
│       │       └─► tcExtendLetEnv [Level N]
│       │           └─ Adds results for next group
│       │
│       └─► thing_inside [Level N, full env]
│
│
├─► tcPolyCheck (CheckGen plan)               ─┐
│   │   ^                                      │
│   │   └─ One binding with complete sig       │ Level: N → N+1
│   │                                           │ Expect: CHECK
│   ├─► tcSkolemiseCompleteSig                  │ Closure: thing_inside
│   │   ├─ Instantiates sig (creates SKOLEMS!)  │ Meta/Skolem: Skolems
│   │   └─ checkConstraints [Level N+1]         │
│   │       └─ tcFunBindMatches                 │
│   │           └─ Checks body against rho_ty   │
│   │                                           │
│   └─ Returns poly_id [Level N]               ─┘
│
│
└─► tcPolyInfer (InferGen plan)               ─┐
    │   ^                                       │
    │   └─ Infer + generalize                   │ Level: N → N+1 → N
    │       (no/partial sigs)                   │ Expect: INFER
    │                                           │ Closure: bracketed
    ├─► pushLevelAndCaptureConstraints          │ Meta/Skolem: Metas
    │   │                                       │   → quantified
    │   └─► tcMonoBinds [Level N+1]            │
    │       │                                   │
    │       ├─► tcLhs                           │
    │       │   ├─ No sig: new TauTv META      │
    │       │   └─ Partial sig: TyVarTv META   │
    │       │                                   │
    │       ├─► tcExtendRecIds [Level N+1]     │
    │       │                                   │
    │       └─► tcRhs [Level N+1]              │
    │           └─► matchExpectedFunTys        │
    │               ├─ Infer mode: METAS       │
    │               └─ Check mode: SKOLEMS     │
    │                                           │
    ├─► simplifyInfer [Returns to Level N]    │
    │   └─ quantifyTyVars                       │
    │       └─ Metas → Skolems (quantified)    │
    │                                           │
    └─► mkExport [Level N]                     ─┘
        └─ Creates poly bindings
```

## Key Insights

### 1. Level Management

- **Level N:** Signatures, complete sig env, body
- **Level N+1:** Inference (metas created here)
- **Level N+2:** Deep checking (skolemisation under arrows)

### 2. Expect Mode Determines Variables

- **Infer mode** → Metas (TauTv, TyVarTv)
- **Check mode** → Skolems (SkolemTv)

### 3. Closure Pattern

Every environment extension uses CPS:
```haskell
withExtendedEnv env $ \new_env -> do
  -- thing_inside with extended env
```

### 4. Meta vs Skolem Critical Distinction

- `tcInstSig` → **TyVarTvs** (metas!)
- `skolemiseRequired` → **SkolemTvs** (skolems!)
- `newMetaTyVarX` → **TauTv** (regular metas)

---

## Validation Notes

All claims validated. See: `LET_BINDING_ARCHITECTURE_VALIDATION.md`

**Critical Corrections:**
1. `tcInstSig` creates **TyVarTvs** (metas), NOT skolems
2. `matchExpectedFunTys` behavior depends on Expect mode
3. Levels: N (outer) → N+1 (inference) → N (generalized)
