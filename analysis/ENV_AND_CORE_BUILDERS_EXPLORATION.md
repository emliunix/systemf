# Evaluator Environment, Core Term Builders, and Pretty Printer Exploration

**Status:** Validated
**Last Updated:** 2026-04-25
**Central Question:** What are the inefficiencies in eval.py's environment, what common core term builders are missing, and how can we reduce duplication between the typechecker and REPL pretty printer?
**Topics:** eval, env, core-builder, pretty-printer, caching, tuple

## Planning

**Scopes:**
- `eval.py` env representation and performance characteristics
- Missing helpers for constructing common core terms (tuples, etc.)
- Pretty printer duplication between `typecheck_expr.py`/`core_pp.py` and `repl.py`
- Caching opportunities in `REPLSession`

**Excluded:**
- Changes to the CEK machine algorithm itself
- Changes to type inference or unification
- Surface syntax changes

**Entry Points:**
- `src/systemf/elab3/eval.py:1` — CEK evaluator
- `src/systemf/elab3/types/val.py:1` — Value and Env types
- `src/systemf/elab3/types/core.py:153` — CoreBuilder class
- `src/systemf/elab3/repl.py:99` — pp_val method
- `src/systemf/elab3/types/core_pp.py:1` — Core pretty printer
- `src/systemf/elab3/typecheck_expr.py:49` — TypeChecker class
- `src/systemf/elab3/builtins.py:17` — BUILTIN_PAIR definitions

**Assumptions:**
- [x] Env is `dict[int, Val]` keyed by `Name.unique`
- [x] `CoreBuilder` only handles primitive constructs
- [x] `pp_val` and `core_pp.py` independently resolve datacon info
- [x] REPL names have fixed uniques (from `NameCache`)

## Summary

Three related issues were identified:

1. **eval.py env is inefficient**: `Env = dict[int, Val]` uses plain Python dicts. Every lambda application creates a new dict via `cenv | {param.name.unique: v}` (line 230). Every let binding creates `env | {binder.name.unique: v}` (line 240). For deep call stacks, this is O(n) per frame in stack depth. Additionally, `eval_mod` for `Rec` bindings (lines 132-138) re-evaluates the entire letrec for each binder instead of constructing a tuple once and extracting fields.

2. **Missing core term builders**: `CoreBuilder` (`types/core.py:153`) only has primitive constructors (`lit`, `var`, `lam`, `app`, `tylam`, `tyapp`, `let`, `letrec`, `case_expr`). There is no helper to build a tuple core term, which requires knowing the `Pair` tycon and `MkPair` datacon info. This info is only available at typecheck time or via `lookup_gbl`. Both `typecheck_expr.py` and `repl.py` need to manually construct tuple-related terms/values.

3. **Pretty printer duplication**: Two separate code paths resolve data constructor info:
   - `repl.py:121` `get_data_con` searches `self.tythings` and calls `self.ctx.load()`
   - `core_pp.py:164` `_pp_alt` just prints `con.surface` without field names
   - `repl.py:99` `pp_val` does full type substitution to get field types for recursive printing
   
   The typechecker (`typecheck_expr.py`) already has `lookup_datacon` and `lookup_tycon` methods that could be reused, but the REPL doesn't have access to a `TcCtx`.

## Claims

### Claim 1: eval.py env dict copying is O(n) per frame
**Statement:** Every function application and let binding creates a new dict, causing linear copying in call stack depth.
**Source:** `src/systemf/elab3/eval.py:230`
**Evidence:**
```python
case VClosure(env=cenv, param=param, body=body):
    return (body, cenv | {param.name.unique: v}, k2)
```
and line 240:
```python
case LetBind(binder=binder, body=body, env=env, k=k2):
    return (body, env | {binder.name.unique: v}, k2)
```
The `|` operator on dicts creates a new dict and copies all entries.
**Status:** Validated
**Confidence:** High
**Notes:** For a recursive function with depth 1000, each frame copies the growing env. A persistent data structure (e.g., HAMT) or linked scope chain would be O(1).

### Claim 2: Rec binding evaluation re-evaluates for each binder
**Statement:** `eval_mod` for `Rec` bindings evaluates `CoreLet(binding, CoreVar(bndr))` for each binder, causing re-evaluation of the entire letrec group.
**Source:** `src/systemf/elab3/eval.py:132-138`
**Evidence:**
```python
case Rec(rec_bindings):
    # FIX: we should construct a tuple, then extracts each field
    # current approach causes re-evaluation for each binder
    for bndr, _ in rec_bindings:
        val = self._eval_expr(CoreLet(binding, CoreVar(bndr)), init_env)
```
A 3-binding letrec evaluates the full letrec 3 times.
**Status:** Validated
**Confidence:** High
**Notes:** The fix comment suggests constructing a tuple and extracting fields, which would evaluate once.

### Claim 3: CoreBuilder lacks tuple constructor
**Statement:** `CoreBuilder` has no method to construct tuple terms, requiring manual lookup of `Pair`/`MkPair` info.
**Source:** `src/systemf/elab3/types/core.py:153-182`
**Evidence:**
```python
class CoreBuilder:
    def lit(self, value: Lit) -> CoreTm: ...
    def var(self, id: Id) -> CoreTm: ...
    def lam(self, param: Id, body: CoreTm) -> CoreTm: ...
    def app(self, fun: CoreTm, arg: CoreTm) -> CoreTm: ...
    # ... no tuple method
```
**Status:** Validated
**Confidence:** High
**Notes:** Tuples exist in builtins (`BUILTIN_PAIR`, `BUILTIN_PAIR_MKPAIR`) but building a tuple core term requires manually applying the `MkPair` datacon.

### Claim 4: Pretty printer resolves datacon info independently
**Statement:** `repl.py` and `core_pp.py` each have their own logic for resolving data constructor metadata.
**Source:** `src/systemf/elab3/repl.py:121` and `src/systemf/elab3/types/core_pp.py:164`
**Evidence:**
`repl.py:121`:
```python
def get_data_con(self, con: Name, tag: int) -> tuple[ATyCon, ACon]:
    def _mod_lookup():
        for _, thing in self.ctx.load(con.mod).tythings:
            yield thing
    for tycon in itertools.chain(self.tythings, _mod_lookup()):
        if isinstance(tycon, ATyCon) and tycon.name == con:
            for acon in tycon.constructors:
                if acon.tag == tag:
                    return tycon, acon
```
`core_pp.py:164`:
```python
def _pp_alt(alt) -> str:
    match alt:
        case DataAlt(con=con, vars=vars):
            if vars:
                return f"{con.surface} {' '.join(v.name.surface for v in vars)}"
            return con.surface
```
`core_pp.py` doesn't even attempt to look up field info; `repl.py` does full type substitution.
**Status:** Validated
**Confidence:** High
**Notes:** `typecheck_expr.py` has `lookup_datacon` and `lookup_tycon` (inherited from `TcCtx`), but the REPL only has `EvalCtx` which only resolves values.

### Claim 5: REPLSession can cache datacon lookups
**Statement:** Because names have fixed uniques, `REPLSession` can safely cache `(Name, tag) -> (ATyCon, ACon)` lookups.
**Source:** `src/systemf/elab3/repl.py:121-131`
**Evidence:**
```python
def get_data_con(self, con: Name, tag: int) -> tuple[ATyCon, ACon]:
    def _mod_lookup():
        for _, thing in self.ctx.load(con.mod).tythings:
            yield thing
    for tycon in itertools.chain(self.tythings, _mod_lookup()):
        ...
```
This linear search happens on every pretty-print of a data value. A `dict[(Name, int), (ATyCon, ACon)]` cache would eliminate repeated scans.
**Status:** Validated
**Confidence:** High
**Notes:** `Name` equality is by `unique` only, and uniques are immutable once allocated.

## Open Questions

- [ ] What persistent data structure should replace `dict[int, Val]`? Python's `immutables.Map` (PyPI) or a simple linked scope chain?
- [ ] Should `TcCtx` be extended with a `CoreBuilder` that knows about tycons/datacons, or should `CoreBuilder` be parameterized with a lookup function?
- [ ] Should the datacon cache be in `REPLSession` or in `REPLContext` (shared across sessions)?

## Related Topics

- `INTERACTIVE_CONTEXT_PERFORMANCE_EXPLORATION.md`
- `INTERACTIVE_CONTEXT_MEMORY_EXPLORATION.md`
- `LET_BINDING_ARCHITECTURE_EXPLORATION.md`

## Unconfirmed Hypotheses

### Hypothesis 1: Linked scope chain is faster than dict copying
**Reason:** Not benchmarked. For shallow stacks dict copying may be faster due to Python's optimized dict implementation.
**Source:** `src/systemf/elab3/eval.py:230`

### Hypothesis 2: Extending TcCtx with core builders couples typechecking and code generation too tightly
**Reason:** GHC separates Core generation from the typechecker. We may want a separate `CoreGen` module.
**Source:** `src/systemf/elab3/typecheck_expr.py:49`
