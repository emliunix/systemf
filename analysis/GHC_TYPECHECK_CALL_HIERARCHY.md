# GHC Typechecker Call Hierarchy: `tcApp` / `tcInstFun`

**Scope**: Only the application typechecking chain starting from `tcApp`.  
Other explored functions (case expressions, bindings, skolemisation) are general typechecker machinery and NOT called from `tcApp`/`tcInstFun`.

---

## 1. `tcApp` Top-Level Flow

```mermaid
flowchart TD
    subgraph tcAppModule["GHC.Tc.Gen.App"]
        tcApp["tcApp<br/>rn_expr, exp_res_ty"]
        splitHsApps["splitHsApps"]
        tcInstFun["tcInstFun<br/>implements |-inst"]
        checkResultTy["checkResultTy"]
        tcValArgs["tcValArgs"]
        finishApp["finishApp"]
        rebuildHsApps["rebuildHsApps"]
    end
    
    subgraph tcHeadModule["GHC.Tc.Gen.Head"]
        tcInferAppHead["tcInferAppHead"]
        tcInferAppHeadMaybe["tcInferAppHead_maybe"]
    end
    
    tcApp --> splitHsApps
    tcApp --> tcInferAppHead
    tcApp --> tcInstFun
    tcApp --> checkResultTy
    tcApp --> tcValArgs
    tcApp --> finishApp
    
    tcInferAppHead --> tcInferAppHeadMaybe
    tcInferAppHeadMaybe --> tcInferId
    tcInferAppHeadMaybe --> tcExprWithSig
    tcInferAppHeadMaybe --> runInferRho
    
    finishApp --> rebuildHsApps
```

---

## 2. `tcInstFun` Internal Dispatch

```mermaid
flowchart TD
    subgraph tcInstFunModule["GHC.Tc.Gen.App: tcInstFun"]
        tcInstFun["tcInstFun<br/>do_ql, inst_final, tc_head, fun_sigma, rn_args"]
        
        subgraph goLoop["local go/go1 loop"]
            go["go:<br/>resolve filled QL vars"]
            go1["go1:<br/>main dispatch"]
        end
        
        subgraph rules["Rules from QL paper Fig 4"]
            IALL["IALL:<br/>instantiate invisible foralls/dicts"]
            ITVDQ["ITVDQ:<br/>visible type application"]
            ITYARG["ITYARG:<br/>explicit @Type arg"]
            IVAR["IVAR:<br/>QL inst var in fun position"]
            IARG["IARG:<br/>value argument"]
            IRESULT["IRESULT:<br/>no more args"]
        end
        
        instantiateSigmaQL["instantiateSigmaQL<br/>(creates meta vars)"]
        tcVDQ["tcVDQ"]
        tcVTA["tcVTA"]
        matchActualFunTy["matchActualFunTy"]
        quickLookArg["quickLookArg"]
        newArgTy["new_arg_ty"]
    end
    
    tcInstFun --> go
    go --> go1
    
    go1 -->|"fun_ty = ∀ invisible"| IALL
    go1 -->|"fun_ty = ∀ required"| ITVDQ
    go1 -->|"ETypeArg"| ITYARG
    go1 -->|"fun_ty = κ (QL var)"| IVAR
    go1 -->|"fun_ty = arg→res"| IARG
    go1 -->|"args = []"| IRESULT
    
    IALL --> instantiateSigmaQL
    ITVDQ --> tcVDQ
    ITYARG --> tcVTA
    IVAR --> newArgTy
    IARG --> matchActualFunTy
    matchActualFunTy --> quickLookArg
    
    instantiateSigmaQL --> go
    tcVDQ --> go
    tcVTA --> go
    newArgTy --> go
    quickLookArg --> go
```

---

## 3. Sequence: `f x y :: T` (NoQL path)

```mermaid
sequenceDiagram
    participant tcExpr as "tcExpr"
    participant tcApp as "tcApp"
    participant split as "splitHsApps"
    participant head as "tcInferAppHead"
    participant inst as "tcInstFun"
    participant check as "checkResultTy"
    participant args as "tcValArgs"
    participant finish as "finishApp"
    
    tcExpr->>tcApp: HsApp chain
    
    tcApp->>split: splitHsApps
    split-->>tcApp: "f" + [x, y]
    
    tcApp->>head: infer f's type
    head-->>tcApp: fun_sigma = forall a. a -> a -> Bool
    
    tcApp->>inst: tcInstFun(NoQL, True, ..., fun_sigma, [x, y])
    
    loop go/go1
        inst->>inst: IALL: instantiate a := α
        Note right of inst: fun_ty becomes α -> α -> Bool
        
        inst->>inst: IARG(pos=1): matchActualFunTy<br/>α → (α -> Bool)
        Note right of inst: arg_ty = α, res_ty = α -> Bool
        
        inst->>inst: IARG(pos=2): matchActualFunTy<br/>α -> Bool
        Note right of inst: arg_ty = α, res_ty = Bool
        
        inst->>inst: IRESULT: no more args
    end
    
    inst-->>tcApp: inst_args=[x:α, y:α],<br/>app_res_rho = Bool
    
    tcApp->>check: check Bool ~ T
    check-->>tcApp: res_wrap
    
    tcApp->>args: tcValArgs: typecheck x against α
    tcApp->>args: tcValArgs: typecheck y against α
    args-->>tcApp: tc_args
    
    tcApp->>finish: finishApp
    finish-->>tcApp: rebuildHsApps
    tcApp-->>tcExpr: typed application
```

---

## 4. `tcInstFun` Rules Summary

| Rule | Condition | Action | Creates |
|------|-----------|--------|---------|
| **IALL** | `fun_ty = ∀ invisible. body` | `instantiateSigmaQL` | Meta vars for `∀`, wanted dicts for `=>` |
| **ITVDQ** | `fun_ty = ∀ required. body` + value arg | `tcVDQ` | Substitutes visible type arg |
| **ITYARG** | `ETypeArg @T` | `tcVTA` | Explicit type application |
| **IVAR** | `fun_ty = κ` (unfilled QL inst var) | `new_arg_ty` | Sets `κ := ν₁ → ... → νₙ → res` |
| **IARG** | `fun_ty = arg_ty → res_ty` | `matchActualFunTy` + `quickLookArg` | Extracts arg/res, checks arg |
| **IRESULT** | `args = []` | return | Final result type |

---

## 5. NOT in `tcApp`/`tcInstFun` Chain

These were explored in previous research but are **general expression handlers**, NOT called from `tcApp`:

| Function | Purpose | Entry Point |
|----------|---------|-------------|
| `tcExpr HsCase` | Typecheck `case` expressions | `tcExpr` dispatch |
| `tcCaseMatches` | Match groups for case | Called by `tcExpr HsCase` |
| `tcMatches` / `tcMatch` | Pattern match checking | Called by `tcCaseMatches`, `tcFunBindMatches` |
| `tcPat` / `tcConPat` | Pattern typechecking | Called by `tcMatch` |
| `tcTopBinds` / `tcLocalBinds` | Let/where bindings | `tcExpr` for `HsLet`, `tcTopBinds` for top level |
| `tcPolyBinds` | Polymorphism dispatch | `tcBindGroups` |
| `topSkolemise` | Skolemise expected type | `matchExpectedFunTys`, signature checking |
| `tcInstSkolTyVars` | Create skolem vars | `topSkolemise`, `skolemiseRequired` |
| `topInstantiate` | Instantiate with meta vars | Various (NOT `tcInstFun` — `tcInstFun` uses `instantiateSigmaQL`) |

---

## File Locations

| Function | Module | Line |
|----------|--------|------|
| `tcApp` | `GHC.Tc.Gen.App` | 353 |
| `tcInstFun` | `GHC.Tc.Gen.App` | 607 |
| `tcInferAppHead` | `GHC.Tc.Gen.Head` | 522 |
| `instantiateSigmaQL` | `GHC.Tc.Gen.App` | ~900 |
| `matchActualFunTy` | `GHC.Tc.Utils.Unify` | various |
| `tcValArgs` | `GHC.Tc.Gen.App` | ~1100 |
| `checkResultTy` | `GHC.Tc.Utils.Unify` | various |
