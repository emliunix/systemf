# Putting 2007 - Paper Text Index (Line Numbers)

**Paper**: "Practical Type Inference for Arbitrary-Rank Types"  
**Authors**: Peyton Jones, Vytiniotis, Weirich, Shields (2007)  
**Source**: `putting-2007.txt`

---

## How to use this index

```bash
# Jump to a specific section
sed -n '2723,2759p' putting-2007.txt    # Read Section 5
sed -n '3108,3207p' putting-2007.txt    # Read Section 5.6 (Subsumption)
grep -n "instantiate" putting-2007.txt  # Search within sections
```

---

## Main Sections

| Section | Line | Description |
|---------|------|-------------|
| Abstract | 20 | Paper overview and contributions |
| **1 Introduction** | 71 | Motivating examples, contribution claims |
| **2 Motivation** | 159 | Real-world use cases (ST monad, generic programming) |
| **3 The key ideas** | 271 | Core concepts: rank-N types, bidirectional inference |
| 3.1 Higher-ranked types | 280 | Definitions: rank-0, rank-1, rank-2, rank-N |
| 3.2 Exploiting type annotations | 306 | How annotations guide inference |
| 3.3 Subsumption | 349 | The σ ≤ ρ relation |
| 3.4 Predicativity | 387 | Impredicative vs predicative polymorphism |
| 3.5 Higher-kinded types | 421 | Brief mention (not main focus) |
| **4 Type systems for higher-rank types** | 440 | Formal development of type systems |
| 4.1 Notation | 531 | Type syntax and conventions |
| 4.2 Non-syntax-directed Damas-Milner | 605 | Figure 3: original Damas-Milner rules |
| 4.3 Syntax-directed Damas-Milner | 667 | Figure 4: algorithmic Damas-Milner |
| 4.4 Type annotations and subsumption | 864 | Handling annotations |
| 4.5 Higher-rank types | 1099 | Figure 5: Odersky-Läufer system |
| 4.6 Syntax-directed higher-rank | 1146 | Figure 6: algorithmic higher-rank |
| 4.7 Bidirectional type inference | 1497 | **Figure 8: main bidirectional rules** |
| 4.8 Type-directed translation | 1846 | Elaboration to System F |
| 4.9 Metatheory | 2250 | Soundness and completeness theorems |
| **5 Damas-Milner type inference** | 2723 | Implementation for rank-1 |
| 5.1 Terms and types | 2735 | Data structures |
| 5.2 The type-checker monad | 2853 | Tc monad with IORef for unification |
| 5.3 Simple inference | 2923 | Basic infer/check functions |
| 5.4 Propagating types inward | 2971 | Bidirectional checking |
| 5.5 Instantiation and generalisation | 3049 | GEN1/GEN2 rules |
| **5.6 Subsumption** | **3108** | **subsCheck implementation** |
| 5.7 Meta type variables | 3206 | MetaTv representation with IORef |
| **6 Inference for higher rank** | 3254 | Extending to arbitrary rank |
| 6.1 Changes to basic structure | 3271 | Expected type data structure |
| 6.2 Basic rules | 3359 | INT, VAR rules |
| 6.3 Abstractions | 3417 | ABS1, ABS2, AABS1, AABS2 |
| 6.4 Generalisation | 3448 | quantify function |
| 6.5 Subsumption | 3524 | subsCheck for higher-rank |
| **7 Handling a larger language** | 3646 | Extensions (if/then/else, etc.) |
| **8 Type-directed translation** | 4025 | Full elaboration to System F |
| **9 Related work** | 4142 | Comparisons to MLF, other systems |
| **10 Summary** | 4360 | Conclusions |
| **A Appendix** | 4486 | Complete implementation |
| A.1 Type inference | 4489 | TcTerm implementation |
| A.2 The monad | 4623 | TcMonad operations |
| A.3 Basic types | 4901 | Type definitions |

---

## Key Figures

| Figure | Line | Contents |
|--------|------|----------|
| Figure 1 | 520 | Road map of type systems |
| Figure 2 | 580 | Source language syntax |
| Figure 3 | 655 | Damas-Milner (non-syntax-directed) |
| Figure 4 | 789 | Syntax-directed Damas-Milner |
| Figure 5 | 1088 | Odersky-Läufer (higher-rank) |
| Figure 6 | 1265 | Syntax-directed higher-rank |
| Figure 7 | 1434 | Deep skolemization subsumption |
| **Figure 8** | **1683** | **Bidirectional rules (main)** |

---

## Critical Implementation Functions

| Function | Section | Line | Purpose |
|----------|---------|------|---------|
| `instantiate` | Appendix A.1 | 4745 | Replace ∀ with fresh metas |
| `skolemise` | Appendix A.1 | 4753 | Replace ∀ with skolem constants |
| `quantify` | Appendix A.1 | 4777 | Generalize free metas to ∀ |
| `subsCheck` | 5.6 | 3127 | Subsumption (σ₁ ≤ σ₂) |
| `unify` | 5.6 | ~3142 | Robinson unification |
| `inferSigma` | 5.5 | ~3051 | GEN1: infer poly type |
| `checkSigma` | 5.5 | ~3055 | GEN2: check against poly type |
| `zonkType` | 5.7 | ~3216 | Follow meta chains |

---

## Quick Topic Reference

| Topic | Where to find |
|-------|---------------|
| MetaTv chain/IORef structure | Lines 64-69, 3216-3225 |
| GEN1 rule (generalization) | Lines 224-234, 520-527, 3051-3054 |
| GEN2 rule (checking poly) | Lines 229-244, 530-542, 3055-3067 |
| INST rule (instantiation) | Lines 193-199, 3136-3139, 4745-4752 |
| SPEC rule (subsumption) | Lines 569-577, 3136-3139 |
| Deep skolemization | Lines 551-563, 3524-3575 |
| ftv(ρ) - ftv(Γ) explained | Lines 224-234, 520-542 |
| Bidirectional modes (⊢⇑, ⊢⇓) | Lines 395-414, 419-508 |
| Expected type datatype | Lines 399-399, 3271-3359 |
| Rich patterns (unified abs) | Section 7.2, Lines 3795-3900 |
| Pattern judgment rules | Section 7.2, Lines 3820-3870 |

---

## Analysis: Unified Abs Rule and Pattern Judgment (Section 7.2)

### The Unified `abs` Rule

Section 7.2 (line ~3820) unifies ABS1, ABS2, AABS1, AABS2 into a single direction-polymorphic rule:

$$\frac{\vdash^{\text{pat}}_\delta\; p : \sigma,\, \Gamma' \qquad \Gamma,\,\Gamma' \vdash_\delta\; t : \rho}{\Gamma \vdash_\delta\; \lambda p.\,t : \sigma \rightarrow \rho} \text{ abs}$$

The paper explicitly states: *"We only need one rule, because the cases that were previously treated separately in abs1, abs2, aabs1, and aabs2, are now handled by $\vdash^{\text{pat}}$."*

### The Pattern Judgment

Judgment form: $\vdash^{\text{pat}}_\delta\; p : \sigma,\, \Gamma'$

Reads as: "pattern $p$ has scrutinee type $\sigma$ and introduces bindings $\Gamma'$".
- $\sigma$ is **output** in infer ($\Uparrow$), **input** in check ($\Downarrow$)
- $\Gamma'$ is always **output**
- `tcPat` takes `Expected Sigma` (not Rho) because argument types can be polytypes

#### Variable pattern rules

$$\frac{\tau \text{ fresh}}{\vdash^{\text{pat}}_\Uparrow\; x : \tau,\, \{x:\tau\}} \text{ VAR-INF}$$

$$\frac{}{\vdash^{\text{pat}}_\Downarrow\; x : \sigma,\, \{x:\sigma\}} \text{ VAR-CHK}$$

#### Annotated pattern rules

$$\frac{}{\vdash^{\text{pat}}_\Uparrow\; (x{::}\sigma) : \sigma,\, \{x:\sigma\}} \text{ ANN-INF}$$

$$\frac{\vdash^{\text{dsk}}\; \sigma' \leq \sigma}{\vdash^{\text{pat}}_\Downarrow\; (x{::}\sigma) : \sigma',\, \{x:\sigma\}} \text{ ANN-CHK}$$

In ANN-CHK, $\sigma'$ is the expected scrutinee type pushed in from outside; $\vdash^{\text{dsk}}$ checks it subsumes the annotation. Corresponds to `instPatSigma pat_ty (Check exp_ty) = subsCheck exp_ty pat_ty`.

### Key Points

**1. $\tau \subseteq \sigma$ via empty quantifier sequence**

The type hierarchy is $\sigma ::= \forall\overline{a}.\,\rho$, $\rho ::= \tau \mid \sigma_1 \rightarrow \sigma_2$, $\tau ::= a \mid \tau_1 \rightarrow \tau_2$.
Since $\overline{a}$ can be empty, $\tau$ is a $\sigma$ with $\forall\varnothing$. This is confirmed by VAR storing $x:\sigma$
in context and using $\vdash^{\text{inst}}$ to bridge to $\rho$ at use sites. Values at the term level
are always $\rho$-typed; $\sigma$ only lives in the context and annotations.

**2. The $\Uparrow$/$\Downarrow$ split aligns with $\rho$/$\sigma$ result types**

| direction | result type in conclusion | body judgment |
|-----------|--------------------------|---------------|
| $\Uparrow$ infer | $\rho$ | $\vdash_\Uparrow t : \rho$ |
| $\Downarrow$ check | $\sigma$ (caller-provided) | $\vdash^{\text{poly}}_\Downarrow t : \sigma_r$ |

In check ($\Downarrow$), ABS2/AABS2 use $\vdash^{\text{poly}}_\Downarrow$ for the body. This is not inside the lambda
rule — GEN2 fires at the call site first, applying $pr(\sigma_r)$ to strip $\forall$s down to a
$\rho$, so the body is always checked against a $\rho$ by the time `abs` fires. The unified
rule's $\vdash_\delta\; t : \rho$ is therefore correct and complete.

**3. Pattern judgment scope**

$\vdash^{\text{pat}}$ is only responsible for the **argument side** of the arrow: synthesizing/checking
$\sigma$ and producing $\Gamma'$. The result side ($\rho$ in the body) and generalization ($\vdash^{\text{poly}}$)
are entirely outside its scope, handled above by GEN1/GEN2.

**4. ABS1/AABS1/ABS2/AABS2 as instances of `abs`**

| original rule | pattern $p$ | direction | $\vdash^{\text{pat}}$ result |
|---------------|-------------|-----------|------------------------------|
| ABS1  | $x$        | $\Uparrow$ | fresh $\tau$, $\{x:\tau\}$ |
| AABS1 | $x{::}\sigma$ | $\Uparrow$ | given $\sigma$, $\{x:\sigma\}$ |
| ABS2  | $x$        | $\Downarrow$ | pushed-in $\sigma$, $\{x:\sigma\}$ |
| AABS2 | $x{::}\sigma$ | $\Downarrow$ | $\vdash^{\text{dsk}}\;\sigma'\leq\sigma$, $\{x:\sigma\}$ |
