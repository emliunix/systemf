# Exploration Session: ValBinds in GHC

**Date:** 2024-03-28
**Session ID:** A
**Focus:** Understanding ValBinds structure and how GHC represents value bindings
**Status:** Validated
**Based on:** EXPLORATION-NOTES-GUIDE.md

## Central Question

How does GHC represent value bindings (let, where, top-level declarations) in its AST? What is the ValBinds structure and how does it relate to pattern bindings and other binding constructs?

---

## Findings

### Finding 1: HsLocalBindsLR Data Type - Top-level Binding Container

**Claim:** GHC uses `HsLocalBindsLR` as the container for local bindings in `let` and `where` clauses, with three variants: `HsValBinds` for value bindings, `HsIPBinds` for implicit parameters, and `EmptyLocalBinds` for empty binding groups.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:59-80`

**Evidence:**
```haskell
-- | Haskell Local Bindings with separate Left and Right identifier types
--
-- Bindings in a 'let' expression
-- or a 'where' clause
data HsLocalBindsLR idL idR
  = HsValBinds
        (XHsValBinds idL idR)
        (HsValBindsLR idL idR)
      -- ^ Haskell Value Bindings

  | HsIPBinds
        (XHsIPBinds idL idR)
        (HsIPBinds idR)
      -- ^ Haskell Implicit Parameter Bindings

  | EmptyLocalBinds (XEmptyLocalBinds idL idR)
      -- ^ Empty Local Bindings

  | XHsLocalBindsLR
        !(XXHsLocalBindsLR idL idR)
```

**Confidence:** High

**Implications:** This is the entry point for all local bindings. The `HsValBinds` constructor wraps `HsValBindsLR` which contains the actual value bindings. The separation of `idL` and `idR` types supports different identifier types on left and right sides during renaming.

**VALIDATED:** Yes
**Source Check:** Verified - Lines 59-80 match exactly
**Logic Check:** Sound - The code clearly shows the four constructors including the extension constructor `XHsLocalBindsLR`
**Notes:** None. The claim accurately describes the structure, though it doesn't mention the fourth variant `XHsLocalBindsLR` which is a Trees That Grow extension point.

---

### Finding 2: HsValBindsLR Data Type - Value Bindings Container

**Claim:** `HsValBindsLR` represents collections of value bindings (not implicit parameters). It has two forms: `ValBinds` for pre-renaming (parsed source) and `XValBindsLR` for post-renaming (renamed/typechecked) which uses `HsValBindGroups` for dependency-analyzed bindings.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:91-107`

**Evidence:**
```haskell
-- | Haskell Value bindings with separate Left and Right identifier types
-- (not implicit parameters)
-- Used for both top level and nested bindings
-- May contain pattern synonym bindings
data HsValBindsLR idL idR
  = -- | Value Bindings In
    --
    -- Before renaming RHS; idR is always RdrName
    -- Not dependency analysed
    -- Recursive by default
    ValBinds
        (XValBinds idL idR)
        (LHsBindsLR idL idR) [LSig idR]

    -- | Value Bindings Out
    --
    -- After renaming RHS; idR can be Name or Id Dependency analysed,
    -- later bindings in the list may depend on earlier ones.
  | XValBindsLR
      !(XXValBindsLR idL idR)
```

**Confidence:** High

**Implications:** The `ValBinds` constructor holds:
1. An extension field `XValBinds` (for annotation data)
2. `LHsBindsLR` - the actual list of bindings
3. `[LSig idR]` - type signatures associated with these bindings

After renaming, `XValBindsLR` is used with `HsValBindGroups` for strongly-connected component (SCC) based dependency analysis.

**VALIDATED:** Yes
**Source Check:** Verified - Lines 91-107 match exactly
**Logic Check:** Sound - The structure matches the description. The type instance in `GHC.Hs.Binds.hs:82` shows `XXValBindsLR (GhcPass pL) _ = HsValBindGroups pL`
**Notes:** None. The claim is accurate.

---

### Finding 3: HsBindLR Data Type - Individual Binding Representation

**Claim:** Individual bindings are represented by `HsBindLR` with four constructors: `FunBind` for function definitions, `PatBind` for pattern bindings, `VarBind` for variable bindings (typechecker-generated), and `PatSynBind` for pattern synonym definitions.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:177-235`

**Evidence:**
```haskell
-- | Haskell Binding with separate Left and Right id's
data HsBindLR idL idR
  = -- | Function-like Binding
    FunBind {
        fun_ext :: XFunBind idL idR,
        fun_id :: LIdP idL,
        fun_matches :: MatchGroup idR (LHsExpr idR)
    }

  -- | Pattern Binding
  | PatBind {
        pat_ext    :: XPatBind idL idR,
        pat_lhs    :: LPat idL,
        pat_mult   :: HsMultAnn idL,
        pat_rhs    :: GRHSs idR (LHsExpr idR)
    }

  -- | Variable Binding
  | VarBind {
        var_ext    :: XVarBind idL idR,
        var_id     :: IdP idL,
        var_rhs    :: LHsExpr idR
    }

  -- | Pattern Synonym Binding
  | PatSynBind
        (XPatSynBind idL idR)
        (PatSynBind idL idR)

  | XHsBindsLR !(XXHsBindsLR idL idR)
```

**Confidence:** High

**Implications:** 
- `FunBind` handles `f x = e`, `f = \x -> e`, and even `!x = e` (strict bindings)
- `PatBind` handles `Just x = e`, `(x) = e`, and `x :: Ty = e` - but NOT simple variables
- `VarBind` is generated by the typechecker for dictionary bindings
- `PatSynBind` wraps `PatSynBind` data type for pattern synonym definitions

**VALIDATED:** Yes
**Source Check:** Verified - Lines 177-235 contain HsBindLR with all described constructors
**Logic Check:** Sound - The four constructors are present as described. Note: There's also a fifth constructor `XHsBindsLR` for extension purposes.
**Notes:** The claim doesn't mention `XHsBindsLR` (extension constructor), but this is acceptable as it's a Trees That Grow mechanism, not a semantic constructor.

---

### Finding 4: FunBind vs PatBind Distinction

**Claim:** The distinction between `FunBind` and `PatBind` is subtle: `FunBind` covers function-like bindings and simple variables, while `PatBind` covers constructor patterns and type-annotated bindings. The key is that `FunBind` has the binder name directly in `fun_id`, while `PatBind` has a pattern in `pat_lhs`.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:125-174`

**Evidence:**
```haskell
{- Note [FunBind vs PatBind]
   ~~~~~~~~~~~~~~~~~~~~~~~~~
The distinction between FunBind and PatBind is a bit subtle. FunBind covers
patterns which resemble function bindings and simple variable bindings.

    f x = e
    f !x = e
    f = e
    !x = e          -- FunRhs has SrcStrict
    x `f` y = e     -- FunRhs has Infix

The actual patterns and RHSs of a FunBind are encoding in fun_matches.

By contrast, PatBind represents data constructor patterns, as well as a few
other interesting cases. Namely,

    Just x = e
    (x) = e
    x :: Ty = e
```

**Confidence:** High

**Implications:** The choice between `FunBind` and `PatBind` affects type inference. `FunBind` gets special treatment in `tcMonoBinds` for better type inference, and instance declarations can only use `FunBind`.

**VALIDATED:** Yes
**Source Check:** Verified - Note spans lines 125-174 (actually ends at line 174 as claimed)
**Logic Check:** Sound - The evidence matches the claim exactly. The structural difference (fun_id vs pat_lhs) is correctly identified in the HsBindLR definition.
**Notes:** The note mentions `mc_fixity` and `mc_strictness` fields in the Match context which provide additional information about FunBind patterns.

---

### Finding 5: HsLet Expression - Using HsLocalBinds

**Claim:** The `HsLet` constructor in `HsExpr` uses `HsLocalBinds` to represent the bindings in a let expression: `let <bindings> in <expr>`.

**Source:** `compiler/Language/Haskell/Syntax/Expr.hs:413-416`

**Evidence:**
```haskell
  -- | let(rec)
  | HsLet       (XLet p)
                (HsLocalBinds p)
                (LHsExpr  p)
```

**Confidence:** High

**Implications:** This shows how `HsLocalBinds` (which contains `HsValBinds` which contains `HsValBindsLR`) is integrated into expression syntax. A let expression wraps an `HsLocalBinds` containing the bindings and an expression for the body.

**VALIDATED:** Yes
**Source Check:** Verified - Lines 413-416 match exactly
**Logic Check:** Sound - The evidence directly supports the claim.
**Notes:** None. The claim is accurate.

---

### Finding 6: Top-Level Value Bindings in HsGroup

**Claim:** At the module level, top-level value bindings are stored in `HsGroup` using the same `HsValBinds` structure under the field `hs_valds`.

**Source:** `compiler/Language/Haskell/Syntax/Decls.hs:203-231`

**Evidence:**
```haskell
data HsGroup p
  = HsGroup {
        hs_ext    :: XCHsGroup p,
        hs_valds  :: HsValBinds p,
        hs_splcds :: [LSpliceDecl p],
        hs_tyclds :: [TyClGroup p],
        hs_derivds :: [LDerivDecl p],
        hs_fixds  :: [LFixitySig p],
        hs_defds  :: [LDefaultDecl p],
        hs_fords  :: [LForeignDecl p],
        hs_warnds :: [LWarnDecls p],
        hs_annds  :: [LAnnDecl p],
        hs_ruleds :: [LRuleDecls p],
        hs_docs   :: [LDocDecl p]
    }
```

**Confidence:** High

**Implications:** The same `HsValBinds` structure is used for both:
- Local bindings (let, where clauses)
- Top-level bindings (module declarations)

This unifies the representation across both contexts.

**VALIDATED:** Yes
**Source Check:** Verified - Lines 203-231 contain HsGroup with hs_valds :: HsValBinds p
**Logic Check:** Sound - The claim is directly supported by the source code.
**Notes:** None. The claim accurately describes the unified representation.

---

### Finding 7: Post-Renaming Binding Representation (HsValBindGroups)

**Claim:** After renaming, bindings are organized into strongly-connected components using `HsValBindGroups`, which stores `(RecFlag, LHsBinds)` pairs representing dependency-analyzed binding groups.

**Source:** `compiler/GHC/Hs/Binds.hs:84-90`

**Evidence:**
```haskell
data HsValBindGroups p   -- Divided into strongly connected components
  = HsVBG [HsValBindGroup (GhcPass p)] [LSig GhcRn]

type family HsValBindGroup p
type instance HsValBindGroup GhcPs = ()
type instance HsValBindGroup GhcRn = (RecFlag, LHsBinds GhcRn)
type instance HsValBindGroup GhcTc = (RecFlag, LHsBinds GhcTc)
```

**Confidence:** High

**Implications:** 
- For parsed source (`GhcPs`): No SCC information (empty `()`)
- For renamed source (`GhcRn`): Bindings organized into `(RecFlag, LHsBinds)` pairs
- For typechecked source (`GhcTc`): Same structure with typechecked bindings
- `RecFlag` indicates whether the group is recursive (`Recursive`) or not (`NonRecursive`)

**VALIDATED:** Yes
**Source Check:** Verified - Lines 84-90 in GHC/Hs/Binds.hs match
**Logic Check:** Sound - The type family instances correctly show the progression from () to (RecFlag, LHsBinds)
**Notes:** The claim says "uses HsValBindGroups" which is correct. Note that `HsValBindGroups` (plural) contains a list of `HsValBindGroup` (singular) elements.

---

### Finding 8: Type-Checked Binding Output (AbsBinds)

**Claim:** The typechecker outputs bindings wrapped in `AbsBinds` (abstract bindings) which represent type-generalized bindings with polymorphic exports and monomorphic local definitions.

**Source:** `compiler/GHC/Hs/Binds.hs:166-186`

**Evidence:**
```haskell
-- | Typechecked, generalised bindings, used in the output to the type checker.
-- See Note [AbsBinds].
data AbsBinds = AbsBinds {
      abs_tvs     :: [TyVar],
      abs_ev_vars :: [EvVar],
      abs_exports :: [ABExport],
      abs_ev_binds :: [TcEvBinds],
      abs_binds    :: LHsBinds GhcTc,
      abs_sig :: Bool
  }

data ABExport
  = ABE { abe_poly      :: Id
        , abe_mono      :: Id
        , abe_wrap      :: HsWrapper
        , abe_prags     :: TcSpecPrags
        }
```

**Confidence:** High

**Implications:**
- `abs_tvs`: Type variables abstracted over the binding group
- `abs_ev_vars`: Evidence variables (dictionaries) abstracted over
- `abs_exports`: Maps monomorphic local Ids to polymorphic exported Ids
- `abs_binds`: The actual monomorphic bindings
- This structure enables polymorphic recursion and type class constraint handling

**VALIDATED:** Partial
**Source Check:** Mismatch - AbsBinds is at lines 167-185 (not 166-186). ABExport is at lines 201-207.
**Logic Check:** Sound - The evidence matches the claim, but line numbers are slightly off.
**Notes:** The `abs_ev_vars` field comment in the source says "Includes equality constraints" which adds detail. The `abs_sig` field is explained in detail in Note [The abs_sig field of AbsBinds].

---

### Finding 9: Pattern Synonym Bindings

**Claim:** Pattern synonyms have their own binding type `PatSynBind` which is distinct from value bindings and stored within the `HsBindLR` type via the `PatSynBind` constructor.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:238-246`

**Evidence:**
```haskell
-- | Pattern Synonym binding
data PatSynBind idL idR
  = PSB { psb_ext  :: XPSB idL idR,
          psb_id   :: LIdP idL,                -- ^ Name of the pattern synonym
          psb_args :: HsPatSynDetails idR,     -- ^ Formal parameter names
          psb_def  :: LPat idR,                -- ^ Right-hand side
          psb_dir  :: HsPatSynDir idR          -- ^ Directionality
     }
   | XPatSynBind !(XXPatSynBind idL idR)

-- Pattern synonym direction
data HsPatSynDir id
  = Unidirectional
  | ImplicitBidirectional
  | ExplicitBidirectional (MatchGroup id (LHsExpr id))
```

**Confidence:** High

**Implications:**
- Pattern synonyms can be unidirectional (pattern only), implicitly bidirectional, or explicitly bidirectional
- `psb_args` captures the formal parameters using `HsPatSynDetails`
- `psb_def` is the pattern that defines what the synonym matches
- Pattern synonyms appear alongside value bindings in binding groups but are processed separately

**VALIDATED:** Yes
**Source Check:** Verified - Lines 238-246 contain PatSynBind, HsPatSynDir is at lines 534-537
**Logic Check:** Sound - The evidence supports all aspects of the claim.
**Notes:** The `HsPatSynDir` type is defined later in the file (lines 534-537), not immediately after `PatSynBind`. This is a minor organization detail.

---

### Finding 10: Type Signature Storage with Bindings

**Claim:** Type signatures are stored alongside bindings in `ValBinds` as `[LSig idR]`, allowing signatures to be associated with their corresponding bindings before being attached to individual identifiers.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:97-99`

**Evidence:**
```haskell
    ValBinds
        (XValBinds idL idR)
        (LHsBindsLR idL idR) [LSig idR]
```

**Confidence:** High

**Implications:**
- Signatures and bindings travel together through the compilation pipeline
- This allows the renamer to connect signatures with their binders
- The `Sig` type (from the same module) represents various signature forms: `TypeSig`, `ClassOpSig`, `InlineSig`, `SpecSig`, etc.

**VALIDATED:** Yes
**Source Check:** Verified - Lines 97-99 show ValBinds with `[LSig idR]`
**Logic Check:** Sound - The evidence directly supports the claim.
**Notes:** None. The claim is accurate.

---

## Summary

GHC's ValBinds structure forms a layered hierarchy:

1. **HsLocalBindsLR**: Container for let/where bindings (3 variants: value, implicit params, empty)
2. **HsValBindsLR**: Container for value bindings (2 forms: pre-renaming `ValBinds`, post-renaming `XValBindsLR`)
3. **HsBindLR**: Individual binding (4 types: `FunBind`, `PatBind`, `VarBind`, `PatSynBind`)
4. **AbsBinds**: Typechecker's output structure for generalized bindings

The same structures are used for:
- Local bindings (let, where) via `HsLet` in expressions
- Top-level bindings via `HsGroup.hs_valds` in modules

Key design decisions:
- Separation of `idL` and `idR` supports renaming where LHS and RHS may have different identifier types
- `FunBind` vs `PatBind` distinction enables better type inference for function bindings
- SCC-based organization after renaming enables proper dependency analysis

---

## Open Questions

- [ ] How do instance method bindings fit into this structure?
- [ ] What is the exact flow from `ValBinds` to `AbsBinds` during typechecking?
- [ ] How are strictness annotations propagated through these structures?

---

## Contradictions

None identified.

---

## Validation Summary

- **Claims validated:** 9
- **Claims with issues:** 1 (Finding 8 has minor line number discrepancy)
- **Source mismatches:** 
  - Finding 8: AbsBinds is at lines 167-185 (not 166-186), ABExport at 201-207
- **Recommended actions:**
  - Finding 1: Keep - Verified
  - Finding 2: Keep - Verified
  - Finding 3: Keep - Verified
  - Finding 4: Keep - Verified
  - Finding 5: Keep - Verified
  - Finding 6: Keep - Verified
  - Finding 7: Keep - Verified
  - Finding 8: Revise line numbers to 167-185 for AbsBinds, 201-207 for ABExport
  - Finding 9: Keep - Verified
  - Finding 10: Keep - Verified

---

**Validation Date:** 2026-03-28
**Validator:** Automated source verification against GHC compiler codebase
**Overall Assessment:** The analysis is highly accurate with excellent source citations. Only minor line number adjustment needed for Finding 8.
