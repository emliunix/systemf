# Change 24b — SurfacePrimTypeDecl: TyVar params with inline docstrings (amended)

> Amended from `24-surfaceprimtypedecl-tyvar-docstrings.md` based on review findings.

## Facts

### Current state

`SurfacePrimTypeDecl` stores type parameters as `list[str]`:

```python
# surface/types.py lines 616-617
name: str
params: list[str]
```

The parser collects them with a raw `match_ident().many()`:

```python
# declarations.py lines 389-390
params_tokens = yield match_ident().many()
params = [t.value for t in params_tokens]
```

Inline docstrings (`-- ^`) on type parameters are silently dropped.

In `rename_prim_ty` (rename.py ~line 169–171):

```python
self.new_lhs_names(pt.params, pt.location)   # line 169: passes list[str]
[None] * len(pt.params)                       # line 171: produces list of None (discards docs)
```

`tyvars_to_argdocs` (rename.py ~line 293–297) already exists and accepts `list[SurfaceTypeVar]`:

```python
def tyvars_to_argdocs(tyvars: list[SurfaceTypeVar]) -> list[str | None]:
    return [tv.docstring for tv in tyvars]
```

But it is **not called** from `rename_prim_ty` — docs are permanently discarded there.

### How inline docstrings work elsewhere

`doc_type_parser` (type_parser.py lines 289–315) wraps `type_app_parser` with pre/post `match_inline_docstring_strict().many()`. `attach_docs` does `dataclasses.replace(ty, docstring=...)`. This pattern is the established convention.

`SurfaceTypeArrow.__str__` (types.py line 80) re-emits `-- ^ {param_doc}` when `arg.docstring` is set — confirmed.

### Surface type var node

`SurfaceTypeVar` (types.py lines 40–47) already carries `docstring: str | None` from `SurfaceType` (line 36). No new AST node needed.

### Downstream consumers of `params` (confirmed by grep)

| File | Line | Usage | Change needed? |
|---|---|---|---|
| `surface/types.py` | 623–624 | `' '.join(self.params)` in `__str__` | Yes — use `p.name` |
| `elab3/rename.py` | ~169 | `self.new_lhs_names(pt.params, ...)` | Yes — `[p.name for p in pt.params]` |
| `elab3/rename.py` | ~171 | `[None] * len(pt.params)` | Yes — replace with `tyvars_to_argdocs(pt.params)` |
| `elab3/typecheck.py` | — | No `.params` access found | No change needed |
| `elab3/pp_tything.py` | — | TBD — verify during implementation | Check |

---

## Design

### 1. Change field type in `SurfacePrimTypeDecl`

```python
# surface/types.py
params: list[SurfaceTypeVar]   # was list[str]
```

### 2. Update `SurfacePrimTypeDecl.__str__`

```python
@override
def __str__(self) -> str:
    parts = []
    for p in self.params:
        if p.docstring:
            parts.append(f"{p.name} -- ^ {p.docstring}")
        else:
            parts.append(p.name)
    params_str = " ".join(parts)
    if params_str:
        return f"prim_type {self.name} {params_str}"
    return f"prim_type {self.name}"
```

### 3. Add `tyvar_with_doc_parser` in `type_parser.py`

Placement: `type_parser.py` — all `doc_*_parser` helpers live there; `declarations.py` already imports from it.

```python
def tyvar_with_doc_parser() -> P[SurfaceTypeVar]:
    """Parse: ("--^" doc)* ident ("--^" doc)*"""
    @generate
    def parser():
        pre_docs   = yield match_inline_docstring_strict().many()
        ident_tok  = yield match_ident()
        post_docs  = yield match_inline_docstring_strict().many()
        docs = pre_docs + post_docs
        docstring = "\n".join(docs) if docs else None
        return SurfaceTypeVar(
            name=ident_tok.value,
            location=ident_tok.location,
            docstring=docstring,
        )
    return parser
```

Add to `__all__` in `type_parser.py`.

### 4. Update `prim_type_parser` in `declarations.py`

```python
from systemf.surface.parser.type_parser import ..., tyvar_with_doc_parser

def prim_type_parser() -> P[SurfacePrimTypeDecl]:
    @generate
    def parser():
        prim_token = yield match_keyword("prim_type")
        loc = prim_token.location
        name_token = yield match_ident()
        name = name_token.value
        params = yield tyvar_with_doc_parser().many()
        return SurfacePrimTypeDecl(name=name, params=params, location=loc, docstring=None, pragma=None)
    return parser
```

Also add `SurfaceTypeVar` to imports from `systemf.surface.types` in `declarations.py` (needed if `tyvar_with_doc_parser` is imported at the type level — in practice only needed if type annotations reference it directly).

### 5. Update `rename_prim_ty` in `rename.py`

- Line 169: `self.new_lhs_names(pt.params, pt.location)` → `self.new_lhs_names([p.name for p in pt.params], pt.location)`
- Line 171: `[None] * len(pt.params)` → `tyvars_to_argdocs(pt.params)`

### 6. Tests

- Confirm all existing `prim_type` parser tests pass unchanged (no-docstring case is identical).
- Add new parser test: `prim_type Ref a -- ^ The element type` → `params[0].docstring == "The element type"`.
- Add rename test verifying docstring propagates through `rename_prim_ty`.

---

## Why it works

- `match_inline_docstring_strict().many()` succeeds immediately (returns `[]`) when the next token is not `-- ^`. Plain `prim_type Int a` parses identically to before.
- `SurfaceTypeVar` + `docstring` is already the established pattern (used in type-arrow args).
- `tyvars_to_argdocs` already exists and handles the rename-pass case — the change just wires it in.
- `SurfaceTypeArrow.__str__` confirms the `-- ^` re-emission convention.

---

## Files

| File | Action | Change |
|---|---|---|
| `systemf/src/systemf/surface/types.py` | **Modify** | `SurfacePrimTypeDecl.params: list[str]` → `list[SurfaceTypeVar]`; update `__str__` |
| `systemf/src/systemf/surface/parser/type_parser.py` | **Modify** | Add `tyvar_with_doc_parser()`; add to `__all__` |
| `systemf/src/systemf/surface/parser/declarations.py` | **Modify** | Import `tyvar_with_doc_parser`; update `prim_type_parser` body |
| `systemf/src/systemf/elab3/rename.py` | **Modify** | Line ~169: use `[p.name for p in pt.params]`; line ~171: use `tyvars_to_argdocs(pt.params)` |
| `systemf/src/systemf/elab3/pp_tything.py` | **Check** | Verify no `params` string access; update if found |
| Tests: existing `prim_type` parser tests | **Review** | Confirm no regressions |
| Tests: new test(s) | **Add** | Parser + rename tests for docstring-annotated type vars |
