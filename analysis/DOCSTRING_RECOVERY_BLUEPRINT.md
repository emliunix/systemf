# Docstring and Pragma Recovery Blueprint

## Problem Statement

The current surface AST attaches docstrings to declarations (`SurfaceTermDeclaration`, `SurfaceDataDeclaration`, etc.), but this is insufficient. Docstrings for function parameters and return types need to be attached to the actual type nodes within the type tree.

## Proposed Solution: Docstring Wrapping Precedence Model

### Precedence Hierarchy (tightest → loosest)

| Level | Construct | Associativity | Combinator |
|-------|-----------|---------------|------------|
| 5 | Atoms (`a`, `Int`, `(T)`, `(T,U)`) | — | `type_atom` |
| 4 | Type application (`F a b`) | left | `type_app = type_atom (many type_atom)` |
| 3 | Docstring wrapping (`--^ doc`) | — | `doc_type = many inlineDoc *> type_app <* many inlineDoc` |
| 2 | Arrow (`a -> b`) | right | `type_arrow = chainr1 doc_type arrowOp` |
| 1 | Forall (`forall a. T`) | — | `type_forall = forall >> ids >> dot >> type_parser` |

### Combinator Design (Haskell-style pseudocode)

```haskell
-- Entry point: forall binds loosest, arrow next
typeParser :: Parser SurfaceType
typeParser = typeForall <|> typeArrow

-- Level 1: Forall keyword makes it unambiguous
typeForall :: Parser SurfaceType
typeForall = do
    _ <- matchForall
    vars <- many1 matchIdent
    _ <- matchDot
    body <- typeParser
    return $ mkForall vars body

-- Level 2: Right-associative arrow
typeArrow :: Parser SurfaceType
typeArrow = do
    left  <- docType
    mArrow <- optional matchArrow
    case mArrow of
        Nothing   -> return left
        Just _    -> do
            right <- typeArrow
            return $ SurfaceTypeArrow left right

-- Level 3: Docstrings wrap around type applications
-- Precedence: tighter than arrow, looser than type app
docType :: Parser SurfaceType
docType = do
    pre  <- many matchInlineDocstringStrict
    ty   <- typeApp
    post <- many matchInlineDocstringStrict
    return $ attachDocs ty pre post

-- Level 4: Left-associative type application
typeApp :: Parser SurfaceType
typeApp = do
    head <- typeAtom
    args <- many typeAtom
    return $ if null args then head else mkTypeApp head args

-- Level 5: Atoms (highest precedence)
typeAtom :: Parser SurfaceType
typeAtom = typeVar <|> typeCon <|> parenType <|> tupleType
```

### Key Design Decisions

1. **`matchInlineDocstringStrict`**: Fails on no-match (unlike the current one that returns `None`). Essential for `many` to terminate.

2. **`attachDocs`**: Uses `dataclasses.replace` to set `docstring` field on the parsed type node. Since all surface type nodes are frozen dataclasses, construct them first, then replace the doc field.

3. **`docType` is the same parser used for both arg and res positions** in `typeArrow`. This satisfies: "the 2 sub type parser, well, actually, the same parser".

4. **Right associativity preserved**: `A -> B -> C` parses as `Arrow(A, Arrow(B, C))`, but now `A`, `B`, and `C` can each carry their own `docstring`.

5. **Docstring storage**: Add `docstring: str | None` to `SurfaceType` base class (default `None`). If both pre and post docs exist, concatenate with `\n` separator.

6. **Deprecation**: Remove `param_doc` from `SurfaceTypeArrow` once migration is complete.

## Rationale

Docstrings are relevant only for arguments or return types. By attaching them to type nodes (not arrow nodes), we can document any position in a complex type:

```haskell
-- ^ Configuration object
Config
-- ^ API key for authentication
->
-- ^ Returns user profile or error
Result User String
```

This parses as:
```
Arrow(
  arg=TypeConstructor("Config", docstring="Configuration object"),
  ret=Arrow(
    arg=TypeConstructor("Result", [TypeConstructor("User"), TypeConstructor("String")], 
                        docstring="API key for authentication"),
    ret=TypeConstructor("Result", [...], docstring="Returns user profile or error")
  )
)
```

## Current vs Proposed

| Aspect | Current | Proposed |
|--------|---------|----------|
| Docstring location | `SurfaceTypeArrow.param_doc` | `SurfaceType.docstring` (all nodes) |
| Parser approach | Inline doc between arg and arrow | Wrap any type node with pre/post docs |
| Associativity | Arrow-only | Orthogonal to arrow |
| Return type docs | Not supported | Supported via post-doc on rightmost type |

## Files to Modify

1. `systemf/src/systemf/surface/types.py` — Add `docstring` field to `SurfaceType` base class
2. `systemf/src/systemf/surface/parser/type_parser.py` — Implement `docType` combinator, update `typeArrow`
3. `systemf/src/systemf/surface/parser/declarations.py` — Update type parsing calls
4. `systemf/src/systemf/surface/inference/*` — Update type elaboration to propagate docstrings
5. `systemf/src/systemf/core/types.py` — Add `docstring` field to `Type` base class
6. Tests — Update all `param_doc=None` references

## Status

- **Design**: ✅ Approved (this document)
- **Implementation**: Pending
- **Tests**: Pending
- **Migration from `param_doc`**: Pending

## Related Tasks

See `analysis/ELAB3_PROJECT_STATUS.md` "Recover Pragma and Docstring Passing" for broader context.
