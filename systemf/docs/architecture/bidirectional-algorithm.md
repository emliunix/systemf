# Bidirectional Type Inference with ADTs

## Based on "Practical Type Inference for Arbitrary-Rank Types" (Jones et al., 2007)

---

## Syntax

### Types

$$
\begin{array}{lrcl}
\text{Type variables} & \alpha, \beta & \in & \text{TyVar} \\
\text{Meta variables} & \tau, \sigma & \in & \text{TMeta} \\
\text{Type constructors} & T & \in & \text{TyCon} \\
\text{Monotypes} & \rho & ::= & \alpha \mid \tau \mid T\ \overline{\rho} \mid \rho_1 \rightarrow \rho_2 \\
\text{Polytypes} & \sigma & ::= & \rho \mid \forall \alpha.\ \sigma \\
\text{Contexts} & \Gamma & ::= & \emptyset \mid \Gamma, x:\sigma \mid \Gamma, \alpha \\
\end{array}
$$

### Terms

$$
\begin{array}{lrcl}
\text{Variables} & x, y, z & \in & \text{Var} \\
\text{Constructors} & C & \in & \text{Con} \\
\text{Terms} & e & ::= & x \mid C \mid \lambda x.\ e \mid e_1\ e_2 \mid \text{let}\ x = e_1\ \text{in}\ e_2 \\
& & \mid & \text{case}\ e\ \text{of}\ \overline{p_i \rightarrow e_i} \\
\text{Patterns} & p & ::= & C\ \overline{x} \\
\text{Values} & v & ::= & C\ \overline{v} \mid \lambda x.\ e \\
\end{array}
$$

### ADT Declarations

$$
\mathsf{data}\ T\ \overline{\alpha} = \overline{C_i\ \overline{\tau_{ij}}}^{\,i}
$$

---

## The Algorithm

### Judgment Forms

$$
\begin{array}{ll}
\Gamma \vdash_\Downarrow e : \sigma & \text{Check: } e \text{ has type } \sigma \\
\Gamma \vdash_\Uparrow e : \rho & \text{Synthesize: } e \text{ has type } \rho \\
\Gamma \vdash_{\Downarrow\text{-inst}} e : \rho & \text{Check with instantiation} \\
\Gamma \vdash_{\Uparrow\text{-poly}} e : \sigma & \text{Synthesize polymorphic type} \\
\end{array}
$$

### Type Variables and Substitution

$$
\begin{array}{ll}
\text{fv}(\rho) & \text{Free type variables in } \rho \\
\text{ftv}(\Gamma) & \text{Free type variables in context} \\
\rho[\tau/\alpha] & \text{Substitute } \tau \text{ for } \alpha \text{ in } \rho \\
\end{array}
$$

### Instantiation and Generalization

**Instantiation:** Replace bound variables with fresh meta-variables.

$$
\text{inst}(\forall \overline{\alpha}.\ \rho) = \rho[\overline{\tau}/\overline{\alpha}] \quad \text{where } \overline{\tau} \text{ fresh}
$$

**Generalization:** Abstract over variables not in context.

$$
\text{gen}(\Gamma, \rho) = \forall \overline{\alpha}.\ \rho \quad \text{where } \overline{\alpha} = \text{fv}(\rho) \setminus \text{ftv}(\Gamma)
$$

### Subsumption

$$
\frac{\sigma_1 \sqsubseteq \sigma_2}{\text{Subsumption}}
$$

$$
\frac{}{\rho \sqsubseteq \rho}
$$

$$
\frac{\rho[\overline{\tau}/\overline{\alpha}] \sqsubseteq \sigma}{\forall \overline{\alpha}.\ \rho \sqsubseteq \sigma}
$$

---

## Core Typing Rules

### Variable

$$
\frac{x : \sigma \in \Gamma \quad \rho = \text{inst}(\sigma)}{\Gamma \vdash_\Uparrow x : \rho}\text{(VAR)}
$$

### Constructor

$$
\frac{C : \forall \overline{\alpha}.\ \overline{\tau} \rightarrow T\ \overline{\alpha} \in \Gamma \quad \rho = \text{inst}(\forall \overline{\alpha}.\ \overline{\tau} \rightarrow T\ \overline{\alpha})}{\Gamma \vdash_\Uparrow C : \rho}\text{(CON)}
$$

### Lambda Abstraction

**Checking against arrow type:**

$$
\frac{\Gamma, x:\rho_1 \vdash_\Downarrow e : \rho_2}{\Gamma \vdash_\Downarrow \lambda x.\ e : \rho_1 \rightarrow \rho_2}\text{(ABS)}
$$

**Checking against polytype (instantiate first):**

$$
\frac{\rho = \text{inst}(\sigma) \quad \Gamma \vdash_\Downarrow \lambda x.\ e : \rho}{\Gamma \vdash_\Downarrow \lambda x.\ e : \sigma}\text{(ABS-V)}
$$

**Synthesizing type (unknown arg type):**

$$
\frac{\Gamma, x:\tau \vdash_\Uparrow e : \rho \quad \tau \text{ fresh}}{\Gamma \vdash_\Uparrow \lambda x.\ e : \tau \rightarrow \rho}\text{(ABS-SYN)}
$$

### Application

$$
\frac{\Gamma \vdash_\Uparrow e_1 : \rho_1 \rightarrow \rho_2 \quad \Gamma \vdash_\Downarrow e_2 : \rho_1}{\Gamma \vdash_\Uparrow e_1\ e_2 : \rho_2}\text{(APP)}
$$

**Application with polymorphic function (instantiate):**

$$
\frac{\Gamma \vdash_\Uparrow e_1 : \sigma \quad \rho_1 \rightarrow \rho_2 = \text{inst}(\sigma) \quad \Gamma \vdash_\Downarrow e_2 : \rho_1}{\Gamma \vdash_\Uparrow e_1\ e_2 : \rho_2}\text{(APP-V)}
$$

### Let Binding

**Synthesizing:**

$$
\frac{\Gamma \vdash_{\Uparrow\text{-poly}} e_1 : \sigma_1 \quad \Gamma, x:\sigma_1 \vdash_\Uparrow e_2 : \rho}{\Gamma \vdash_\Uparrow \text{let}\ x = e_1\ \text{in}\ e_2 : \rho}\text{(LET)}
$$

**Checking (polymorphic generalization):**

$$
\frac{\Gamma \vdash_{\Uparrow\text{-poly}} e_1 : \sigma_1 \quad \Gamma, x:\sigma_1 \vdash_\Downarrow e_2 : \sigma}{\Gamma \vdash_\Downarrow \text{let}\ x = e_1\ \text{in}\ e_2 : \sigma}\text{(LET-V)}
$$

**Polymorphic synthesis auxiliary:**

$$
\frac{\Gamma \vdash_\Uparrow e : \rho \quad \sigma = \text{gen}(\Gamma, \rho)}{\Gamma \vdash_{\Uparrow\text{-poly}} e : \sigma}\text{(GEN)}
$$

### Subsumption (Checking)

$$
\frac{\Gamma \vdash_\Uparrow e : \rho_1 \quad \rho_1 \sqsubseteq \rho_2}{\Gamma \vdash_\Downarrow e : \rho_2}\text{(SUB)}
$$

---

## ADT and Case Matching Rules

### ADT Declaration Processing

Before elaboration, process ADT declarations:

$$
\frac{\mathsf{data}\ T\ \overline{\alpha} = \overline{C_i\ \overline{\tau_{ij}}}^{\,i} \quad \sigma_i = \forall \overline{\alpha}.\ \overline{\tau_{ij}} \rightarrow T\ \overline{\alpha}}{\Gamma + (C_i : \sigma_i)_{i}}
$$

### Constructor Application

**Fully applied constructor:**

$$
\frac{C : \forall \overline{\alpha}.\ \overline{\tau} \rightarrow T\ \overline{\alpha} \in \Gamma \quad \overline{\tau'} = \text{inst}(\forall \overline{\alpha}.\ \overline{\tau}) \quad \forall i.\ \Gamma \vdash_\Downarrow e_i : \tau'_i}{\Gamma \vdash_\Uparrow C\ \overline{e} : T\ \overline{\tau''}}\text{(CON-APP)}
$$

Where $\tau''$ are the fresh instantiations for $\overline{\alpha}$.

**Partial application (curried):**

$$
\frac{C : \sigma \in \Gamma \quad \rho = \text{inst}(\sigma)}{\Gamma \vdash_\Uparrow C : \rho}\text{(CON-PARTIAL)}
$$

### Pattern Matching

**Synthesizing case expression:**

$$
\frac{\Gamma \vdash_\Uparrow e : \rho \quad \forall i.\ \Gamma \vdash_\text{branch} (p_i \rightarrow e_i) : \rho \Rightarrow \rho_{result}}{\Gamma \vdash_\Uparrow \text{case}\ e\ \text{of}\ \overline{p_i \rightarrow e_i} : \rho_{result}}\text{(CASE-SYN)}
$$

**Checking case expression:**

$$
\frac{\Gamma \vdash_\Uparrow e : \rho \quad \forall i.\ \Gamma \vdash_\text{branch} (p_i \rightarrow e_i) : \rho \Rightarrow \sigma}{\Gamma \vdash_\Downarrow \text{case}\ e\ \text{of}\ \overline{p_i \rightarrow e_i} : \sigma}\text{(CASE-CHECK)}
$$

### Branch Checking

**Constructor pattern:**

$$
\frac{C : \forall \overline{\alpha}.\ \overline{\tau} \rightarrow T\ \overline{\alpha} \in \Gamma \quad \text{inst}(\forall \overline{\alpha}.\ \overline{\tau} \rightarrow T\ \overline{\alpha}) = \overline{\tau'} \rightarrow T\ \overline{\tau''} \quad T\ \overline{\tau''} \sqsubseteq \rho \quad \Gamma, \overline{x_i : \tau'_i} \vdash_\Downarrow e : \rho_{result}}{\Gamma \vdash_\text{branch} (C\ \overline{x} \rightarrow e) : \rho \Rightarrow \rho_{result}}\text{(BRANCH)}
$$

**Wild pattern:**

$$
\frac{\Gamma \vdash_\Downarrow e : \rho_{result}}{\Gamma \vdash_\text{branch} (\_ \rightarrow e) : \rho \Rightarrow \rho_{result}}\text{(BRANCH-WILD)}
$$

---

## Extended with Iso-Recursive Types (μ)

### Types with μ

$$
\rho ::= \ldots \mid \mu \alpha.\ \rho
$$

### Fold/Unfold Rules

**Fold (introduction):**

$$
\frac{\Gamma \vdash_\Downarrow e : \rho[\mu \alpha.\ \rho / \alpha]}{\Gamma \vdash_\Downarrow \mathsf{fold}\ e : \mu \alpha.\ \rho}\text{(FOLD)}
$$

$$
\frac{\Gamma \vdash_\Uparrow e : \rho[\mu \alpha.\ \rho / \alpha]}{\Gamma \vdash_\Uparrow \mathsf{fold}\ e : \mu \alpha.\ \rho}\text{(FOLD-SYN)}
$$

**Unfold (elimination):**

$$
\frac{\Gamma \vdash_\Downarrow e : \mu \alpha.\ \rho}{\Gamma \vdash_\Downarrow \mathsf{unfold}\ e : \rho[\mu \alpha.\ \rho / \alpha]}\text{(UNFOLD)}
$$

$$
\frac{\Gamma \vdash_\Uparrow e : \mu \alpha.\ \rho}{\Gamma \vdash_\Uparrow \mathsf{unfold}\ e : \rho[\mu \alpha.\ \rho / \alpha]}\text{(UNFOLD-SYN)}
$$

### Constructor Application with Fold

$$
\frac{\Gamma \vdash_\Downarrow C\ \overline{e} : \rho[\mu \alpha.\ \rho / \alpha] \quad T\ \overline{\tau} = \mu \alpha.\ \rho}{\Gamma \vdash_\Downarrow C\ \overline{e} : T\ \overline{\tau}}\text{(CON-FOLD)}
$$

This is sugar for: $\mathsf{fold}(C\ \overline{e})$.

### Case Analysis with Unfold

$$
\frac{\Gamma \vdash_\Uparrow e : \mu \alpha.\ \rho \quad \Gamma \vdash_\text{case-unfold} (\text{unfold}\ e)\ \text{of}\ \overline{p_i \rightarrow e_i} : \rho_{result}}{\Gamma \vdash_\Uparrow \text{case}\ e\ \text{of}\ \overline{p_i \rightarrow e_i} : \rho_{result}}\text{(CASE-MU)}
$$

---

## Algorithm Summary

```
Input:  Scoped AST (with de Bruijn indices)
Output: Typed Core AST + resolved types

Phase 1: ADT Processing
  - Collect all data declarations
  - Build SCC graph for mutual recursion
  - Generate constructor types
  - Register in elaboration context

Phase 2: Type Elaboration (Bidirectional)
  For each term:
    - If expected type known: check mode
    - Otherwise: synthesize mode
    - Use unification to solve constraints
    - Apply substitution after each binding

Phase 3: Generalization (at let-bindings)
  - Collect free type variables
  - Abstract over those not in context
  - Produce polymorphic type

Phase 4: Fold/Unfold Insertion (for iso-recursive)
  - At constructor applications: insert fold
  - At pattern matches: insert unfold on scrutinee
  - Ensure μ-types are properly wrapped
```

---

## References

- Peyton Jones, S., Vytiniotis, D., Weirich, S., & Shields, M. (2007). Practical type inference for arbitrary-rank types. *Journal of Functional Programming*, 17(1), 1-82.
- Pierce, B. C. (2002). *Types and Programming Languages*. MIT Press.

---

**Last Updated**: 2026-03-07  
**Status**: Algorithm specification complete
