# GHC Type Inference Documentation Index

## 📚 Documentation Files

| Document | Content | Best For |
|----------|---------|----------|
| **README.md** | Entry point, learning paths | Getting oriented |
| **TYPE_INFERENCE.md** | Complete type inference system | Full understanding |
| **PATTERN_TC_ANALYSIS.md** | VarPat/SigPat/ConPat type-checking | Pattern analysis |
| **HSWRAPPER_ARCHITECTURE.md** | Evidence recording & Core translation | Wrapper mechanics |
| **COMPILER_DIRECTORY_GUIDE.md** | Compiler directory organization | Finding code |
| **CORE_SYSTEM_F.md** | Core language & translation | Core generation |
| **FLOW_DIAGRAMS.md** | Visual flow diagrams | Visual learners |
| **HIGHERRANK_POLY.md** | Higher-rank polymorphism | Advanced types |
| **DESUGARING_PATTERNS.md** | Pattern desugaring & AABS2 implementation | Desugaring details |
| **UNIQUENESS_MANAGEMENT.md** | Global unique identifier system | Variable creation |
| **RULES_TO_CODE_MAPPING.md** | Paper rules to GHC code correspondence | Rule implementations |
| **SKOLEMISE_TRACE.md** | Step-by-step trace of deeplySkolemise | Implementation details |
| **putting-2007-rules.tex** | Formal bidirectional typing rules (Jones 2007) | Theory reference |

---

## 🎯 Learning Paths

### Path 1: Understanding Type Inference (45 min)
1. **TYPE_INFERENCE.md** - Complete overview
2. **FLOW_DIAGRAMS.md** - Visual reinforcement

### Path 2: Understanding Evidence/Wrappers (30 min)
1. **HSWRAPPER_ARCHITECTURE.md** - Architecture & variants
2. **TYPE_INFERENCE.md** Part 3 - Type storage

### Path 3: Finding Code in the Compiler
1. **COMPILER_DIRECTORY_GUIDE.md** - Directory map
2. **TYPE_INFERENCE.md** Part 5 - Key files

### Path 4: Complete Understanding (2-3 hours)
1. **TYPE_INFERENCE.md**
2. **HSWRAPPER_ARCHITECTURE.md**
3. **CORE_SYSTEM_F.md**
4. **FLOW_DIAGRAMS.md**

### Path 5: Deep Dive into Desugaring (45 min)
1. **DESUGARING_PATTERNS.md** - AABS2 implementation
2. **HSWRAPPER_ARCHITECTURE.md** - Wrapper translation
3. **UNIQUENESS_MANAGEMENT.md** - Variable creation

### Path 6: Understanding Variable Identity (30 min)
1. **UNIQUENESS_MANAGEMENT.md** - Global uniqueness system
2. **DESUGARING_PATTERNS.md** - How variables connect across phases

### Path 7: Paper Rules to GHC Implementation (1 hour)
1. **putting-2007-rules.tex** - Formal bidirectional rules
2. **RULES_TO_CODE_MAPPING.md** - How rules map to code
   - Focus on Section 6.5: pr(σ) witness vs GHC wrapper equivalence
3. **HIGHERRANK_POLY.md** - Higher-rank polymorphism details
4. **HSWRAPPER_ARCHITECTURE.md** - Evidence wrappers

### Path 8: Deep Skolemisation Deep Dive (45 min)
1. **SKOLEMISE_TRACE.md** - Step-by-step trace with nested forall type
2. **RULES_TO_CODE_MAPPING.md** - DEEP-SKOL rule (Section 6)
3. **HSWRAPPER_ARCHITECTURE.md** - WpFun and mkWpEta
4. **GHC/Tc/Utils/Unify.hs** - Read `deeplySkolemise` source

---

## 🔑 Key Concepts Reference

### Data Structures

**ExpType** (TYPE_INFERENCE.md Part 1)
```haskell
data ExpType = Check TcType
             | Infer !InferResult
```

**InferResult** (TYPE_INFERENCE.md Part 1)
```haskell
data InferResult = IR {
    ir_uniq :: Unique,
    ir_lvl :: TcLevel,
    ir_frr :: InferFRRFlag,
    ir_inst :: InferInstFlag,
    ir_ref :: IORef (Maybe TcType)
}
```

**HsWrapper** (HSWRAPPER_ARCHITECTURE.md Part 2)
```haskell
data HsWrapper
  = WpHole | WpTyApp KindOrType | WpEvApp EvTerm
  | WpCast TcCoercionR | WpTyLam TyVar | WpEvLam EvVar
  | WpLet TcEvBinds | WpFun ... | WpCompose ... | WpSubType ...
```

**CoPat** (DESUGARING_PATTERNS.md)
```haskell
data XXPatGhcTc
  = CoPat
      { co_cpt_wrap :: HsWrapper
      , co_pat_inner :: Pat GhcTc
      , co_pat_ty :: Type
      }
```

**Unique** (UNIQUENESS_MANAGEMENT.md)
```haskell
newtype Unique = MkUnique Word64
-- Combines tag (8 bits) + number (56 bits)
```

### Key Principles

1. **One mode per node**: Check OR Infer, never both
2. **Generalization at let**: Only `tcPolyInfer` creates polymorphic types
3. **Linear hole usage**: Each ExpType used exactly once
4. **Wrapper evidence**: HsWrapper records type-checker evidence
5. **GhcTc-only**: Wrappers only appear in type-checked AST
6. **Pattern-level substitution**: AABS2 term substitution via CoPat wrappers
7. **Global uniqueness**: All variables share one atomic counter across phases

---

## 📍 File Location Index

| Concept | File | Documentation |
|---------|------|---------------|
| ExpType | `GHC/Tc/Utils/TcType.hs` | TYPE_INFERENCE.md |
| newInferExpType | `GHC/Tc/Utils/TcMType.hs` | TYPE_INFERENCE.md |
| tcExpr | `GHC/Tc/Gen/Expr.hs` | TYPE_INFERENCE.md |
| tcApp | `GHC/Tc/Gen/App.hs` | TYPE_INFERENCE.md |
| HsWrapper | `GHC/Tc/Types/Evidence.hs` | HSWRAPPER_ARCHITECTURE.md |
| mkHsWrap | `GHC/Hs/Utils.hs` | HSWRAPPER_ARCHITECTURE.md |
| dsHsWrapper | `GHC/HsToCore/Binds.hs` | HSWRAPPER_ARCHITECTURE.md |
| CoPat | `GHC/Hs/Pat.hs` | DESUGARING_PATTERNS.md |
| matchCoercion | `GHC/HsToCore/Match.hs` | DESUGARING_PATTERNS.md |
| genSym | `GHC/Types/Unique/Supply.hs` | UNIQUENESS_MANAGEMENT.md |
| MonadUnique | `GHC/Types/Unique/Supply.hs` | UNIQUENESS_MANAGEMENT.md |
| newUnique | `GHC/Tc/Utils/Monad.hs` | UNIQUENESS_MANAGEMENT.md |

---



## ✅ What You'll Understand

- ✓ How GHC implements bidirectional type inference
- ✓ ExpType and the Check/Infer modes
- ✓ How type information is stored during inference
- ✓ Where generalization occurs (only at let!)
- ✓ HsWrapper evidence recording
- ✓ Translation from Haskell to Core
- ✓ Key source files and their roles
- ✓ Pattern desugaring and the AABS2 rule implementation
- ✓ Global uniqueness management across compiler phases

---

## 🏁 Next Steps

1. **Start with TYPE_INFERENCE.md** for the complete picture
2. **Use COMPILER_DIRECTORY_GUIDE.md** to find code
3. **Reference HSWRAPPER_ARCHITECTURE.md** for wrapper details
4. **Check FLOW_DIAGRAMS.md** for visual reinforcement
5. **Read DESUGARING_PATTERNS.md** for pattern desugaring details
6. **Study UNIQUENESS_MANAGEMENT.md** to understand variable identity

**Happy learning! 🚀**
