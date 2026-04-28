# Parser Refactor: Context Closure

## Task Overview

Refactor the System F surface parser from the old monolithic `parser.py` to a modular structure using the new helper combinators with explicit constraint passing (Idris2-style).

## Key Constraint: FREEZE helpers.py

The `src/systemf/surface/parser/helpers.py` file is COMPLETE and FROZEN. Do not modify it.
Only create new files in `src/systemf/surface/parser/`:
- `expressions.py` - Expression parsers
- `declarations.py` - Declaration parsers
- Update `__init__.py` - Public exports

## Reference Materials

### 1. Parser Tree Documentation
**Location**: `docs/design/parser-tree.md`

**Key Concepts**:
- Constraint passing: `expr_parser(constraint)` flows constraints through parsers
- Layout-sensitive: `case`, `let`, `where` use `block()` combinator
- Layout-agnostic: atoms, applications, operators ignore constraint
- Pattern: After layout keyword, capture column with `column()`, then use `block_entries(AtPos(col), item_parser)`

### 2. System F Syntax Specification
**Location**: `docs/syntax.md`

**Expressions (Section 3)**:
```
expr      ::= lambda_expr | type_abs_expr | if_expr | case_expr | let_expr | op_expr
lambda_expr ::= "λ" lambda_param+ "→" expr
type_abs_expr ::= "Λ" ident+ "." expr
case_expr   ::= "case" expr "of" case_body
case_body   ::= "{" branch (";" branch)* "}" | layout_branch+
let_expr    ::= "let" let_binding (";" let_binding)* "in" expr
let_binding ::= ident [":" type] "=" expr
```

**Declarations (Section 7)**:
```
decl      ::= data_decl | term_decl | prim_type_decl | prim_op_decl
data_decl ::= "data" CONSTRUCTOR [ident*] "=" constr ("|" constr)*
term_decl ::= ident ":" type "=" expr
prim_type_decl ::= "prim_type" CONSTRUCTOR
prim_op_decl   ::= "prim_op" ident ":" type
```

### 3. Old Parser Implementation
**Location**: `src/systemf/surface/parser.py` (LEGACY - for reference only)

**Key patterns to preserve**:
- Use `@generate` decorator for monadic parsing
- Parser type alias: `P = Parser` from parsy
- Token matching: `match_token(token_type)` and `match_value(token_type, value)`
- Forward declarations for recursive parsers: `parsy.forward_declaration()`
- AST imports from `systemf.surface.types`

**DO NOT COPY**: Old indentation handling (uses INDENT/DEDENT tokens) - new approach uses column checking

### 4. Helper Combinators (FROZEN)
**Location**: `src/systemf/surface/parser/helpers.py`

**Available for use**:
```python
# Core
from systemf.surface.parser.helpers import (
    column,           # Peek current token column
    check_valid,      # Validate column against constraint
    is_at_constraint, # Check exact match
    get_indent_info,  # Extract column from token
)

# Block parsing
from systemf.surface.parser.helpers import (
    block,            # { items } OR layout block
    block_after,      # Block with min column
    block_entries,    # Parse multiple items with constraint
    block_entry,      # Parse single item with constraint
)

# Terminators
from systemf.surface.parser.helpers import (
    terminator,       # Check for block end
    must_continue,    # Verify not EndOfBlock
)

# Types
from systemf.surface.parser.types import (
    ValidIndent, AnyIndent, AtPos, AfterPos, EndOfBlock,
    TokenBase, Location,
)
```

### 5. Idris2 Reference
**Location**: `upstream/idris2/src/Idris/Parser.idr`

**Key patterns**:
```idris
-- Forward declarations for recursive parsers
expr : ParseOpts -> OriginDesc -> IndentInfo -> Rule PTerm

-- Layout block parsing
case_ fname indents = do
    decoratedKeyword fname "case"
    scr <- expr pdef fname indents
    mustWork (commitKeyword fname indents "of")
    alts <- block (caseAlt fname)  -- NEW constraint from block
    pure (PCase ...)

-- Where clause parsing
whereBlock fname col = do
    decoratedKeyword fname "where"
    ds <- blockAfter col (topDecl fname)
    pure (collectDefs ds)
```

## Module Structure

### New Files to Create

1. **`src/systemf/surface/parser/expressions.py`**
   - `atom_parser()` - Variables, literals, constructors, parens
   - `lambda_parser(constraint)` - Lambda expressions
   - `type_abs_parser(constraint)` - Type abstractions
   - `if_parser(constraint)` - If-then-else
   - `case_parser(constraint)` - Case expressions (layout-sensitive)
   - `let_parser(constraint)` - Let expressions (layout-sensitive)
   - `app_parser(constraint)` - Function application
   - `op_parser(constraint)` - Operator expressions
   - `expr_parser(constraint)` - Main expression entry point

2. **`src/systemf/surface/parser/declarations.py`**
   - `data_parser()` - Data declarations
   - `term_parser()` - Term declarations (function definitions)
   - `prim_type_parser()` - Primitive type declarations
   - `prim_op_parser()` - Primitive operation declarations
   - `decl_parser()` - Main declaration entry point

3. **Update `src/systemf/surface/parser/__init__.py`**
   - Export new parsers
   - Maintain backward compatibility

## Implementation Notes

### Constraint Passing Pattern

```python
from systemf.surface.parser.helpers import column, block_entries, AtPos

@generate
def case_parser(constraint: ValidIndent) -> P[SurfaceCase]:
    yield match_keyword("case")
    scrutinee = yield expr_parser(constraint)  # Pass constraint through
    yield match_keyword("of")
    
    # Enter layout mode: capture column of first branch
    col = yield column()  # Peek at first token
    branches = yield block_entries(AtPos(col), case_alt)
    
    return SurfaceCase(scrutinee, branches)
```

### Declaration Pattern (No Constraint)

```python
@generate
def data_parser() -> P[SurfaceDataDeclaration]:
    yield match_keyword("data")
    name = yield match_constructor()
    params = yield many(match_ident())
    yield match_symbol("=")
    constructors = yield sep_by1(constr_parser, match_symbol("|"))
    return SurfaceDataDeclaration(name, params, constructors)
```

### Block with Declarations (for where clauses)

```python
from systemf.surface.parser.helpers import block_after, AfterPos

@generate
def where_block(min_col: int) -> P[List[SurfaceDeclaration]]:
    yield match_keyword("where")
    decls = yield block_after(min_col, decl_parser)
    return decls
```

## Testing

Tests are in `tests/test_surface/test_parser/`:
- `test_helpers.py` - Unit tests for helpers (DONE, PASSING)
- `test_parser_complex.py` - Integration tests

Run tests with:
```bash
cd /home/liu/Documents/bub/systemf
uv run pytest tests/test_surface/test_parser/ -v
```

## Success Criteria

1. All existing tests pass
2. New parsers use helper combinators correctly
3. Constraint flows properly through layout-sensitive parsers
4. No modifications to helpers.py
5. Clean separation: expressions.py vs declarations.py
