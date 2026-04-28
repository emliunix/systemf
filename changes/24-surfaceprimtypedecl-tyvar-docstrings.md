# Change 24 — SurfacePrimTypeDecl: TyVar params with inline docstrings

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
# surface/parser/declarations.py lines 389-390
params_tokens = yield match_ident().many()
params = [t.value for t in params_tokens]
```

This means inline docstrings (`-- ^`) on type parameters are silently dropped — there is no mechanism to attach documentation to individual type variables in `prim_type` declarations.

### How inline docstrings work elsewhere

Inline (`-- ^`, `DocstringType.FOLLOWING`) docstrings are consumed by `doc_type_parser` in `type_parser.py` (lines 289–315):

```python
# type_parser.py lines 289-315
def doc_type_parser(constraint=None):
    @generate
    def parser():
        pre_docs  = yield match_inline_docstring_strict().many()
        ty        = yield type_app_parser(constraint)
        post_docs = yield match_inline_docstring_strict().many()
        return attach_docs(ty, pre_docs, post_docs)
    return parser
```

`attach_docs` does a `dataclasses.replace(ty, docstring=...)` using the base field `SurfaceType.docstring: str | None` (surface/types.py line 36).

For arrow-typed `prim_op` signatures this already works: the arrow parser calls `doc_type_parser` for each argument, so `prim_op foo : A -- ^ doc -> B` produces a `SurfaceTypeVar` / `SurfaceTypeConstructor` with `docstring` populated.

### Surface type var node

`SurfaceTypeVar` is the correct surface-level representation of a type variable:

```python
# surface/types.py lines 40-47
@dataclass(frozen=True, kw_only=True)
class SurfaceTypeVar(SurfaceType):
    name: str
```

`SurfaceType` (base) already carries `docstring: str | None` (line 36), so `SurfaceTypeVar` can hold docstrings for free.

### Downstream consumers of `SurfacePrimTypeDecl.params`

Searched the full repo for `\.params` on `SurfacePrimTypeDecl` / `prim_type`:

| File | Location | Usage |
|---|---|---|
| `surface/types.py` | line 623–624 | `__str__`: `' '.join(self.params)` |
| `elab3/rename.py` | (search needed) | registers param names as type vars in scope |
| `elab3/typecheck.py` | (search needed) | creates `ATyCon` with `tyvars` from params |

### `match_inline_docstring` helpers already available

`type_parser.py` already exports two matchers:

- `match_inline_docstring()` — always succeeds, returns `str | None`
- `match_inline_docstring_strict()` — fails on miss (for `.many()`)

These are importable from `type_parser.py`.

---

## Design

### Option chosen: `SurfaceTyVar` params with `doc_type_parser`-style parsing

Change `params: list[str]` → `params: list[SurfaceTypeVar]`, and parse each param as:

```
pre_doc* ident post_doc*
```

using the existing `match_inline_docstring_strict()` and `match_ident()` helpers.

### 1. New field type in `SurfacePrimTypeDecl`

```python
# surface/types.py
params: list[SurfaceTypeVar]   # was list[str]
```

`__str__` updated to emit `param.name` (and optionally re-emit docstrings as `-- ^` comments, for consistency with `SurfaceTypeArrow.__str__`).

### 2. New helper: `tyvar_with_doc_parser`

In `surface/parser/type_parser.py` (or `declarations.py`), add:

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

### 3. Updated `prim_type_parser`

```python
# declarations.py  prim_type_parser()
params = yield tyvar_with_doc_parser().many()

return SurfacePrimTypeDecl(
    name=name,
    params=params,    # list[SurfaceTypeVar]
    location=loc,
    docstring=None,
    pragma=None,
)
```

### 4. Update downstream consumers

All consumers of `params` that expect `str` must be updated to use `param.name`:

| File | Change |
|---|---|
| `surface/types.py` `__str__` | `' '.join(p.name for p in self.params)` |
| `elab3/rename.py` | iterate `p.name` instead of `p` |
| `elab3/typecheck.py` | iterate `p.name` instead of `p` |
| `elab3/pp_tything.py` | if it accesses `.params` |
| Tests: `test_surface_parser_*`, `test_rename.py`, `test_putting2007_*` | update string expectations if `__str__` changes |

### 5. `SurfacePrimTypeDecl.__str__` — docstring emission

For consistency with `SurfaceTypeArrow`, re-emit `-- ^` comments when a param has a docstring:

```python
def __str__(self) -> str:
    parts = []
    for p in self.params:
        if p.docstring:
            parts.append(f"-- ^ {p.docstring}")
        parts.append(p.name)
    params_str = " ".join(parts)
    if params_str:
        return f"prim_type {self.name} {params_str}"
    return f"prim_type {self.name}"
```

---

## Why it works

- `match_inline_docstring_strict().many()` already handles zero-or-more `-- ^` tokens — it succeeds immediately (returning `[]`) when the next token is not a following docstring. So a plain `prim_type Int a` with no doc comments parses identically to before; no existing tests break.
- `SurfaceTypeVar` already exists and carries `docstring`. No new AST node needed.
- The `tyvar_with_doc_parser` mirrors `doc_type_parser` exactly, just with `match_ident()` instead of `type_app_parser`. Same pre/post pattern.
- Downstream consumers only used `.params` as plain strings; changing to `SurfaceTypeVar` and updating call sites to use `.name` is mechanical.

---

## Files

| File | Action | Change |
|---|---|---|
| `systemf/src/systemf/surface/types.py` | **Modify** | `SurfacePrimTypeDecl.params: list[str]` → `list[SurfaceTypeVar]`; update `__str__` |
| `systemf/src/systemf/surface/parser/declarations.py` | **Modify** | `prim_type_parser`: use `tyvar_with_doc_parser().many()`; add or import helper |
| `systemf/src/systemf/surface/parser/type_parser.py` | **Modify** (or `declarations.py`) | Add `tyvar_with_doc_parser()` helper |
| `systemf/src/systemf/elab3/rename.py` | **Modify** | Update `params` iteration to use `.name` |
| `systemf/src/systemf/elab3/typecheck.py` | **Modify** | Update `params` iteration to use `.name` |
| `systemf/src/systemf/elab3/pp_tything.py` | **Modify** (if needed) | Update `params` access |
| `tests/test_elab3/test_surface_*.py` | **Review** | Confirm existing `prim_type` tests still pass |
| `tests/test_elab3/test_rename.py` | **Review** | Confirm no string-comparison regressions |
| New test file or additions | **Add** | Tests for `prim_type Ref a -- ^ The element type` parsing |
