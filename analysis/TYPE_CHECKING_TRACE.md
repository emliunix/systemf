# Trace: Topmost Expression Type Checking Entry Point

This document traces the call chain from the topmost module-level type checking entry point down to the expression-level `tcExpr` function.

## Overview

When GHC type-checks a module, the entry point is `tcRnModule` which eventually calls `tcExpr` for each expression. This trace shows the complete call hierarchy.

## Complete Call Chain

```
tcRnModule (GHC/Tc/Module.hs:200)
  └── tcRnModuleTcRnM (GHC/Tc/Module.hs:235)
        └── tcRnSrcDecls (GHC/Tc/Module.hs:546)
              └── tcTopSrcDecls (GHC/Tc/Module.hs:1702)
                    └── tcTopBinds (GHC/Tc/Module.hs:1736)
                          └── tcValBinds (GHC/Tc/Gen/Bind.hs:260)
                                └── tcPolyInfer / tcMonoBinds (general case)
                                      └── tcRhs (GHC/Tc/Gen/Bind.hs:1585)
                                            └── tcFunBindMatches / tcGRHSsPat
                                                  └── tcMatches (GHC/Tc/Gen/Match.hs)
                                                        └── tcBody (GHC/Tc/Gen/Match.hs:418)
                                                              └── tcPolyLExpr (GHC/Tc/Gen/Expr.hs:120)
                                                                    └── tcPolyExpr (GHC/Tc/Gen/Expr.hs:132)
                                                                          └── tcExpr (GHC/Tc/Gen/Expr.hs:290)
                                                                                ← **THE MAIN EXPRESSION ENTRY POINT**
```

## Detailed Call Chain with Types

### 1. Module Level

**`tcRnModule`** `GHC/Tc/Module.hs:200`
```haskell
tcRnModule :: HscEnv
           -> ModSummary
           -> Bool              -- True <=> save renamed syntax
           -> HsParsedModule
           -> IO (Messages TcRnMessage, Maybe TcGblEnv)
```

**`tcRnModuleTcRnM`** `GHC/Tc/Module.hs:235`
```haskell
tcRnModuleTcRnM :: HscEnv
                -> ModSummary
                -> HsParsedModule
                -> Module
                -> TcRn TcGblEnv
```

### 2. Declaration Level

**`tcRnSrcDecls`** `GHC/Tc/Module.hs:546`
```haskell
tcRnSrcDecls :: Bool  -- False => no 'module M(..) where' header at all
             -> Maybe [(IE GhcRn, Avails)]
             -> [LHsDecl GhcRn]
             -> TcRn TcGblEnv
```

**`tcTopSrcDecls`** `GHC/Tc/Module.hs:1702`
```haskell
tcTopSrcDecls :: HsGroup GhcRn -> TcM (TcGblEnv, TcLclEnv)
```

### 3. Binding Level

**`tcTopBinds`** `GHC/Tc/Module.hs:1736`
```haskell
tcTopBinds :: [(RecFlag, LHsBinds GhcRn)] -> [LSig GhcRn]
           -> TcM (TcGblEnv, TcLclEnv)
```

**`tcValBinds`** `GHC/Tc/Gen/Bind.hs:260`
```haskell
tcValBinds :: TopLevelFlag
           -> [(RecFlag, LHsBinds GhcRn)] -> [LSig GhcRn]
           -> TcM thing
           -> TcM ([(RecFlag, LHsBinds GhcTc)], thing)
```

**`tcPolyInfer`** `GHC/Tc/Gen/Bind.hs:714`
```haskell
tcPolyInfer :: TopLevelFlag
            -> RecFlag
            -> TcPragEnv -> TcSigFun
            -> [LHsBind GhcRn]
            -> TcM (LHsBinds GhcTc, [Scaled TcId])
```

**`tcMonoBinds`** `GHC/Tc/Gen/Bind.hs:1289`
```haskell
tcMonoBinds :: RecFlag
            -> TcSigFun -> LetBndrSpec
            -> [LHsBind GhcRn]
            -> TcM (LHsBinds GhcTc, [MonoBindInfo])
```

**`tcRhs`** `GHC/Tc/Gen/Bind.hs:1585`
```haskell
tcRhs :: TcMonoBind -> TcM (HsBind GhcTc)
```

### 4. Match/Pattern Level

**`tcFunBindMatches`** `GHC/Tc/Gen/Match.hs:103`
```haskell
tcFunBindMatches :: UserTypeCtxt
                 -> Name            -- Function name
                 -> Mult            -- The multiplicity of the binder
                 -> MatchGroup GhcRn (LHsExpr GhcRn)
                 -> [ExpPatType]    -- Scoped skolemised binders
                 -> ExpRhoType      -- Expected type of function
                 -> TcM (HsWrapper, MatchGroup GhcTc (LHsExpr GhcTc))
```

**`tcBody`** `GHC/Tc/Gen/Match.hs:418`
```haskell
tcBody :: LHsExpr GhcRn -> ExpRhoType -> TcM (LHsExpr GhcTc)
```

### 5. Expression Level

**`tcPolyLExpr`** `GHC/Tc/Gen/Expr.hs:120`
```haskell
tcPolyLExpr :: LHsExpr GhcRn -> ExpSigmaType -> TcM (LHsExpr GhcTc)
```

**`tcPolyExpr`** `GHC/Tc/Gen/Expr.hs:132`
```haskell
tcPolyExpr :: HsExpr GhcRn -> ExpSigmaType -> TcM (HsExpr GhcTc)
```

**`tcExpr`** `GHC/Tc/Gen/Expr.hs:290` ← **MAIN ENTRY POINT**
```haskell
tcExpr :: HsExpr GhcRn
       -> ExpRhoType   -- DeepSubsumption <=> when checking, this type
                       --                     is deeply skolemised
       -> TcM (HsExpr GhcTc)
```

## Alternative Entry: GHCi's `:type` Command

For interactive expression type checking (GHCi), the entry point is:

**`tcRnExpr`** `GHC/Tc/Module.hs:2615`
```haskell
tcRnExpr :: HscEnv
         -> TcRnExprMode
         -> LHsExpr GhcPs
         -> IO (Messages TcRnMessage, Maybe Type)
```

This calls:
```
tcRnExpr
  └── tcInferSigma (line 2631, for TM_Inst mode)
        └── tcInferExpr IIF_Sigma
              └── runInfer IIF_Sigma IFRR_Any
                    └── tcExpr
```

After inference:
1. `simplifyInfer` (line 2638) - Generalization at let
2. `zonkTcType` (line 2649) - Zonking the final type

## Key Functions Along the Chain

| Function | File | Line | Purpose |
|----------|------|------|---------|
| `tcRnModule` | GHC/Tc/Module.hs | 200 | Top-level module type checking |
| `tcTopSrcDecls` | GHC/Tc/Module.hs | 1702 | Type-check top-level declarations |
| `tcTopBinds` | GHC/Tc/Module.hs | 1736 | Type-check top-level bindings |
| `tcPolyInfer` | GHC/Tc/Gen/Bind.hs | 714 | Generalization at let bindings |
| `tcMonoBinds` | GHC/Tc/Gen/Bind.hs | 1289 | Type-check monomorphic bindings |
| `tcRhs` | GHC/Tc/Gen/Bind.hs | 1585 | Type-check right-hand side |
| `tcFunBindMatches` | GHC/Tc/Gen/Match.hs | 103 | Type-check function matches |
| `tcBody` | GHC/Tc/Gen/Match.hs | 418 | Type-check expression body |
| `tcPolyLExpr` | GHC/Tc/Gen/Expr.hs | 120 | Type-check poly expression (located) |
| `tcExpr` | GHC/Tc/Gen/Expr.hs | 290 | **Main expression type checker** |

## Type Signatures Throughout

The types transform as we go down the chain:

- `HsParsedModule` (parsed)
- `HsGroup GhcRn` (renamed declarations)
- `LHsBinds GhcRn` (renamed bindings)
- `LHsExpr GhcRn` (renamed expression)
- `HsExpr GhcTc` (type-checked expression)

The expected type flows downward:
- `ExpSigmaType` (can be a polymorphic type)
- `ExpRhoType` (no top-level foralls - instantiated)

## Related Documentation

- See `TYPE_INFERENCE.md` for how `tcExpr` works in Check vs Infer mode
- See `HSWRAPPER_ARCHITECTURE.md` for evidence recording
- See `DESUGARING_PATTERNS.md` for pattern binding details

---

*Generated from GHC source code analysis*
