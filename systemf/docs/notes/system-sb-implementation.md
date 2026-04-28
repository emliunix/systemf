# Visible Type Application: System SB Rules and Implementation

## Type Grammar

**Types:**
- $\sigma$ (type scheme) $::= \forall\{a\}.\, \upsilon$ — generalized variables (from let-generalization)
- $\upsilon$ (specified polytype) $::= \forall a.\, \upsilon \mid \varphi$ — specified variables (from user annotations)
- $\varphi$ (phi-type) $::= \tau \mid \upsigma \rightarrow \upsigma$ — no top-level $\forall$
- $\rho$ (rho-type) $::= \tau \mid \upsigma \rightarrow \rho$ — for checking (prenex form)

## Judgments

| Judgment | Meaning |
|----------|---------|
| $\Gamma \vdash_{sb} e \Rightarrow \varphi$ | Synthesize phi-type (no top-level $\forall$) |
| $\Gamma \vdash^*_{sb} e \Rightarrow \upsilon$ | Synthesize specified polytype (may have $\forall a$) |
| $\Gamma \vdash^{gen}_{sb} e \Rightarrow \sigma$ | Synthesize with generalization |
| $\Gamma \vdash_{sb} e \Leftarrow \rho$ | Check against rho-type |
| $\Gamma \vdash^*_{sb} e \Leftarrow \upsilon$ | Check against specified polytype |

---

## Synthesis Rules

### SB_Var: Variable Lookup (Lazy Instantiation)

$$
\frac{x : \forall\{a\}.\, \upsilon \in \Gamma}{\Gamma \vdash^*_{sb} x \Rightarrow \upsilon[\overline{\tau}/\overline{a}]}
$$

**Key insight:** Instantiates **generalized** vars $\{a\}$ to fresh metas, **preserves** specified vars in $\upsilon$.

**Example:**
- `id : ∀a. a → a` (all specified) → returns `∀a. a → a`
- `myId : ∀{a}. a → a` (generalized) → returns `_t1 → _t1`

---

### SB_TApp: Visible Type Application

$$
\frac{\Gamma \vdash_{sb} e \Rightarrow \forall a.\, \upsigma \quad \Gamma \vdash \tau}{\Gamma \vdash^*_{sb} e @\tau \Rightarrow \upsigma[\tau/a]}
$$

**Key insight:** Premise uses $\vdash_{sb}$ (not $\vdash^*_{sb}$)! This forces implicit instantiation if needed.

**Example:**
```
Γ ⊢_sb id ⇒ ∀a. a → a    (SB_InstS skipped because we need ∀a)
-----------------------------------
Γ ⊢*_sb id @Int ⇒ Int → Int
```

---

### SB_App: Function Application

$$
\frac{\Gamma \vdash_{sb} e_1 \Rightarrow \upsigma_1 \rightarrow \upsigma_2 \quad \Gamma \vdash^*_{sb} e_2 \Leftarrow \upsigma_1}{\Gamma \vdash^*_{sb} e_1\,e_2 \Rightarrow \upsigma_2}
$
$

**Key insight:** Function position must be phi-type (already instantiated), argument checks against domain.

---

### SB_InstS: Implicit Instantiation (Fallback)

$$
\frac{\Gamma \vdash_{sb} e \Rightarrow \forall a.\, \varphi \quad \text{no other rule matches}}{\Gamma \vdash_{sb} e \Rightarrow \varphi[\tau/a]}
$
$

**Key insight:** Only fires when we **need** a phi-type but have a forall. Creates fresh meta for $a$.

---

### SB_Phi: Bridge Judgments

$$
\frac{\Gamma \vdash_{sb} e \Rightarrow \varphi}{\Gamma \vdash^*_{sb} e \Rightarrow \varphi}
$
$

**Key insight:** Connects $\vdash_{sb}$ to $\vdash^*_{sb}$ when there's no forall.

---

### SB_Gen: Generalization at Let

$$
\frac{\overline{a} = \text{ftv}(\upsigma) \setminus \text{ftv}(\Gamma) \quad \Gamma \vdash^*_{sb} e \Rightarrow \upsigma}{\Gamma \vdash^{gen}_{sb} e \Rightarrow \forall\{\overline{a}\}.\, \upsigma}
$
$

**Key insight:** Quantifies over free vars not in environment (generalized vars).

---

## Checking Rules

### SB_DAbs: Check Lambda with Higher-Rank Type

$$
\frac{\Gamma, x : \upsigma_1 \vdash_{sb} e \Leftarrow \rho_2}{\Gamma \vdash_{sb} \lambda x.\, e \Leftarrow \upsigma_1 \rightarrow \rho_2}
$
$

**Key insight:** This is what makes System SB **higher-rank** — lambda params can have polymorphic types!

---

### SB_DeepSkol: Deep Skolemization for Checking

$$
\frac{\text{prenex}(\upsigma) = \forall \overline{a}.\, \rho \quad \overline{a} \notin \text{ftv}(\Gamma) \quad \Gamma \vdash_{sb} e \Leftarrow \rho}{\Gamma \vdash^*_{sb} e \Leftarrow \upsigma}
$
$

**Key insight:** Converts `∀a. a → ∀b. b → a` to `a → b → a` with $a,b$ as skolem constants (rigid vars).

---

### SB_Infer: Fallback to Synthesis

$$
\frac{\Gamma \vdash^*_{sb} e \Rightarrow \upsigma_1 \quad \upsigma_1 \leq_{dsk} \rho_2 \quad \text{no other rule matches}}{\Gamma \vdash_{sb} e \Leftarrow \rho_2}
$
$

**Key insight:** When checking fails, synthesize then use subsumption.

---

## Subsumption Relations

Subsumption $\sigma_1 \leq \sigma_2$ means "$\sigma_1$ is at least as polymorphic as $\sigma_2$". These are **relational specifications** that we **operationalize** to compute coercions.

### $\le_{dsk}$ (Deep Skolemization)

$$
\frac{\text{prenex}(\upsigma_2) = \forall \overline{a}.\, \rho \quad \overline{a} \notin \text{fv}(\upsigma_1) \quad \upsigma_1 \leq^*_{dsk} \rho}{\upsigma_1 \leq_{dsk} \upsigma_2}
$
$

**Purpose:** Used in **SB_Infer** to check synthesized type against expected rho-type.

**Example:**
```
∀a. a → a  ≤_dsk  Int → Int

1. prenex(Int → Int) = Int → Int  (no change)
2. Check: ∀a. a → a ≤*_dsk Int → Int
3. Instantiate: (a → a)[_t1/a] = _t1 → _t1
4. Unify: _t1 → _t1 = Int → Int  ✓
```

---

### $\le^*_{dsk}$ (To Rho-Type)

**SPEC:** Instantiate outer foralls
$$
\frac{\upsigma_1[\overline{\tau}/\overline{a}] \leq^*_{dsk} \rho_2}{\forall \overline{a}.\, \upsigma_1 \leq^*_{dsk} \rho_2}
$
$

**FUN:** Function subsumption (contravariant in arg, covariant in res)
$$
\frac{\upsigma_3 \leq_{dsk} \upsigma_1 \quad \upsigma_2 \leq^*_{dsk} \rho_4}{\upsigma_1 \rightarrow \upsigma_2 \leq^*_{dsk} \upsigma_3 \rightarrow \rho_4}
$
$

**MONO:** Unify monomorphic types
$$
\frac{}{\tau \leq^*_{dsk} \tau}
$
$

---

## Implementation in Python

### Type Representation

```python
from dataclasses import dataclass
from typing import List, Set, Optional, Union

@dataclass
class TypeVar:
    """Bound type variable from forall"""
    name: str

@dataclass
class TypeForall:
    """Specified polytype: forall a. body"""
    var: str
    body: 'Type'

@dataclass
class TypeScheme:
    """Type scheme: forall {a}. body
    
    - generalized: {a} - from let-generalization (Set)
    - specified: [a, b] - from user annotations (List, ordered)
    """
    generalized: Set[str]
    specified: List[str]
    body: 'Type'

@dataclass
class TypeArrow:
    """Function type: arg -
 res"""
    arg: 'Type'
    res: 'Type'

@dataclass
class TypeMeta:
    """Meta type variable (unification variable)"""
    id: int

Type = Union[TypeVar, TypeForall, TypeArrow, TypeMeta, 'TypeCon']
```

---

### Lazy Instantiation at Variable Lookup

```python
def lookup_var_lazy(name: str, ctx: Context) -
 Type:
    """
    SB_Var: x : forall {a}. v ∈ Γ
            --------------------
            Γ ⊢*_sb x =
 v[τ/a]
    
    Instantiates generalized vars immediately.
    Preserves specified vars for potential @ application.
    """
    scheme = ctx.lookup(name)  # TypeScheme
    
    # Step 1: Instantiate generalized vars (always)
    subst = {}
    for gen_var in scheme.generalized:
        subst[gen_var] = TypeMeta(fresh_meta())
    
    body = substitute(scheme.body, subst)
    
    # Step 2: Rebuild specified forall chain (preserved!)
    result = body
    for spec_var in reversed(scheme.specified):
        result = TypeForall(spec_var, result)
    
    return result
```

**Example trace:**
```python
# id : forall a. a -
 a  (specified only)
lookup_var_lazy('id', ctx)
# =
 TypeForall('a', TypeArrow(TypeVar('a'), TypeVar('a')))
# = forall a. a -
 a  ✓ preserved!

# myId = id  (inferred, let-generalized)
# myId : forall {a}. a -
 a  (generalized only)
lookup_var_lazy('myId', ctx)
# = TypeArrow(TypeMeta(1), TypeMeta(1))
# = _t1 -
 _t1  (instantiated!)
```

---

### Type Application

```python
def check_type_app(func: Term, type_arg: Type, ctx: Context) -
 Type:
    """
    SB_TApp: Γ ⊢_sb e =
 forall a. σ    Γ ⊢ τ
            ---------------------------
            Γ ⊢*_sb e @τ =
 σ[τ/a]
    
    The function type must have forall at head.
    """
    # Premise uses ⊢_sb (forces instantiation if needed)
    func_type = synth_phi_type(func, ctx)
    
    match func_type:
        case TypeForall(var, body):
            # Substitute explicit type argument
            return substitute(body, {var: type_arg})
        case _:
            raise TypeError(
                f"Cannot apply type to monomorphic type: {func_type}"
            )
```

---

### Phi-Type Synthesis (with Implicit Instantiation)

```python
def synth_phi_type(term: Term, ctx: Context) -
 Type:
    """
    Γ ⊢_sb e =
 φ  (synthesize without top-level forall)
    
    SB_InstS: When we have forall but need phi-type,
              instantiate with fresh meta.
    """
    # Try specific rules first...
    
    # Fallback: get specified polytype, then instantiate if needed
    upsilon = synth_specified_polytype(term, ctx)
    
    match upsilon:
        case TypeForall(var, body):
            # SB_InstS: Instantiate to make progress
            fresh = TypeMeta(fresh_meta())
            return substitute(body, {var: fresh})
        case _:
            # Already a phi-type
            return upsilon
```

---

### Specified Polytype Synthesis

```python
def synth_specified_polytype(term: Term, ctx: Context) -
 Type:
    """
    Γ ⊢*_sb e =
 υ  (may return forall a. ...)
    """
    match term:
        case Var(name):
            # SB_Var: lookup with lazy instantiation
            return lookup_var_lazy(name, ctx)
        
        case TypeApp(func, type_arg):
            # SB_TApp: explicit type instantiation
            return check_type_app(func, type_arg, ctx)
        
        case App(func, arg):
            # SB_App: function application
            func_type = synth_phi_type(func, ctx)
            match func_type:
                case TypeArrow(arg_type, res_type):
                    check_specified_polytype(arg, arg_type, ctx)
                    return res_type
                case _:
                    raise TypeError("Not a function")
        
        case _:
            # SB_Phi: bridge from phi-type
            return synth_phi_type(term, ctx)
```

---

### Checking with Deep Skolemization

```python
def check_specified_polytype(term: Term, expected: Type, ctx: Context) -
 None:
    """
    SB_DeepSkol: prenex(σ) = forall a. ρ
                  a ∉ ftv(Γ)
                  Γ ⊢_sb e <
 ρ
                  ------------------
                  Γ ⊢*_sb e <
 σ
    """
    # Prenex conversion: hoist all quantifiers
    skolems, rho = prenex(expected)
    
    # Extend context with skolem constants (rigid, not unifiable)
    new_ctx = ctx
    for skolem in skolems:
        new_ctx = new_ctx.extend_type_skolem(skolem)
    
    # Check against rho-type (no top-level forall)
    check_rho_type(term, rho, new_ctx)


def prenex(upsilon: Type) -
 (List[str], Type):
    """
    PR_Poly: prenex(forall a. ρ1) = forall ab. ρ2
             where prenex(ρ1) = forall b. ρ2
    
    PR_Fun:  prenex(σ1 -
 σ2) = forall a. (σ1 -
 ρ2)
             where prenex(σ2) = forall a. ρ2, a ∉ ftv(σ1)
    
    Returns: (skolem_vars, rho_body)
    """
    match upsilon:
        case TypeForall(var, body):
            rest_skolems, rest_body = prenex(body)
            return ([var] + rest_skolems, rest_body)
        
        case TypeArrow(arg, res):
            res_skolems, res_body = prenex(res)
            # Avoid capture
            safe_skolems = [s for s in res_skolems 
                          if s not in ftv(arg)]
            return (safe_skolems, 
                   TypeArrow(arg, res_body))
        
        case _:
            return ([], upsilon)
```

---

### Subsumption as Operation

```python
def subs_check_rho(sigma1: Type, rho2: Type) -
 Coercion:
    """
    Check sigma1 ≤*_dsk rho2.
    Returns coercion function: σ1 -
 σ2 in System F.
    
    SPEC: Instantiate forall
    FUN:  Function subsumption  
    MONO: Unify
    """
    match sigma1:
        case TypeForall(var, body):
            # SPEC: Instantiate with fresh meta
            fresh_meta = TypeMeta(fresh_meta())
            instantiated = substitute(body, var, fresh_meta)
            return subs_check_rho(instantiated, rho2)
        
        case TypeArrow(arg1, res1):
            # FUN: Function subsumption
            if not isinstance(rho2, TypeArrow):
                raise TypeError("Expected function type")
            arg2, res2 = rho2.arg, rho2.res
            
            # Contravariant in argument: σ3 ≤ σ1
            c1 = subs_check(arg2, arg1)
            # Covariant in result: σ2 ≤* ρ4
            c2 = subs_check_rho(res1, res2)
            
            # λf. λx. c2 (f (c1 x))
            return lambda f: lambda x: c2(f(c1(x)))
        
        case _:
            # MONO: Unify
            unify(sigma1, rho2)
            return lambda x: x  # identity coercion
```

---

## Complete Example

**Source:** `let id :: forall a. a -
 a = \x -
 x in id @Int 42`

**Step 1: Check declaration**
```
id : forall a. a -
 a = \x -
 x

Extend ctx with 'a' (scoped type variable)
Check body: (x : a) ⊢ x ⇐ a  ✓
```

**Step 2: Lookup `id`**
```python
id_type = lookup_var_lazy('id', ctx)
# Returns: forall a. a -
 a  (preserved!)
```

**Step 3: Type application `id @Int`**
```python
# SB_TApp premise: synthesize phi-type
func_type = synth_phi_type(id, ctx)
# id is forall a. a -
 a, so SB_InstS fires:
# Returns: _t1 -
 _t1  (instantiated)

# Wait! That's wrong for SB_TApp...
# Actually SB_TApp premise is Γ ⊢_sb e ⇒ ∀a. σ
# So we need to NOT instantiate the head forall!

# Correction: Special case for TypeApp
if isinstance(func, Var):
    func_type = lookup_var_lazy(func.name, ctx)
    # Keep as: forall a. a -
 a
else:
    func_type = synth_phi_type(func, ctx)

# Now apply: (a -
 a)[Int/a] = Int -
 Int
result = substitute(body, 'a', TypeCon('Int'))
```

**Step 4: Application `(id @Int) 42`**
```
Func: Int -
 Int
Arg: 42 : Int
Result: Int  ✓
```

---

## Key Insights

1. **Two-phase instantiation:**
   - **Generalized** vars `∀{a}`: Eager (at lookup)
   - **Specified** vars `∀a`: Lazy (at application)

2. **Judgment stratification:**
   - `⊢_sb`: Must return phi-type (forces instantiation)
   - `⊢*_sb`: Can return specified polytype (preserves forall)
   - Mutual recursion via SB_Phi and SB_InstS

3. **Subsumption operationalization:**
   - Relational: $\sigma_1 \le \sigma_2$ (specification)
   - Operational: `subs_check` computes coercion
   - Used in SB_Infer to bridge synthesized and expected types

4. **Deep skolemization:**
   - Required for higher-rank polymorphism
   - Converts `∀a. a → ∀b. b → a` to `a → b → a`
   - Skolems are rigid (not unifiable)
