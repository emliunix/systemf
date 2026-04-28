# Elab3 Meta Guidelines

> Facts and conventions about the `systemf/elab3` codebase for future sessions.
> Last updated: 2026-04-20

---

## 1. Project Architecture

### Repository Layout

```
systemf/src/systemf/elab3/       # Core compiler code
  typecheck_expr.py              # Main typechecker (UNIFIED — see §3)
  tc_ctx.py                      # Base Unifier, TcCtx, Expect (Infer/Check)
  matchc.py                      # Pattern match compiler → CoreCase
  rename.py / rename_expr.py     # Renamer
  scc.py                         # SCC analysis for recursive bindings
  types/                         # AST definitions
    ast.py                         # Surface AST (App, Lam, Let, Case, ...)
    core.py                        # Core AST (CoreApp, CoreLam, CoreCase, ...)
    ty.py                          # Types (TyFun, TyForall, MetaTv, SkolemTv, ...)
    wrapper.py                     # HsWrapper equivalents (WpTyApp, WpFun, WpCast, ...)
    tything.py                     # TyThing (AnId, ACon, ATyCon)
    xpat.py                        # XPat AST (typed patterns for MatchC)
  builtins.py                    # Built-in types
  name_gen.py                    # Name/unique generation

tests/test_elab3/                # Tests (pytest)
analysis/                        # Research docs (GHC exploration, design notes)
changes/                         # Structured change plans
tasks/                           # Task documents
journal/                         # Dev journal entries
```

### Key External Dependency
- **GHC source** at `upstream/ghc/` — primary reference implementation
- Bidirectional type checking modeled on GHC's `TcExpr`/`TcApp`/`tcInstFun`

---

## 2. Technical Stack & Commands

| Tool | Usage |
|------|-------|
| `uv` | Python package manager, at `~/.local/bin/uv` |
| `uv run` | Execute Python commands. **Never set PYTHONPATH manually.** |
| Ruff | Linting/formatting |
| mypy | Type checking |
| pytest | Testing |

```bash
# Run tests
uv run pytest systemf/tests/test_elab3/ -v

# Run specific test
uv run pytest systemf/tests/test_elab3/test_matchc.py -v

# Type check
uv run mypy systemf/src/systemf/elab3/
```

---

## 3. Critical: `typecheck_expr2.py` Was Deleted

**Do NOT create `typecheck_expr2.py`.** It was merged into `typecheck_expr.py` on 2026-04-20 (commit `ad1a19a`).

- `typecheck_expr.py` is now the **single unified typechecker**
- `tc_ctx.py` was extracted from the old `typecheck_expr.py` to hold `TcCtx`, `Unifier`, `Expect`
- Some tests still import from `typecheck_expr2` — **they are broken** and need fixing

Current `typecheck_expr.py` contains:
- `TypeChecker` class (extends `Unifier` from `tc_ctx`)
- `InstFunArg` / `InstFunWrap` / `InstFun` command stream types
- `inst_fun()` method for function type instantiation
- Pattern checking (`pat()`)
- Expression dispatch (`expr()`)

---

## 4. Design Patterns Used

### Bidirectional Type Checking
- `Expect = Infer | Check`
- `Infer` has a `Ref[Ty]` that gets filled in
- `Check` has an expected `Ty`
- Typechecking returns `TyCkRes = Callable[[], CoreTm]` (thunk for Core generation)

### Command Stream for Applications
`inst_fun()` returns `list[InstFun]` where:
```python
@dataclass class InstFunArg: ty: Ty
@dataclass class InstFunWrap: wrap: Wrapper
type InstFun = InstFunArg | InstFunWrap
```

Walk the function type left-to-right, yielding commands:
- `TyForall` → `InstFunWrap` (instantiation wrapper)
- `TyFun` → `InstFunArg` (value argument type)

Rebuild by iterating commands and applying wrappers to function head / args.

### Wrapper Composition
- `WpCompose(g, f)` means "apply f first, then g" (`g . f`)
- `wp_compose()` is a smart constructor that simplifies `WP_HOLE`
- Wrappers are applied to the **function expression head**, not to arguments
- `WpFun` is for **subtyping/coercion** (eta expansion), NOT for instantiation

### Generator Pattern
```python
def inst_fun(...) -> tuple[list[InstFun], Ty]:
    def _inst(...) -> Generator[InstFun, None, Ty]:
        ...
    return run_capture_return(_inst(...))
```

---

## 5. GHC Correspondence Map

| Our Component | GHC Equivalent | File |
|---------------|----------------|------|
| `inst_fun()` | `tcInstFun` | `GHC/Tc/Gen/App.hs` |
| `TypeChecker.expr()` | `tcExpr` | `GHC/Tc/Gen/Expr.hs` |
| `match_funtys()` | `matchExpectedFunTys` | `GHC/Tc/Utils/Unify.hs` |
| `poly_check_expr()` | `tcPolyExpr` / `tcPolyExprCheck` | `GHC/Tc/Gen/Expr.hs` |
| `skolemise()` | `topSkolemise` / `tcSkolemise` | `GHC/Tc/Utils/Instantiate.hs` |
| `instantiate()` | `topInstantiate` | `GHC/Tc/Utils/Instantiate.hs` |
| `pat()` | `tcPat` | `GHC/Tc/Gen/Pat.hs` |
| `MatchC` | `GHC/HsToCore/Pmc` | `GHC/HsToCore/Pmc/` |
| `CoreCase` | `Case` | `GHC/Core.hs` |

**Key difference from GHC**: We don't use `HsExprArg` with interleaved `EWrap`. We use the `InstFun` command stream which is a cleaned-up projection.

---

## 6. Working Conventions

### Before Implementing
1. **Check GHC source first** — the user expects deep understanding of GHC's approach
2. **Read relevant skills** from `.agents/skills/` (docs, testing, change-plan, etc.)
3. **Check `analysis/`** for existing research on the topic
4. **Check `changes/` and `tasks/`** for planned work

### During Exploration
- Create `analysis/` docs for non-trivial research (GHC call hierarchy, design decisions)
- Use mermaid diagrams for call hierarchies and data flow
- Trace actual GHC code paths, don't rely on memory
- Ask pointed questions about edge cases (levels, wrappers, coercion directions)

### Code Style
- Use `match/case` (Python 3.10+)
- Type hints everywhere
- `dataclass` for simple data types
- Generator pattern with `run_capture_return` for accumulating results
- `functools.reduce` for composing wrappers

### Testing
- Tests in `tests/test_elab3/`
- Use `FakeCtx` pattern for mock TcCtx in tests
- pytest with descriptive docstrings

### Commit Style
- `feat(elab3): ...` for features
- `refactor(elab3): ...` for refactoring
- `test(elab3): ...` for tests
- `save` commits exist but are just checkpoints

---

## 7. Known Traps

| Trap | Why | Fix |
|------|-----|-----|
| `typecheck_expr2.py` doesn't exist | Was merged into `typecheck_expr.py` | Import from `typecheck_expr` or `xpat` |
| `WpFun` during instantiation | `WpFun` is for subtyping, NOT for `inst_fun` | Use `WpTyApp`/`WpCast` on function head only |
| `reversed(args)` + `pop()` | Stack idiom — cancel each other | It's correct, don't "fix" it |
| `tcInstFun` vs `inst_fun` | GHC returns `[HsExprArg]`, we return `list[InstFun]` | Don't try to match GHC's interleaved EWrap exactly |
| Skolemisation levels | `tcInstSkolTyVarsPushLevel` pushes +1 | Skolems belong to implication at current+1 |
| `topSkolemise` vs `skolemiseRequired` | Former for checking, latter for lambdas | Use correct one for context |

---

## 8. Open Questions / Active Work

1. **Case expression typechecking** — `expr()` dispatch has no `Case` handler
2. **`pat()` returns CPS, not `XPat`** — need `check_pat()` variant for MatchC
3. **Let bindings** — `TODO: scc into groups and properly handle recursive bindings`
4. **Tests broken** — imports from `typecheck_expr2` need updating
5. **Core error term** — `MRFallible` needs a `CoreTm` error term
