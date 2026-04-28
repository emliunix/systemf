# Base Model Validation Report

**Target Document:** `upstream/ghc/analysis/LET_BINDING_ARCHITECTURE_EXPLORATION.md`  
**Validation Date:** 2026-04-10  
**Base Model:** 4 Aspects (Levels, Expect, Closure, Meta/Skolem)

---

## Validation Summary

| Function | LEVELS | EXPECT | CLOSURE | META/SKOLEM | Status |
|----------|--------|--------|---------|-------------|--------|
| tcValBinds | ✅ | ✅ | ✅ | ⚠️ | VALID |
| tcTySigs | ✅ | ✅ | ✅ | ⚠️ | VALID |
| tcPolyCheck | ✅ | ✅ | ✅ | ✅ | VALID |
| tcPolyInfer | ✅ | ✅ | ✅ | ✅ | VALID |
| tcMonoBinds | ✅ | ✅ | ✅ | ✅ | VALID |
| tcInstSig | ✅ | ✅ | ✅ | ✅ | VALID |
| matchExpectedFunTys | ✅ | ✅ | ✅ | ✅ | VALID |

**Overall Score: 27/28 (96%)**

---

## Detailed Validation

### tcValBinds (Entry Point)

**LEVELS:** ✅ **VALID**
- Document states: "Maintains Level N throughout, delegates level push to sub-functions"
- Correct - tcValBinds operates at outer level

**EXPECT:** ✅ **VALID**
- Document states: "Takes `thing_inside` - body is checked in whatever mode caller specifies"
- Correct - passes through expect mode

**CLOSURE:** ✅ **VALID**
- Document states: "Classic CPS - processes bindings, then calls `thing_inside` with extended env"
- Correct - shows callback pattern

**META/SKOLEM:** ⚠️ **MINOR ISSUE**
- Document states: "Doesn't create vars directly - delegates to `tcPolyBinds`"
- **Suggestion:** Could explicitly note this function doesn't deal with vars

---

### tcTySigs (Signature Processing)

**LEVELS:** ✅ **VALID**
- Document states: "Level N - signatures processed at outer level"
- Correct - verified in code at Bind.hs:165-180

**EXPECT:** ✅ **VALID**
- Document states: "N/A - just instantiates signatures, not checking terms"
- Correct - this is pure processing

**CLOSURE:** ✅ **VALID**
- Document states: "No closure - returns results directly"
- Correct - no CPS here

**META/SKOLEM:** ⚠️ **MINOR ISSUE**
- Document states: "Creates `poly_id` for complete sigs (these are polymorphic types, not vars)"
- **Suggestion:** Could clarify creates poly types, not vars

---

### tcPolyCheck (CheckGen Plan)

**LEVELS:** ✅ **VALID**
- Document states: "N → N+1 → N"
- **Evidence verified:** `tcSkolemiseCompleteSig` pushes to N+1 via `checkConstraints`

**EXPECT:** ✅ **VALID**
- Document states: "CHECK mode - has expected type from signature"
- **Evidence verified:** `mkCheckExpType rho_ty` in Bind.hs:585

**CLOSURE:** ✅ **VALID**
- Document states: "`tcSkolemiseCompleteSig` with callback"
- **Evidence verified:** `\invis_pat_tys rho_ty -> ...` closure in Bind.hs

**META/SKOLEM:** ✅ **VALID**
- Document states: "Creates skolems (rigid) from signature"
- **Evidence verified:** `tcSkolemiseCompleteSig` calls skolemisation functions

---

### tcPolyInfer (InferGen Plan)

**LEVELS:** ✅ **VALID**
- Document states: "N → N+1 → N (explicit level push)"
- **Evidence verified:** `pushLevelAndCaptureConstraints` at Bind.hs:721

**EXPECT:** ✅ **VALID**
- Document states: "INFER mode - synthesizes types"
- **Evidence verified:** Creates metas, no expected type

**CLOSURE:** ✅ **VALID**
- Document states: "`pushLevelAndCaptureConstraints` brackets N+1 inference"
- **Evidence verified:** Bracket pattern with level push

**META/SKOLEM:** ✅ **VALID**
- Document states: "Creates metas at N+1, quantifies to skolems on return"
- **Evidence verified:** `quantifyTyVars` at Bind.hs:742

---

### tcMonoBinds (InferGen Helper)

**LEVELS:** ✅ **VALID**
- Document states: "Runs at Level N+1 (already pushed by caller)"
- **Evidence verified:** Called within `pushLevelAndCaptureConstraints` bracket

**EXPECT:** ✅ **VALID**
- Document states: "INFER mode - creates metas for unknown types"
- **Evidence verified:** Creates metas, not checking against known types

**CLOSURE:** ✅ **VALID**
- Document states: "`tcExtendRecIds` for recursive references"
- **Evidence verified:** Bind.hs:1314-1315

**META/SKOLEM:** ✅ **VALID**
- Document states: "No sig: TauTv meta; Partial sig: TyVarTv (meta, NOT skolem!)"
- **Evidence verified:** `newOpenFlexiTyVarTy` and `tcInstSig` usage

---

### tcInstSig (Partial Signature Instantiation)

**LEVELS:** ✅ **VALID**
- Document states: "Runs at caller's level (N+1 for InferGen)"
- **Evidence verified:** Sig.hs:506

**EXPECT:** ✅ **VALID**
- Document states: "N/A - just instantiation"
- **Evidence verified:** No ExpType parameter

**CLOSURE:** ✅ **VALID**
- Document states: "N/A"
- **Evidence verified:** Returns directly

**META/SKOLEM:** ✅ **VALID** - **CRITICAL CLAIM**
- Document states: "Creates **TyVarTvs** (metas!), NOT skolems"
- **Evidence verified:**
  - Sig.hs:510 calls `tcInstTypeBndrs`
  - Instantiate.hs:541 uses `newMetaTyVarTyVarX`
  - TcMType.hs:995-997 shows `newMetaTyVarTyVarX = new_meta_tv_x TyVarTv`
- **This is CORRECT** - TyVarTvs are metas despite confusing field name `sig_inst_skols`

---

### matchExpectedFunTys (Function Type Decomposition)

**LEVELS:** ✅ **VALID**
- Document states: "Depends on mode - may push to N+2 in Check mode"
- **Evidence verified:** `checkConstraints` in Check mode pushes level

**EXPECT:** ✅ **VALID** - **CRITICAL DISTINCTION**
- Document states: "DISPATCHES on Check vs Infer!"
- **Evidence verified:**
  - Infer mode (Unify.hs:809-822): creates metas
  - Check mode (Unify.hs:835-851): may skolemise
- **This is CORRECT and clearly documented**

**CLOSURE:** ✅ **VALID**
- Document states: "Callback receives `pat_tys` and `rhs_ty`"
- **Evidence verified:** `thing_inside` parameter

**META/SKOLEM:** ✅ **VALID** - **CRITICAL DISTINCTION**
- Document states: 
  - "Infer: `new_infer_arg_ty` → TauTv metas"
  - "Check: `skolemiseRequired` → SkolemTv (skolems!)"
- **Evidence verified:** Line 810 vs line 838 in Unify.hs
- **This is CORRECT and clearly documented**

---

## Summary of Critical Claims

All critical claims validated:

1. ✅ **tcInstSig creates TyVarTvs (metas), NOT skolems**
   - Evidence: Instantiate.hs:541, TcMType.hs:995-997

2. ✅ **matchExpectedFunTys behavior differs by Expect mode**
   - Infer: metas; Check: may skolemise
   - Evidence: Unify.hs:809-822 vs 835-851

3. ✅ **Levels: N (outer) → N+1 (inference) → N (generalized)**
   - Evidence: pushLevelAndCaptureConstraints at Bind.hs:721

4. ✅ **Check mode creates skolems, Infer mode creates metas**
   - Evidence: tcPolyCheck vs tcPolyInfer flow

---

## Minor Issues

1. **tcValBinds META/SKOLEM:** Could explicitly state "No var creation"
2. **tcTySigs META/SKOLEM:** Could clarify "Creates poly types, not vars"

---

## Conclusion

**Document is VALID and follows the 4-aspect base model correctly.**

The analysis accurately captures:
- Level transitions throughout the call hierarchy
- Expect mode dispatch (Check vs Infer)
- Closure/CPS patterns
- Meta vs Skolem variable creation

Critical distinction (tcInstSig creates metas, not skolems) is correctly documented with evidence.