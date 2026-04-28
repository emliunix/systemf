# Change 24c — tycon_arg_parser: SurfaceTypeVar params for both data and prim_type

> Supersedes `24-surfaceprimtypedecl-tyvar-docstrings.md` and `24b-...amended.md`.
> Extends scope to cover `SurfaceDataDeclaration.params` in addition to `SurfacePrimTypeDecl.params`.

## Facts

### Both declarations use `list[str]` for type params

```python
# surface/types.py line 565
class SurfaceDataDeclaration(SurfaceDeclaration):
    params: list[str]

# surface/types.py line 617
class SurfacePrimTypeDecl(SurfaceDeclaration):
    params: list[str]
```

Both parsers use the identical raw pattern:

```python
# declarations.py lines 280-281  (data_parser)
params_tokens = yield match_ident().many()
params = [t.value for t in params_tokens]

# declarations.py lines 389-390  (prim_type_parser)
params_tokens = yield match_ident().many()
params = [t.value for t in params_tokens]
```

### `SurfaceTypeVar` already carries `docstring`

```python
# surface/types.py lines 40-47
@dataclass(frozen=True, kw_only=True)
class SurfaceTypeVar(SurfaceType):
    name: str
    # inherits: docstring: str | None  (SurfaceType line 36)
```

No new AST node needed.

### Existing inline-docstring matchers in `type_parser.py`

- `match_inline_docstring_strict()` (lines 109–125) — fails on miss, for `.many()`
- Pattern: `pre.many() >> atom << post.many()` used in `doc_type_parser` (lines 289–315)

### All downstream consumers of `params` (confirmed by grep)

| File | Line | Usage | Change |
|---|---|---|---|
| `surface/types.py` | 572 | `' '.join(self.params)` in `SurfaceDataDeclaration.__str__` | `' '.join(p.name for p in self.params)` |
| `surface/types.py` | 623–624 | `' '.join(self.params)` in `SurfacePrimTypeDecl.__str__` | `' '.join(p.name for p in self.params)` |
| `elab3/rename.py` | ~117 | `self.new_lhs_names(lhs_res.decl.params, ...)` | `[p.name for p in ...]` |
| `elab3/rename.py` | ~118 | `[None] * len(lhs_res.decl.params)` | `tyvars_to_argdocs(lhs_res.decl.params)` |
| `elab3/rename.py` | ~169 | `self.new_lhs_names(pt.params, ...)` | `[p.name for p in pt.params]` |
| `elab3/rename.py` | ~172 | `[None] * len(pt.params)` | `tyvars_to_argdocs(pt.params)` |

`elab3/typecheck.py` — no `.params` access, confirmed by grep.

### Tests that assert on `params` as strings

```python
# test_declarations.py line 51
assert "a" in result.params          # will break — result.params is list[SurfaceTypeVar]

# test_declarations.py line 59
assert len(result.params) == 2       # still works (len unchanged)
```

---

## Design

### 1. Add `tycon_arg_parser` in `type_parser.py`

```python
def tycon_arg_parser() -> P[SurfaceTypeVar]:
    """Parse a single type-constructor argument with optional inline docstrings.

    Grammar:  ("--^" doc)* ident ("--^" doc)*
    """
    @generate
    def parser():
        pre_docs  = yield match_inline_docstring_strict().many()
        ident_tok = yield match_ident()
        post_docs = yield match_inline_docstring_strict().many()
        docs = pre_docs + post_docs
        docstring = "\n".join(docs) if docs else None
        return SurfaceTypeVar(
            name=ident_tok.value,
            location=ident_tok.location,
            docstring=docstring,
        )
    return parser
```

Add `"tycon_arg_parser"` to `__all__` in `type_parser.py`.

### 2. Update `SurfaceDataDeclaration.params`

```python
# surface/types.py
params: list[SurfaceTypeVar]   # was list[str]
```

Update `__str__`:

```python
params_str = " ".join(p.name for p in self.params) if self.params else ""
```

### 3. Update `SurfacePrimTypeDecl.params`

```python
# surface/types.py
params: list[SurfaceTypeVar]   # was list[str]
```

Update `__str__`:

```python
if self.params:
    return f"prim_type {self.name} {' '.join(p.name for p in self.params)}"
return f"prim_type {self.name}"
```

### 4. Update `data_parser` in `declarations.py`

```python
params = yield tycon_arg_parser().many()
# (remove params_tokens intermediary)
```

### 5. Update `prim_type_parser` in `declarations.py`

```python
params = yield tycon_arg_parser().many()
```

Add `tycon_arg_parser` to the import from `type_parser`.

### 6. Update `rename.py` — both data and prim_type call sites

- Line ~117: `self.new_lhs_names(lhs_res.decl.params, ...)` → `self.new_lhs_names([p.name for p in lhs_res.decl.params], ...)`
- Line ~118: `[None] * len(lhs_res.decl.params)` → `tyvars_to_argdocs(lhs_res.decl.params)`
- Line ~169: `self.new_lhs_names(pt.params, ...)` → `self.new_lhs_names([p.name for p in pt.params], ...)`
- Line ~172: `[None] * len(pt.params)` → `tyvars_to_argdocs(pt.params)`

### 7. Fix failing test

```python
# test_declarations.py line 51 — before
assert "a" in result.params

# after
assert any(p.name == "a" for p in result.params)
# or equivalently:
assert result.params[0].name == "a"
```

---

## Why it works

- `match_inline_docstring_strict().many()` returns `[]` immediately when the next token is not `-- ^`. Plain `data Maybe a` and `prim_type Ref a` parse identically to before, no regressions.
- Both `SurfaceDataDeclaration` and `SurfacePrimTypeDecl` share the exact same `list[str]` → `list[SurfaceTypeVar]` migration pattern — one helper covers both.
- `tyvars_to_argdocs` already exists in `rename.py` and accepts `list[SurfaceTypeVar]`.

---

## Files

| File | Action | Change |
|---|---|---|
| `systemf/src/systemf/surface/types.py` | **Modify** | `SurfaceDataDeclaration.params` and `SurfacePrimTypeDecl.params`: `list[str]` → `list[SurfaceTypeVar]`; update both `__str__` methods |
| `systemf/src/systemf/surface/parser/type_parser.py` | **Modify** | Add `tycon_arg_parser()`; add to `__all__` |
| `systemf/src/systemf/surface/parser/declarations.py` | **Modify** | Import `tycon_arg_parser`; update `data_parser` and `prim_type_parser` to use it |
| `systemf/src/systemf/elab3/rename.py` | **Modify** | 4 call sites: use `[p.name for p in ...]` and `tyvars_to_argdocs(...)` |
| `systemf/tests/test_surface/test_parser/test_declarations.py` | **Modify** | Fix string-containment assertion (`"a" in result.params`) |
| New tests (optional) | **Add** | Parser test for `prim_type Ref a -- ^ doc` and `data F a -- ^ doc = ...` |
