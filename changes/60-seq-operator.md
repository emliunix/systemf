# 60: Sequence Operator (`;`)

**Date:** 2026-06-21
**Status:** Design (reviewed — awaiting approval to implement)
**Area:** `systemf/src/systemf/surface/parser/lexer.py`, `systemf/src/systemf/surface/parser/expressions.py`

## Problem

The sequence operator `;` is declared at every layer **except** the lexer and parser, so any
program that writes `effect1 ; effect2` fails to parse:

```
$ uv run bub sf-check test -L .
Error: test.sf:78:13: Unexpected character: ';'
```

This blocks the natural sequencing syntax. Authors currently work around it with the
lambda-application idiom from `compact` in `bub.sf`:

```systemf
(\_unit -> effect2) effect1
```

`main.sf`'s `with_compact` was written with `;` and is therefore unparsable as-is.

## Facts

The operator is fully wired from the **rename** layer down — only the front-end (lex + parse)
is missing.

| Layer | State | Location |
|---|---|---|
| Type + definition | ✅ | `builtins.sf:89` — `seq :: forall a b. a -> b -> b = \a b -> b` |
| Builtin name | ✅ | `builtins.py:52` — `BUILTIN_SEQ = Name("builtins", "seq", 34)` |
| Bin-op → builtin mapping | ✅ | `builtins.py:111` — `";": BUILTIN_SEQ` in `BUILTIN_BIN_OPS` |
| Rename (`SurfaceOp` → AST) | ✅ | `rename_expr.py:138-141` — `SurfaceOp(op=";")` ⇒ `App(App(Var(seq), l), r)` |
| Runtime | ✅ (none needed) | `seq` is an ordinary lambda in `builtins.sf`; it evaluates via normal application, so no `repl._reg(...)` entry is required (unlike `int_plus`, which needs an RTS binding because integers are not lambdas). |
| **Lexer token** | ❌ **MISSING** | `lexer.py:110-148` — `TOKEN_PATTERNS` has no `;` entry. The lexer falls through to its "unexpected character" error. |
| **Parser precedence level** | ❌ **MISSING** | `expressions.py:491-708` — the precedence ladder is `multiplicative → additive → cons → comparison → logical_and → logical_or`; there is no `seq` level, and `op_parser` (`:711`) bottoms out at `logical_or_parser`. |

Existing operator parser structure (precedence ladder, all left-associative except `cons`):

```
op_parser  ─► logical_or_parser   (||)         :674   lowest
            └► logical_and_parser (&&)         :637
             └► comparison_parser (== < > …)   :599
              └► cons_parser      (:)          :567   right-assoc
               └► additive_parser (+ - ++)     :529
                └► multiplicative (* /)        :491
                 └► app_parser                 :higher
```

## Evaluation semantics: RESOLVED (plain lambda suffices)

System F is a **strict call-by-value CEK machine** (`eval.py:114`:
`"Strict CBV CEK evaluator."`). Function arguments are fully evaluated before
beta-reduction (`CoreApp` → `Ar` → `Ap` at `eval.py:192-245`). `VAsync` is
awaited inline the moment a primop application produces it (`eval.py:254`,
via `unasync` at `:294-299`); it never persists as a value.

Trace of `effect1 ; effect2` (= `App(App(Var(seq), effect1), effect2)`):

1. `Var(seq)` → `VClosure(\a b -> b)` from `builtins.sf`.
2. CBV evaluates `effect1` → primop application → `VAsync` → **awaited, side effect runs** → unit.
3. Unit bound to `a` (discarded by the lambda).
4. CBV evaluates `effect2` → **side effect runs**.
5. Result = `effect2`'s value.

The lambda discards the *value* of `a`, but the *side effect* already ran
during step 2's CBV evaluation. **No forcing RTS `seq` is needed.**

## Design

Three front-end additions, reusing the `SemicolonToken` class that already
exists (`surface/types.py:429-431`) but is currently dead code.

### 1. Lexer: tokenize `;` as `SemicolonToken`

Two edits in `lexer.py`:

- Add `("SEQ", r";")` to `TOKEN_PATTERNS`, in the single-character operators
  block (~`:133`, after `DOT`). No multi-char operator starts with `;`, so
  ordering is unconstrained beyond "after multi-char operators" (already met).
- Add a handler in `_create_token` (`:280-416`); the current `else` clause
  (`:414-416`) returns `None`, which would **silently drop** the token. Add:
  ```python
  elif token_type == "SEQ":
      return SemicolonToken(operator=value, location=loc)
  ```
  and import `SemicolonToken` from `surface/types` (not currently imported).

### 2. Parser: add `seq_parser` as the new lowest precedence level

`seq` binds **looser than `||`** and is **left-associative**, matching how
sequencing operators behave conventionally (Haskell `>>` is `infixl 1`). In
`expressions.py`:

- Import `SemicolonToken` and define `SEQ = match_token(SemicolonToken)`
  alongside the existing `OR = match_token(OrToken)` / `AND` (`:182-183`).
  (`OR`/`AND` are defined locally via `match_token`, not imported as tokens.)
- Add `seq_parser` after `logical_or_parser` (`:674-708`):
  ```python
  def seq_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
      """Parse sequence expressions: left ; right (left-associative, lowest precedence)."""
      @generate
      def parser():
          left = yield logical_or_parser(constraint)
          loc = left.location
          ops_and_rights = []
          while True:
              semi = yield SEQ.optional()
              if semi is None:
                  break
              right = yield logical_or_parser(constraint)
              ops_and_rights.append((semi, right))
          result = left
          for semi, right in ops_and_rights:
              result = SurfaceOp(left=result, op=semi.value, right=right, location=loc)
          return result
      return parser
  ```
  (`op=semi.value` — not a hardcoded `";"` — matches the pattern used by the
  other operator parsers at `:522`, `:560`.)
- Rebase `op_parser` (`:711`) to start from `seq_parser` instead of
  `logical_or_parser`.

`SurfaceOp(op=";")` then flows through the already-correct rename path
(`rename_expr.py:138`) → `App(App(Var(seq), l), r)`, typechecks against
`seq :: forall a b. a -> b -> b`, and evaluates as a normal lambda. No other
layer needs changes.

### Associativity / precedence rationale

- **Lowest precedence**: `a || b ; c` means `(a || b) ; c`, not `a || (b ; c)`.
  Sequence is structurally outermost.
- **Left-associative**: `a ; b ; c` reads left-to-right as a program.

### Grammar interaction: `if` / `let` bodies absorb `;` (inherent, not new)

`if`/`let`/`case`/lambda sit as alternatives in `expr_parser` *alongside*
`op_parser`, not inside the operator ladder, and their sub-parsers call
`expr_parser` recursively. So:

- `if c then e1 else e2 ; rest` parses as `if c then e1 else (e2 ; rest)`,
  **not** `(if c then e1 else e2) ; rest`. (Diverges from OCaml, where `;` is
  lower precedence than `if`.) To sequence after an `if`, parenthesize:
  `(if c then e1 else e2) ; rest`.
- `let x = 1 in x ; foo` → `let x = 1 in (x ; foo)` (the `let` body extends
  rightward — usually what is wanted).

This behavior is inherent to the existing grammar shape (all operators share
it), not introduced by this change. Worth documenting for users.

## Review findings (incorporated)

- **`SemicolonToken` already exists** (`surface/types.py:429-431`) and is
  referenced by `helpers.py:402-412` as a braces-mode block separator. Both
  are currently dead code because the lexer never produced `;`. This change
  reuses the existing token class rather than introducing a new one.
- **Braces-mode `;` separator**: `terminator()` (`helpers.py:402`) treats `;`
  as a statement separator inside `{ item; item; ... }`. Once `;` is lexed,
  `seq_parser` could in principle consume a `;` that `terminator` expected.
  However: (a) **no `.sf` file in the repo uses braces-mode `;`** (grep finds
  zero occurrences), and (b) braces-mode `;` has never worked (lexer couldn't
  produce it). Decision: **proceed; braces-mode `;` separators remain
  unsupported** as they are today. If braces-mode is ever needed, it requires
  separate grammar work (a constraint-aware `seq_parser` or distinct tokens).
- **`_create_token` handler is mandatory**: without it, the `SEQ` token is
  silently dropped by the `else` branch (`lexer.py:414-416`) and the parser
  never sees `;`. This is the highest-risk omission in the original plan.

## Files

| File | Action | Change |
|---|---|---|
| `systemf/src/systemf/surface/parser/lexer.py` | edit | Add `("SEQ", r";")` to `TOKEN_PATTERNS` (operators block, ~`:133`); **add `SEQ` handler in `_create_token` returning `SemicolonToken`** (~`:414`, else branch); import `SemicolonToken` from `surface/types` |
| `systemf/src/systemf/surface/parser/expressions.py` | edit | Import `SemicolonToken`; define `SEQ = match_token(SemicolonToken)` (~`:183`); add `seq_parser` (after `:708`); rebase `op_parser` (`:711`) onto `seq_parser` |
| `systemf/tests/…` | add | Parser test: `a ; b ; c` parses left-associative; eval test confirming `;` sequences two effects (CBV forces the first) |

## Verification

1. `uv run bub sf-check test -L .` on a `test.sf` using `effect1 ; effect2` → `OK`.
2. Fix `main.sf`'s `with_compact` back to the `;` form → typechecks.
3. New unit tests: parse associativity; eval sequencing (assert first effect runs).

## References

- `changes/59-steering-message-support.md` — where `main.sf`'s `with_compact` (`;` form) originates
- `bub_sf/src/bub_sf/bub.sf` — `compact` uses the `(\_unit -> e2) e1` workaround that `;` replaces
