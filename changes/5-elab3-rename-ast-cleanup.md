# Change Plan: elab3 AST Cleanup — Pure Renamed AST + Name.loc Optional + builtins Fix

**Previous plan:** `changes/4-elab3-nested-patterns.md`

## Why a new plan

Review of `elab3/ast.py` revealed mixed concerns: it contains both renamed and pre-renaming (Parsed/Rn-prefixed) declaration types. The goal is to make `ast.py` contain **only** the renamed term/pattern/declaration AST, with a separate module handling the surface-to-renamed conversion. We also need to fix `builtins.py` and make `Name.loc` optional so parser locations can propagate cleanly.

## Facts

- `elab3/ast.py` currently contains:
  - Renamed expressions: `Var`, `GlobalVar`, `Lam`, `App`, `Let`, `Ann`, `LitExpr`, `Case`
  - Renamed patterns: `Pat`, `VarPat`, `ConPat`, `LitPat`, `DefaultPat`
  - Renamed declarations: `DataDecl`, `DataConDecl`, `TermDecl`
  - **Pre-renaming declarations**: `RnDataConDecl`, `RnDataDecl`, `RnTermDecl`, `ImportDecl`, `ModuleDecls`
- There is **no `DataCon` expression node** in the current `ast.py` — constructor applications are already represented as normal `App(Var/GlobalVar, arg)` chains, which is correct.
- There is **no `LetRec` syntax** in the current `ast.py` — only `Let` with a `list[Binding]`. Recursive lets can be represented as multiple `Binding`s in a single `Let` if needed, or we can add `LetRec` later. For now, `Let` is sufficient.
- `elab3/types.py` defines `Name` with `loc: Any` as a **required** field.
- `elab3/builtins.py` constructs `Name("Bool", 1, None)` but the file has **two conflicting definitions** of `BUILTIN_UNIQUES` (the second overwrites the first), and the old flat unique mapping is stale.

## Design

### 1. Make `Name.loc` optional

In `elab3/types.py`:

```python
from systemf.utils.location import Location

@dataclass(frozen=True)
class Name:
    surface: str
    unique: int
    loc: Location | None = None
```

This lets the parser create `Name`s with location info while builtins can omit it.

### 2. Clean up `elab3/ast.py` — keep only renamed AST

Remove all pre-renaming types:
- Delete `RnDataConDecl`, `RnDataDecl`, `RnTermDecl`
- Delete `ImportDecl`, `ModuleDecls`

`ast.py` should contain only:
- Expressions: `Expr` base, `Var`, `GlobalVar`, `Lam`, `App`, `Let`, `Ann`, `LitExpr`, `Case`
- Patterns: `Pat` base, `VarPat`, `ConPat`, `LitPat`, `DefaultPat`
- Declarations: `DataDecl`, `DataConDecl`, `TermDecl`
- Support: `AnnotName`, `Binding`, `CaseBranch`

The surface-to-renamed conversion will be a recursive function in a **new module** (e.g. `elab3/renamer.py`), not in `ast.py`.

### 3. Fix `elab3/builtins.py`

- Remove the duplicate `BUILTIN_UNIQUES` definition.
- Remove the stale TODO/old code block.
- Keep the `Name`-based structure and extend it with all builtins (Bool, True, False, Int, String, List, Pair, primitive ops).

Example target structure:

```python
BUILTIN_BOOL = Name("Bool", 1)
BUILTIN_TRUE = Name("True", 2)
# ... etc


def build_builtins(mod_names: dict[str, list[Name]]) -> dict[tuple[str, str], int]:
    return {
        (mod, name.surface): name.unique
        for (mod, names) in mod_names.items()
        for name in names
    }


BUILTIN_UNIQUES: dict[tuple[str, str], int] = build_builtins({
    "builtins": [
        BUILTIN_BOOL,
        BUILTIN_TRUE,
        # ... etc
    ]
})
```

### 4. Confirm expression design

- Constructor values are **normal function application** (`App(GlobalVar(consName), arg)`), not a special `DataCon` expression node. This matches GHC Core where constructors are just global ids applied to arguments.
- `Let` with `list[Binding]` is sufficient for both recursive and non-recursive bindings; we do not need a separate `LetRec` node at this layer.

## Why It Works

- `Name.loc` being optional removes the awkward `None` requirement in `builtins.py` and allows clean parser integration.
- `ast.py` becomes a clean, single-concern module: the renamed AST only.
- `builtins.py` becomes the single source of truth for pre-allocated builtin names.
- Keeping constructor applications as normal `App` nodes is the standard design (GHC Core, System F) and avoids a redundant expression form.

## Files

- `systemf/src/systemf/elab3/types.py` — make `Name.loc` optional (`Location | None = None`)
- `systemf/src/systemf/elab3/ast.py` — remove `Rn*`, `ImportDecl`, `ModuleDecls`; keep only renamed AST
- `systemf/src/systemf/elab3/builtins.py` — remove duplicate/stale code; extend with all builtins

## Update (2026-03-30)

### Implemented

- **`systemf/src/systemf/elab3/types.py`**: `Name.loc` changed from required `loc: Any` to optional `loc: Location | None = None`, imported from `systemf.utils.location`.
- **`systemf/src/systemf/elab3/builtins.py`**: Removed duplicate/stale `BUILTIN_UNIQUES` block. Kept original `build_builtins(mod_names: dict[str, list[Name]]) -> dict[tuple[str, str], int]` function. Extended with all builtins using `Name("...", unique)` (no explicit `None` loc needed).
- **`systemf/src/systemf/elab3/ast.py`**: Not yet cleaned up — `RnDataConDecl`, `RnDataDecl`, `RnTermDecl`, `ImportDecl`, `ModuleDecls` still present. Pending removal in follow-up.
