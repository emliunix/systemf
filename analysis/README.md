# GHC Type Inference System - Documentation

## Quick Start

This directory contains comprehensive documentation of GHC's type inference system, organized into focused documents:

### 📘 TYPE_INFERENCE.md - **Start Here!**
Complete guide to GHC's bidirectional type inference system:
- Core data structures (ExpType, InferResult)
- Type checking modes (Check vs Infer)
- Type storage during inference
- Main type-checking functions
- Key implementation files

### 📗 HSWRAPPER_ARCHITECTURE.md
Deep dive into HsWrapper - the evidence recording mechanism:
- Two-phase architecture (type checking → desugaring)
- All 10 wrapper variants explained
- Translation to Core
- Creation sites and validation

### 📙 COMPILER_DIRECTORY_GUIDE.md
Complete map of the GHC compiler codebase:
- Directory structure by compilation phase
- Type checking subsystem (GHC/Tc/)
- Key entry points

### 📕 CORE_SYSTEM_F.md
Core language and System FC:
- Translation from Haskell to Core
- Type classes and coercions
- Currying and multi-argument functions

### 📊 FLOW_DIAGRAMS.md
Visual reference with 12 detailed flow diagrams

### 📒 HIGHERRANK_POLY.md
Higher-rank polymorphism with bidirectional type inference

### 📗 DESUGARING_PATTERNS.md
Pattern desugaring and the AABS2 rule implementation:
- CoPat and pattern wrappers
- How term substitution becomes let-bindings
- matchCoercion and wrapper application
- Variable binding chains

### 📙 UNIQUENESS_MANAGEMENT.md
Global unique identifier system:
- Atomic counter and genSym
- MonadUnique typeclass
- UniqSupply tree structure
- Cross-phase variable creation

### 📗 RULES_TO_CODE_MAPPING.md
Mapping formal paper rules to GHC implementation:
- INST1/INST2 instantiation rules
- Prenex conversion (PRPOLY, PRFUN)
- Deep skolemization (DEEP-SKOL)
- **Key insight**: pr(σ) witness vs GHC wrapper equivalence
- Function subsumption (FUN)

---

## Learning Paths

### Path 1: Understanding Type Inference (45 min)
1. **TYPE_INFERENCE.md** - Complete overview
2. **FLOW_DIAGRAMS.md** - Visual reinforcement

### Path 2: Understanding Evidence/Wrappers (30 min)
1. **HSWRAPPER_ARCHITECTURE.md** - Complete architecture
2. **TYPE_INFERENCE.md** Section 4 - Type storage

### Path 3: Finding Code in the Compiler
1. **COMPILER_DIRECTORY_GUIDE.md** - Directory map
2. **TYPE_INFERENCE.md** Section 5 - Key files

### Path 4: Complete Understanding (2-3 hours)
1. **TYPE_INFERENCE.md**
2. **HSWRAPPER_ARCHITECTURE.md**
3. **CORE_SYSTEM_F.md**
4. **FLOW_DIAGRAMS.md**

### Path 5: Pattern Desugaring Deep Dive (45 min)
1. **DESUGARING_PATTERNS.md** - AABS2 rule and CoPat
2. **HSWRAPPER_ARCHITECTURE.md** - Wrapper translation to Core
3. **TYPE_INFERENCE.md** - Pattern type checking

### Path 6: Variable Identity Across Phases (30 min)
1. **UNIQUENESS_MANAGEMENT.md** - Global uniqueness system
2. **DESUGARING_PATTERNS.md** - How variables connect
3. **HSWRAPPER_ARCHITECTURE.md** - Evidence and variables

### Path 7: Paper Rules to Implementation (1 hour)
1. **putting-2007-rules.tex** - Formal bidirectional rules (Jones 2007)
2. **RULES_TO_CODE_MAPPING.md** - Rule-to-code correspondence
   - Section 6.5: pr(σ) witness vs GHC wrapper equivalence
3. **HIGHERRANK_POLY.md** - Higher-rank polymorphism
4. **HSWRAPPER_ARCHITECTURE.md** - Evidence wrappers

---

## Key Concepts

| Concept | Description | Where to Find |
|---------|-------------|---------------|
| **ExpType** | Check TcType \| Infer InferResult | TYPE_INFERENCE.md Part 1 |
| **Bidirectional** | Checking vs Inference modes | TYPE_INFERENCE.md Part 2 |
| **Generalization** | Only at let-bindings | TYPE_INFERENCE.md Part 2 |
| **HsWrapper** | Evidence recording | HSWRAPPER_ARCHITECTURE.md |
| **Meta-variables** | IORef-based inference | TYPE_INFERENCE.md Part 3 |
| **Zonking** | Replace meta-vars | TYPE_INFERENCE.md Part 3 |
| **CoPat** | Pattern coercion wrapper | DESUGARING_PATTERNS.md |
| **matchCoercion** | Desugar CoPat patterns | DESUGARING_PATTERNS.md |
| **Unique** | Global unique identifier | UNIQUENESS_MANAGEMENT.md |
| **genSym** | Atomic counter for uniques | UNIQUENESS_MANAGEMENT.md |
| **pr(σ)** | Prenex conversion witness | RULES_TO_CODE_MAPPING.md |
| **DEEP-SKOL** | Deep skolemization rule | RULES_TO_CODE_MAPPING.md |
| **INST1/INST2** | Instantiation rules | RULES_TO_CODE_MAPPING.md |

---

## Document Consolidation

Previous documentation has been consolidated:
- **BIDIRECTIONAL_TYPE_INFERENCE.md** → Merged into TYPE_INFERENCE.md
- **TYPE_CHECKING_MODES.md** → Merged into TYPE_INFERENCE.md Part 2
- **KEY_TYPE_CHECKING_FILES.md** → Merged into TYPE_INFERENCE.md Part 5
- **TYPE_STORAGE_MECHANISM.md** → Merged into TYPE_INFERENCE.md Part 3
- **HSWRAPPER_VARIANTS_ANALYSIS.md** → Merged into HSWRAPPER_ARCHITECTURE.md
- **HSWRAPPER_VALIDATION.md** → Merged into HSWRAPPER_ARCHITECTURE.md Section 6
- **TYPE_CHECKER_OUTPUT.md** → Merged into HSWRAPPER_ARCHITECTURE.md

---

## File Locations

| What | File |
|------|------|
| Expression type checking | `GHC/Tc/Gen/Expr.hs` |
| Application checking | `GHC/Tc/Gen/App.hs` |
| Pattern checking | `GHC/Tc/Gen/Pat.hs` |
| ExpType definition | `GHC/Tc/Utils/TcType.hs` |
| Hole operations | `GHC/Tc/Utils/TcMType.hs` |
| Unification | `GHC/Tc/Utils/Unify.hs` |
| Constraint solving | `GHC/Tc/Solver/Solve.hs` |
| Wrapper definition | `GHC/Tc/Types/Evidence.hs` |
| Desugaring | `GHC/HsToCore/Expr.hs` |
| Pattern coercions | `GHC/HsToCore/Match.hs` |
| Global uniqueness | `GHC/Types/Unique/Supply.hs` |
| Unique API | `GHC/Tc/Utils/Monad.hs` |

---

## Summary

This documentation suite covers:
- ✓ How GHC implements bidirectional type inference
- ✓ ExpType and the Check/Infer modes
- ✓ How type information is stored during inference
- ✓ Where generalization occurs (only at let!)
- ✓ HsWrapper evidence recording
- ✓ Translation from Haskell to Core
- ✓ Key source files and their roles
- ✓ Pattern desugaring (AABS2 rule implementation)
- ✓ Global uniqueness management across phases
- ✓ Paper rules to GHC implementation mapping

Start with **TYPE_INFERENCE.md** for the complete picture!
