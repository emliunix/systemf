---
title: "Parser Indentation Infrastructure"
category: "implementation"
status: "current"
last-updated: "2026-03-09"
description: "Layout-sensitive constraint propagation in the type parser: theory, design, and implementation"
---

# Parser Indentation Infrastructure

This document covers the layout-sensitive indentation constraint system in
the SystemF parser — why it exists, how it works, the theoretical grounding
from Idris2, the design decisions, and the final implementation record.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Theoretical Foundation: Idris2](#2-theoretical-foundation-idris2)
3. [Existing Infrastructure in SystemF](#3-existing-infrastructure-in-systemf)
4. [Architecture: How Constraints Flow](#4-architecture-how-constraints-flow)
5. [Type Parser Design](#5-type-parser-design)
6. [Implementation Record](#6-implementation-record)
7. [Files Changed](#7-files-changed)
8. [Invariants](#8-invariants)

---

## 1. The Problem

### 1.1 Bug Description

The SystemF type parser (`type_parser.py`) had no boundary awareness.
`type_app_parser` called `type_atom_parser().optional()` in an unconstrainted
loop, so it never stopped at declaration boundaries — it would greedily consume
identifiers from the *next* declaration into the current type.

Concretely, given:

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
prim_op int_ge :: Int -> Int -> Bool

-- Bool primitives
bool_and :: Bool -> Bool -> Bool = \b -> case b of
```

The parser produced `Int -> Int -> Bool bool_and` instead of `Int -> Int -> Bool`.
The parsed type structure was:

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
SurfaceTypeConstructor(name='Bool', args=[SurfaceTypeVar(name='bool_and')])
```

### 1.2 Root Cause

`prim_op_parser` called `type_parser()` with no constraint, defaulting to
`AnyIndent()`. In `type_app_parser`, the boundary-check branch begins with:

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
if not isinstance(constraint, AnyIndent):
    ...  # check skipped entirely
```

So with `AnyIndent()` the check was always skipped and the loop ran until it
simply failed to find another type atom — by which point it had consumed tokens
from the next declaration.

A secondary structural issue was that `type_forall_parser` was a zero-argument
`@generate` Parser object and could not accept or propagate any constraint.
For `prim_op foo :: forall a. a -> a` the constraint would be silently dropped
at the `forall` branch.

### 1.3 Initial Exploratory Approach (Superseded)

The first fix attempt added a heuristic function `_is_at_declaration_boundary()`
that inspected lookahead tokens for patterns like `ident ::` or `ident =` and
recognised declaration keywords. This worked for the immediate case but was
fragile: it duplicated logic the parser already encoded structurally, relied on
multi-token lookahead, and did not compose with the existing `ValidIndent`
infrastructure. The proper fix — described in the rest of this document — uses
the existing constraint machinery instead.

---

## 2. Theoretical Foundation: Idris2

The correct approach mirrors Idris2's layout-sensitive parsing. The key source
anchors:

| File | Lines | What it shows |
|------|-------|---------------|
| `src/Parser/Rule/Source.idr` | L466–467 | `IndentInfo = Int` — the constraint is just a column integer |
| `src/Parser/Rule/Source.idr` | L473–484 | `continueF` / `continue` — boundary check as an `EmptyRule ()` |
| `src/Parser/Rule/Source.idr` | L494–514 | `ValidIndent` ADT and `checkValid` |
| `src/Parser/Rule/Source.idr` | L596–604 | `blockEntry` — where `IndentInfo` is **captured** and **injected** |
| `src/Parser/Rule/Source.idr` | L605–616 | `blockEntries` / `block` — iteration via `blockEntry` failure |
| `src/TTImp/Parser.idr`       | L181–188 | `argExpr` — `continue indents` is the **first combinator** |
| `src/TTImp/Parser.idr`       | L476–495 | `typeExpr` — `continue indents` guards application **and** arrow |
| `src/Idris/Parser.idr`       | L224–266 | Full `appExpr` / `argExpr` — `many (argExpr fname indents)` |

### 2.1 Key Concepts

**`IndentInfo`** — a plain `Int` representing the column of the enclosing block
item. This is *not* the column of any sub-expression token; it is the column of
the declaration or branch that opened the current layout scope.

**`ValidIndent`** — an ADT (`AnyIndent | AtPos Int | AfterPos Int | EndOfBlock`)
used by `blockEntry` to decide whether the next item in a block is at a legal
column. It is a block-level concept.

**`continue indent`** — an `EmptyRule ()` that succeeds silently when the next
token's column is strictly greater than `indent`, and fails *non-consumingly*
otherwise (also fails at EOF or `where`). Non-consuming failure is essential:
when `continue` fails inside `many` or `optional`, those combinators yield
their zero/nothing result cleanly without backtracking cost.

**`argExpr`** — the per-argument parser. Its *first action* is `continue
indents`. The constraint check is structurally part of the argument parser,
not an external guard.

**`many (argExpr fname indents)`** — the application loop. `many` stops
naturally when `argExpr` fails (i.e., when `continue` fails at a boundary).

**`blockEntry valid rule`** — the combinator that ties block structure to
expression parsing. It captures `col = column`, validates `col` against `valid`,
then calls `rule col`, passing the column forward as `IndentInfo`. This is the
**only place** where `IndentInfo` is determined.

**Constraint reset at parens** — when `(` is encountered, the inner parser is
invoked with a fresh unconstrained context. Parentheses are a syntactic boundary
that overrides layout.

**`AfterPos(col = decl_col + 1)`** — the SystemF equivalent of Idris2's
`continue decl_col`. `check_valid(AfterPos(c), col)` is `col >= c`, so
`AfterPos(decl_col + 1)` accepts `col > decl_col`, matching exactly the
semantics of `continue decl_col` which fails when `col <= decl_col`.

### 2.2 The Structural Pattern

In Idris2, `blockEntry` is the single canonical source of `IndentInfo`. It
captures the column of the first token of a block item and passes that integer
to the rule function:

```
blockEntry valid rule =
    col  <- column          -- peek, no consume
    checkValid valid col    -- is this item at a legal column?
    p    <- rule col        -- rule receives its own column as IndentInfo
    ...
```

In SystemF, `top_decl_parser` uses `entry.many()` without a `block` combinator,
so declaration parsers receive no such column injection. The equivalent recovery
is: each declaration parser reads its own keyword token's column from the
already-consumed token (e.g. `prim_token.location.column`).

The structural correspondence between Idris2 and SystemF:

```
-- Idris2
argExpr fname indents =
    do continue indents       -- boundary check (non-consuming, fails cleanly)
       arg <- simpleExpr ...

appExpr fname indents =
    do f    <- simpleExpr ...
       args <- many (argExpr fname indents)

typeExpr fname indents =
    do arg <- appExpr fname indents
       optional (do continue indents   -- boundary check before arrow too
                    bd  <- bindSymbol
                    rhs <- typeExpr fname indents
                    ...)
```

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
# SystemF equivalent
def type_app_parser(constraint):     # appExpr
    first = yield type_atom_parser(constraint)
    args = []
    while True:
        if not isinstance(constraint, AnyIndent):
            next_col = yield peek_column()
            if next_col == 0 or not check_valid(constraint, next_col):
                break
        arg = yield type_atom_parser(constraint).optional()
        if arg is None:
            break
        args.append(arg)

def type_arrow_parser(constraint):   # typeExpr
    left = yield type_app_parser(constraint)
    if not isinstance(constraint, AnyIndent):
        next_col = yield peek_column()
        if next_col == 0 or not check_valid(constraint, next_col):
            return left
    arrow = yield match_token(ArrowToken).optional()
    if arrow is None:
        return left
    right = yield type_arrow_parser(constraint)
    ...
```

---

## 3. Existing Infrastructure in SystemF

All relevant building blocks were already present in `helpers.py` and correctly
used by `expressions.py`. Nothing new needed to be invented.

From `helpers.py`:

```systemf/src/systemf/surface/parser/helpers.py#L1-1
ValidIndent = AnyIndent | AtPos | AfterPos | EndOfBlock

def check_valid(constraint: ValidIndent, col: int) -> bool
def column() -> P[int]        # captures current token column (does NOT consume)
def peek_column() -> P[int]   # peeks at next token column, returns 0 at EOF
```

From `expressions.py` — the reference implementation:

```systemf/src/systemf/surface/parser/expressions.py#L1-1
def app_parser(constraint: ValidIndent) -> P[SurfaceTerm]:
    first = yield atom_parser(constraint)
    while True:
        if not isinstance(constraint, AnyIndent):
            next_col = yield peek_column()
            if next_col > 0 and not check_valid(constraint, next_col):
                break
        arg = yield atom_parser(constraint).optional()
        if arg is None:
            break
        args.append(arg)

def paren_parser():
    yield match_token(LeftParenToken)
    expr = yield expr_parser(AnyIndent())  # resets constraint inside parens
    yield match_token(RightParenToken)
```

The type parser needed to mirror this pattern exactly.

---

## 4. Architecture: How Constraints Flow

### 4.1 Type Parser Hierarchy

```
type_parser(constraint)
├── type_forall_parser(constraint)
│   └── type_parser(constraint)              ← body propagates constraint
└── type_arrow_parser(constraint)
    ├── [peek_column + check_valid guard]     ← before consuming arrow
    ├── type_app_parser(constraint)           ← CONSTRAINT CHECK LEVEL
    │   └── type_atom_parser(constraint)      ← PASS-THROUGH LEVEL
    │       ├── type_parser(AnyIndent())      ← RESET IN PARENS
    │       └── type_tuple_parser()           ← ALWAYS AnyIndent internally
    └── type_arrow_parser(constraint)         ← recursive right side
```

### 4.2 Where the Constraint Is Determined

`prim_op_parser` recovers the declaration column from the token it has already
parsed:

```systemf/src/systemf/surface/parser/declarations.py#L1-1
prim_token = yield match_keyword("prim_op")
decl_col   = prim_token.location.column      # e.g. 1 at top level
...
yield match_symbol("::")
ty = yield type_parser(AfterPos(col=decl_col + 1))
# AfterPos(col=2) accepts col >= 2, rejects col=1 (next declaration)
```

`term_parser` uses the same pattern for both its type annotation and its body:

```systemf/src/systemf/surface/parser/declarations.py#L1-1
decl_col = name_token.location.column
ty   = yield type_parser(AfterPos(col=decl_col + 1))
yield match_symbol("=")
body = yield _expr_parser_factory(AfterPos(col=decl_col + 1))
```

Using `decl_col` uniformly (not `body_col` derived from the first body token)
is the principled approach: any token at `column <= decl_col` belongs to the
next declaration, whether inside the type or the body. This matches Idris2's
`blockEntry` semantics.

### 4.3 Where the Constraint Is Used

The constraint is used at exactly one kind of decision point: **before consuming
an optional continuation**. Specifically:

- In `type_app_parser`: before consuming the next type argument atom
- In `type_arrow_parser`: before consuming the `->` token

### 4.4 What Does NOT Need a Constraint Check

- `type_atom_parser`: the caller (`type_app_parser`) already checked the
  constraint via `peek_column()` before deciding to call `type_atom_parser`.
  The atom parser does not re-check. This mirrors `atom_parser` in
  `expressions.py`.
- The `->` token match itself: only the *decision* to look for an arrow needs
  the check.
- `type_tuple_parser`: tuples are always inside `(...)`. Constraint is already
  reset to `AnyIndent` inside parens.

### 4.5 Constraint Reset at Parentheses

Parentheses are a strong syntactic boundary. Once inside `(...)`, indentation
rules no longer apply — the closing `)` is the boundary, not column position.

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
func :: (Int
         -> Bool)   -- OK: inside parens, any indentation
     -> String
```

Reset is done by passing `AnyIndent()` explicitly when recursing into
`type_parser` from `type_atom_parser` for parenthesized types.

The internal `_type_parser` forward declaration (used by `type_tuple_parser`
and inside `type_atom_parser` for paren branches) stays as
`_type_parser.become(type_parser(AnyIndent()))` — recursive internal uses
always occur inside parens or similar scopes where constraint has been reset.

### 4.6 Constraint Propagation on the Arrow Right-Hand Side

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
right = yield type_arrow_parser(constraint)  # propagate, do not reset
```

The constraint propagates through the arrow right-hand side. This means a
multi-arrow type like `A -> B -> C` stays within the boundary established by
the declaration. Resetting to `AnyIndent()` on the right side of `->` would
allow consuming tokens from the next line inside a type — incorrect.

The `forall` body also propagates the constraint, enabling:

```systemf/prelude.sf#L1-1
prim_op error :: forall a.
    String -> a        -- continuation: must be indented past decl name
next_decl :: ...       -- stop here
```

---

## 5. Type Parser Design

### 5.1 Function Signatures

Following the expression parser convention (`expressions.py`):

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
# Application level — has the constraint loop (mirrors app_parser)
def type_app_parser(constraint: ValidIndent = AnyIndent()) -> P[SurfaceType]

# Pass-through levels — accept and forward constraint
def type_atom_parser(constraint: ValidIndent = AnyIndent()) -> P[SurfaceType]
def type_arrow_parser(constraint: ValidIndent = AnyIndent()) -> P[SurfaceType]
def type_forall_parser(constraint: ValidIndent = AnyIndent()) -> P[SurfaceType]
def type_parser(constraint: ValidIndent = AnyIndent()) -> P[SurfaceType]

# Base level — no constraint, always resets internally
def type_tuple_parser() -> P[SurfaceType]
```

### 5.2 Default Argument: `AnyIndent()` not `None`

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
# CORRECT: AnyIndent() as default is safe and expressive
def type_app_parser(constraint: ValidIndent = AnyIndent()) -> P[SurfaceType]:
    ...

# AVOID: None-check boilerplate inside every function
def type_app_parser(constraint: ValidIndent | None = None) -> P[SurfaceType]:
    if constraint is None:
        constraint = AnyIndent()  # noise
```

`AnyIndent()` is a dataclass (value type) so the default is safe. No
boilerplate needed inside the function body. Calling `type_parser()` with no
args behaves identically to the previous zero-argument `@generate` parser
objects.

### 5.3 Factory Function Pattern

All type parser functions use the factory pattern already used by `app_parser`
in `expressions.py` — a plain function with a nested zero-argument `@generate`:

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
def type_app_parser(constraint: ValidIndent = AnyIndent()) -> P[SurfaceType]:
    @generate
    def parser():
        first = yield type_atom_parser(constraint)
        args = []
        while True:
            if not isinstance(constraint, AnyIndent):
                next_col = yield peek_column()
                if next_col == 0 or not check_valid(constraint, next_col):
                    break
            arg = yield type_atom_parser(constraint).optional()
            if arg is None:
                break
            args.append(arg)
        ...
    return parser
```

The nested `@generate` generator body closes over `constraint`. **Do not apply
`@generate` directly to a function with default parameters** — parsy calls the
function at decoration time (ignoring the default), producing a Parser object
that crashes with a `TypeError` when later called with an argument.

---

## 6. Implementation Record

### 6.1 Completed Items

#### ✅ `prim_op_parser`: constraint injection

`prim_token.location.column` is read and passed as `AfterPos(col=decl_col + 1)`
into `type_parser`. This is the minimal fix for the original bug.

#### ✅ Imperative loop in `type_app_parser`

The existing loop structure was kept (consistent with `app_parser` in
`expressions.py`). The loop now uses `peek_column()` — which returns `0` at
EOF — replacing the old `column()` + separate `peek(eof).optional()` guard.
The single check `next_col == 0 or not check_valid(constraint, next_col)`
handles EOF and layout boundary in one condition.

#### ✅ Constraint check before `->` in `type_arrow_parser`

Before attempting `match_token(ArrowToken)`, the arrow parser peeks the column
and returns early if the constraint is not satisfied. This mirrors Idris2's
`continue indents` guard in `typeExpr` (TTImp L476–495).

#### ✅ `type_forall_parser` refactored to factory function

`type_forall_parser` was a zero-argument `@generate` Parser object. It is now a
factory function that accepts and propagates `constraint`. `type_parser` calls
`type_forall_parser(constraint)` instead of the bare Parser object.

#### ✅ `peek_column` moved to `helpers.py`

`peek_column()` was defined locally in `expressions.py`. It now lives in
`helpers.py` and is exported in `__all__`. Both `expressions.py` and
`type_parser.py` import it from there.

#### ✅ Dead code removed

Removed from `type_parser.py`:
- `_is_at_declaration_boundary` — ad-hoc heuristic, superseded by column constraints
- `type_app_parser_with_constraint` — identical to the refactored `type_app_parser`
- `type_arrow_parser_with_constraint` — same
- `type_parser_with_constraint` — same

`__all__` updated accordingly.

#### ✅ `term_parser` also uses the constraint

`term_parser` has `=` as an explicit type terminator, so greedy consumption of
a next-declaration identifier causes a parse failure at `match_symbol("=")`.
However, without the constraint the failure position is confusing — a
next-declaration identifier is consumed as a type variable, giving the wrong
type before the error. With the constraint, the type stops cleanly and
`match_symbol("=")` reports a clear, immediate failure.

The `=` terminator and the column constraint are **orthogonal, not conflicting**:
`=` terminates valid types; the column constraint prevents greedy consumption of
tokens belonging to the next declaration.

#### ✅ Declaration name column governs both annotation and body

`term_parser` previously derived `body_col` from the first body token:

```systemf/src/systemf/surface/parser/declarations.py#L1-1
body_col = yield column()               # column of first body token
body_constraint = AfterPos(col=body_col - 1)
```

This is fragile: if the first body token is at column 1, `AfterPos(0)` accepts
everything including the next top-level declaration.

The fix captures `decl_col` once from the name token and uses it for both the
type annotation and the body expression. Any token at `column <= decl_col`
belongs to the next declaration. This matches Idris2's `blockEntry` semantics
exactly.

### 6.2 Structural Fix: `@generate` Applied to Function Bug

The edit buffer during implementation contained a broken attempt applying
`@generate` directly to functions with default parameters:

```systemf/src/systemf/surface/parser/type_parser.py#L1-1
# BROKEN — parsy calls fn() at decoration time, ignoring the default arg.
# The result is a Parser object. Calling it with an argument later invokes
# Parser.__call__(stream, index), crashing with a missing-argument TypeError.
@generate
def type_app_parser(constraint: ValidIndent = None) -> P[SurfaceType]:
    ...
```

This crashed the module at import time (`_type_parser.become(type_parser(AnyIndent()))`)
before any parser could run. The fix was the factory pattern described in §5.3.

### 6.3 Two-Line Declaration Format Is Not Supported

The format:

```systemf/prelude.sf#L1-1
foo :: Int -> Int
foo x = x + 1
```

is not valid for `term_parser`. `term_parser` parses the combined grammar
`name :: type = body`. Two-line format is the responsibility of `top_decl_parser`
to recognise and merge a standalone type-signature item with a following
definition item — not the type parser's job.

Two tests that relied on the broken greedy behaviour to accidentally parse
this format were rewritten to use valid single-declaration syntax:

| Old (relying on bug) | Fixed |
|---|---|
| `foo :: Int -> Int\nfoo x = let y :: Int = x + 1 in y` | `foo :: Int -> Int = \x -> let y :: Int = x + 1 in y` |
| `compute :: Int\ncompute = let x :: Int = 1 in ...` | `compute :: Int = let x :: Int = 1 in let y :: Int = 2 in x + y` |

### 6.4 Remaining Long-Term Work

**Wire `top_decl_parser` through `block`** (not done).

The principled Idris2 approach injects `IndentInfo` via `blockEntry`. In
SystemF, `top_decl_parser` uses `entry.many()` with no block machinery.
Declaration parsers therefore self-recover their block column from their own
first token (the approach used throughout this implementation).

If `top_decl_parser` were refactored to use `block_entries`, declaration parsers
would receive their column as a parameter rather than reading it from an
already-parsed token. This matches the Idris2 architecture exactly but requires
changing the signature of all declaration parsers. Not required for the bug fix;
noted here as the structurally correct long-term direction.

---

## 7. Files Changed

| File | Change |
|------|--------|
| `src/systemf/surface/parser/helpers.py` | Added `peek_column()`, exported in `__all__` |
| `src/systemf/surface/parser/expressions.py` | Removed local `peek_column`, imports from `helpers` |
| `src/systemf/surface/parser/type_parser.py` | Full structural refactor: factory functions, constraint propagation throughout, dead code removed |
| `src/systemf/surface/parser/declarations.py` | `prim_op_parser` and `term_parser` pass `AfterPos(decl_col + 1)` for type and body; removed `body_col` derivation |
| `tests/test_surface/test_parser/test_declarations.py` | Fixed two tests that relied on greedy-parsing bug |

### Files NOT Changed

| File | Reason |
|------|--------|
| `helpers.py` (pre-existing infra) | Existing `ValidIndent`, `check_valid`, `column` are correct and complete |
| `expressions.py` (application loop) | Already correct; served as the reference pattern |
| `builtins.sf` | Source file is correct; the bug was in the parser |

---

## 8. Invariants

The following must hold after any future modification to the type parser:

1. `type_parser()` with no args behaves identically to the original zero-argument parser
2. `type_app_parser()` with no args behaves identically to the original
3. `List Int`, `Maybe a`, `Pair String Bool` parse as type applications
4. `(Int -> Bool)` inside parens always resets constraint to `AnyIndent`
5. `forall a. a -> a` parses as a single type regardless of context
6. Consecutive `prim_op` declarations parse independently with correct types
7. All existing parser tests pass
8. `peek_column()` (not `column()`) is used for boundary checks — it returns `0` at EOF rather than failing