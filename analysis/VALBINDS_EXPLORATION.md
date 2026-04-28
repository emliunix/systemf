# ValBinds in GHC

**Status:** Validated  
**Last Updated:** 2024-03-28  
**Central Question:** How does GHC represent value bindings in its AST?

## Summary

GHC uses a layered AST structure to represent value bindings. The hierarchy flows from outer containers (`HsLocalBindsLR`) through binding collections (`HsValBindsLR`) to individual bindings (`HsBindLR`). The same structures are used for both local bindings (let/where) and top-level module declarations. The representation evolves through compilation phases: pre-renaming (`ValBinds`), post-renaming (`HsValBindGroups` with SCCs), and post-typechecking (`AbsBinds`).

---

## Claims

### 1. AST Type Hierarchy

#### 1.1 HsLocalBindsLR - Top-Level Binding Container
GHC uses `HsLocalBindsLR` as the container for local bindings in `let` and `where` clauses, with three variants: `HsValBinds` for value bindings, `HsIPBinds` for implicit parameters, and `EmptyLocalBinds` for empty binding groups.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:59-80`

```haskell
data HsLocalBindsLR idL idR
  = HsValBinds
        (XHsValBinds idL idR)
        (HsValBindsLR idL idR)

  | HsIPBinds
        (XHsIPBinds idL idR)
        (HsIPBinds idR)

  | EmptyLocalBinds (XEmptyLocalBinds idL idR)

  | XHsLocalBindsLR
        !(XXHsLocalBindsLR idL idR)
```

*Merged: 2024-03-28*

---

#### 1.2 HsValBindsLR - Value Bindings Container
`HsValBindsLR` represents collections of value bindings (not implicit parameters). It has two forms: `ValBinds` for pre-renaming (parsed source) and `XValBindsLR` for post-renaming (renamed/typechecked) which uses `HsValBindGroups` for dependency-analyzed bindings.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:91-107`

```haskell
data HsValBindsLR idL idR
  = -- Before renaming RHS; idR is always RdrName
    -- Not dependency analysed
    -- Recursive by default
    ValBinds
        (XValBinds idL idR)
        (LHsBindsLR idL idR) [LSig idR]

    -- After renaming RHS; idR can be Name or Id
    -- Dependency analysed, later bindings may depend on earlier ones
  | XValBindsLR
      !(XXValBindsLR idL idR)
```

*Merged: 2024-03-28*

---

#### 1.3 HsBindLR - Individual Binding Representation
Individual bindings are represented by `HsBindLR` with four constructors: `FunBind` for function definitions, `PatBind` for pattern bindings, `VarBind` for variable bindings (typechecker-generated), and `PatSynBind` for pattern synonym definitions.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:177-235`

```haskell
data HsBindLR idL idR
  = FunBind {
        fun_ext :: XFunBind idL idR,
        fun_id :: LIdP idL,
        fun_matches :: MatchGroup idR (LHsExpr idR)
    }

  | PatBind {
        pat_ext    :: XPatBind idL idR,
        pat_lhs    :: LPat idL,
        pat_mult   :: HsMultAnn idL,
        pat_rhs    :: GRHSs idR (LHsExpr idR)
    }

  | VarBind {
        var_ext    :: XVarBind idL idR,
        var_id     :: IdP idL,
        var_rhs    :: LHsExpr idR
    }

  | PatSynBind
        (XPatSynBind idL idR)
        (PatSynBind idL idR)

  | XHsBindsLR !(XXHsBindsLR idL idR)
```

*Merged: 2024-03-28*

---

### 2. Binding Type Distinctions

#### 2.1 FunBind vs PatBind Distinction
The distinction between `FunBind` and `PatBind` is subtle: `FunBind` covers function-like bindings and simple variables, while `PatBind` covers constructor patterns and type-annotated bindings. The key is that `FunBind` has the binder name directly in `fun_id`, while `PatBind` has a pattern in `pat_lhs`.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:125-174`

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

**Implications:** The choice between `FunBind` and `PatBind` affects type inference. `FunBind` gets special treatment in `tcMonoBinds` for better type inference, and instance declarations can only use `FunBind`.

*Merged: 2024-03-28*

---

### 3. Processing Pipeline

#### 3.1 Post-Renaming Binding Representation (HsValBindGroups)
After renaming, bindings are organized into strongly-connected components using `HsValBindGroups`, which stores `(RecFlag, LHsBinds)` pairs representing dependency-analyzed binding groups.

**Source:** `compiler/GHC/Hs/Binds.hs:84-90`

```haskell
data HsValBindGroups p   -- Divided into strongly connected components
  = HsVBG [HsValBindGroup (GhcPass p)] [LSig GhcRn]

type family HsValBindGroup p
type instance HsValBindGroup GhcPs = ()
type instance HsValBindGroup GhcRn = (RecFlag, LHsBinds GhcRn)
type instance HsValBindGroup GhcTc = (RecFlag, LHsBinds GhcTc)
```

**Implications:** 
- For parsed source (`GhcPs`): No SCC information (empty `()`)
- For renamed source (`GhcRn`): Bindings organized into `(RecFlag, LHsBinds)` pairs
- For typechecked source (`GhcTc`): Same structure with typechecked bindings
- `RecFlag` indicates whether the group is recursive (`Recursive`) or not (`NonRecursive`)

*Merged: 2024-03-28*

---

#### 3.2 Type-Checked Binding Output (AbsBinds)
The typechecker outputs bindings wrapped in `AbsBinds` (abstract bindings) which represent type-generalized bindings with polymorphic exports and monomorphic local definitions.

**Source:** `compiler/GHC/Hs/Binds.hs:167-185`  
*Note: Line numbers corrected from 166-186 during validation*

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

**Implications:**
- `abs_tvs`: Type variables abstracted over the binding group
- `abs_ev_vars`: Evidence variables (dictionaries) abstracted over
- `abs_exports`: Maps monomorphic local Ids to polymorphic exported Ids
- `abs_binds`: The actual monomorphic bindings
- This structure enables polymorphic recursion and type class constraint handling

*Merged: 2024-03-28*  
*Validation Note: Line numbers corrected (was 166-186, corrected to 167-185)*

---

### 4. Integration Points

#### 4.1 HsLet Expression
The `HsLet` constructor in `HsExpr` uses `HsLocalBinds` to represent the bindings in a let expression: `let <bindings> in <expr>`.

**Source:** `compiler/Language/Haskell/Syntax/Expr.hs:413-416`

```haskell
  -- | let(rec)
  | HsLet       (XLet p)
                (HsLocalBinds p)
                (LHsExpr  p)
```

**Implications:** This shows how `HsLocalBinds` (which contains `HsValBinds` which contains `HsValBindsLR`) is integrated into expression syntax. A let expression wraps an `HsLocalBinds` containing the bindings and an expression for the body.

*Merged: 2024-03-28*

---

#### 4.2 Top-Level Value Bindings in HsGroup
At the module level, top-level value bindings are stored in `HsGroup` using the same `HsValBinds` structure under the field `hs_valds`.

**Source:** `compiler/Language/Haskell/Syntax/Decls.hs:203-231`

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

**Implications:** The same `HsValBinds` structure is used for both:
- Local bindings (let, where clauses)
- Top-level bindings (module declarations)

This unifies the representation across both contexts.

*Merged: 2024-03-28*

---

#### 4.3 Type Signature Storage with Bindings
Type signatures are stored alongside bindings in `ValBinds` as `[LSig idR]`, allowing signatures to be associated with their corresponding bindings before being attached to individual identifiers.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:97-99`

```haskell
    ValBinds
        (XValBinds idL idR)
        (LHsBindsLR idL idR) [LSig idR]
```

**Implications:**
- Signatures and bindings travel together through the compilation pipeline
- This allows the renamer to connect signatures with their binders
- The `Sig` type (from the same module) represents various signature forms: `TypeSig`, `ClassOpSig`, `InlineSig`, `SpecSig`, etc.

*Merged: 2024-03-28*

---

### 5. Pattern Synonyms

#### 5.1 Pattern Synonym Bindings
Pattern synonyms have their own binding type `PatSynBind` which is distinct from value bindings and stored within the `HsBindLR` type via the `PatSynBind` constructor.

**Source:** `compiler/Language/Haskell/Syntax/Binds.hs:238-246`

```haskell
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

**Implications:**
- Pattern synonyms can be unidirectional (pattern only), implicitly bidirectional, or explicitly bidirectional
- `psb_args` captures the formal parameters using `HsPatSynDetails`
- `psb_def` is the pattern that defines what the synonym matches
- Pattern synonyms appear alongside value bindings in binding groups but are processed separately

*Merged: 2024-03-28*

---

## Structural Overview

```
HsLocalBindsLR (let/where container)
    |
    +-- HsValBinds
    |       |
    |       +-- HsValBindsLR (value bindings collection)
    |               |
    |               +-- ValBinds (pre-renaming)
    |               |       |
    |               |       +-- LHsBindsLR [HsBindLR] (individual bindings)
    |               |       +-- [LSig] (type signatures)
    |               |
    |               +-- XValBindsLR (post-renaming)
    |                       |
    |                       +-- HsValBindGroups (SCC-organized)
    |                               |
    |                               +-- (RecFlag, LHsBinds)
    |
    +-- HsIPBinds (implicit parameters)
    +-- EmptyLocalBinds

Post-Typechecking:
    |
    +-- AbsBinds (generalized bindings)
            |
            +-- abs_tvs :: [TyVar]
            +-- abs_ev_vars :: [EvVar]
            +-- abs_exports :: [ABExport]
            +-- abs_binds :: LHsBinds GhcTc
```

---

## Key Design Decisions

1. **Separation of `idL` and `idR`**: Supports renaming where LHS and RHS may have different identifier types (e.g., `RdrName` on left, `Name` on right during renaming).

2. **FunBind vs PatBind distinction**: Enables better type inference for function bindings. `FunBind` gets special treatment in `tcMonoBinds`.

3. **SCC-based organization after renaming**: Enables proper dependency analysis. Bindings are grouped into strongly-connected components for correct recursive binding handling.

4. **Unified representation**: Same structures used for local bindings (let/where) and top-level declarations, simplifying the AST design.

---

## Open Questions

- How do instance method bindings fit into this structure?
- What is the exact flow from `ValBinds` to `AbsBinds` during typechecking?
- How are strictness annotations propagated through these structures?

---

## Related Topics

- `EXPLORATION-NOTES-GUIDE.md` - Exploration methodology
- `PATTERN_TC_ANALYSIS.md` - Pattern typechecking
- `TYPE_INFERENCE.md` - Type inference details
- `compiler/Language/Haskell/Syntax/Binds.hs` - Source definitions
- `compiler/GHC/Hs/Binds.hs` - Post-renaming structures

---

*Merged from: VALBINDS_2024-03-28_A_TEMP.md*  
*Validation: 9 claims fully validated, 1 claim with corrected line numbers (Finding 8)*  
*Merge Date: 2024-03-28*
