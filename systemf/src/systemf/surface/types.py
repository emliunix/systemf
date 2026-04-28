"""Surface language AST for System F.

Surface syntax uses name-based binding (not de Bruijn indices) and allows
omitting type annotations where they can be inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from systemf.utils.location import Location


# =============================================================================
# Surface Node Base Class
# =============================================================================


@dataclass(frozen=True, kw_only=True)
class SurfaceNode:
    """Base class for all surface AST nodes."""

    location: Location | None = None


# =============================================================================
# Surface Types
# =============================================================================


@dataclass(frozen=True, kw_only=True)
class SurfaceType(SurfaceNode):
    """Base class for surface types."""

    docstring: str | None = None


@dataclass(frozen=True, kw_only=True)
class SurfaceTypeVar(SurfaceType):
    """Type variable: a."""

    name: str

    @override
    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, kw_only=True)
class SurfaceTypeArrow(SurfaceType):
    """Function type: arg -> ret.

    Parameter documentation is stored on the ``arg`` type node's
    ``docstring`` field (inherited from ``SurfaceType``).

    Example:
        String -- ^ Input text -> String

    Representation:
        SurfaceTypeArrow(
            arg=SurfaceTypeConstructor(name="String", docstring="Input text"),
            ret=SurfaceTypeConstructor(name="String"),
            location=loc
        )
    """

    arg: SurfaceType
    ret: SurfaceType

    @override
    def __str__(self) -> str:
        match self.arg:
            case SurfaceTypeArrow():
                arg_str = f"({self.arg})"
            case _:
                arg_str = str(self.arg)
        # Pull param doc from arg node's docstring field
        param_doc = self.arg.docstring
        doc_suffix = f" -- ^ {param_doc}" if param_doc else ""
        return f"{arg_str}{doc_suffix} -> {self.ret}"


@dataclass(frozen=True, kw_only=True)
class SurfaceTypeForall(SurfaceType):
    """Polymorphic type: forall a b c. body."""

    vars: list[str]
    body: SurfaceType

    @override
    def __str__(self) -> str:
        return f"forall {' '.join(self.vars)}. {self.body}"


@dataclass(frozen=True, kw_only=True)
class SurfaceTypeConstructor(SurfaceType):
    """Data type constructor: T t1 ... tn."""

    name: str
    args: list[SurfaceType]

    @override
    def __str__(self) -> str:
        if not self.args:
            return self.name
        args_strs = []
        for arg in self.args:
            match arg:
                case SurfaceTypeArrow() | SurfaceTypeForall():
                    args_strs.append(f"({arg})")
                case _:
                    args_strs.append(str(arg))
        args_str = " ".join(args_strs)
        return f"{self.name} {args_str}"


@dataclass(frozen=True, kw_only=True)
class SurfaceTypeTuple(SurfaceType):
    """Tuple type: (t1, t2, ..., tn) - desugars to nested Pairs.

    Sugar for: Pair t1 (Pair t2 (... tn))
    """

    elements: list[SurfaceType]

    @override
    def __str__(self) -> str:
        elems_str = ", ".join(str(e) for e in self.elements)
        return f"({elems_str})"


type SurfaceTypeRepr = SurfaceTypeVar | SurfaceTypeArrow | SurfaceTypeForall | SurfaceTypeConstructor | SurfaceTypeTuple


# =============================================================================
# Surface Terms
# =============================================================================


class SurfaceTerm(SurfaceNode):
    """Base class for surface terms."""

    pass


@dataclass(frozen=True, kw_only=True)
class SurfaceVar(SurfaceTerm):
    """Variable reference by name: x."""

    name: str

    @override
    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, kw_only=True)
class SurfaceAbs(SurfaceTerm):
    r"""Lambda abstraction: \x -> body or \x:T -> body.

    Supports multiple parameters: \x y z -> body (desugared to nested lambdas)
    """

    # Multi-param support: list of (name, type) pairs
    # For single param, use params=[(name, type)]
    params: list[tuple[str, SurfaceType | None]]
    body: SurfaceTerm

    # Backwards compatibility properties
    @property
    def var(self) -> str:
        """First parameter name (backwards compatibility)."""
        return self.params[0][0] if self.params else ""

    @property
    def var_type(self) -> SurfaceType | None:
        """First parameter type (backwards compatibility)."""
        return self.params[0][1] if self.params else None

    def __init__(
        self,
        params: list[tuple[str, SurfaceType | None]] | None = None,
        body: SurfaceTerm | None = None,
        location: Location | None = None,
        # Backwards compatibility kwargs
        var: str | None = None,
        var_type: SurfaceType | None = None,
    ):
        """Initialize with backwards compatibility for old API.

        Old API: SurfaceAbs(var="x", var_type=Int, body=..., location=...)
        New API: SurfaceAbs(params=[("x", Int)], body=..., location=...)
        """
        # Handle old API: if var is provided, build params from it
        if var is not None:
            params = [(var, var_type)]
        elif params is None:
            params = []

        # Use object.__setattr__ since dataclass is frozen
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "location", location)

    @override
    def __str__(self) -> str:
        if not self.params:
            return f"\\ -> {self.body}"
        params_str = " ".join(f"{name}:{ty}" if ty else name for name, ty in self.params)
        return f"\\{params_str} -> {self.body}"


@dataclass(frozen=True, kw_only=True)
class SurfaceApp(SurfaceTerm):
    """Function application: f arg."""

    func: SurfaceTerm
    arg: SurfaceTerm

    @override
    def __str__(self) -> str:
        return f"({self.func} {self.arg})"


@dataclass(frozen=True, kw_only=True)
class SurfaceTypeApp(SurfaceTerm):
    """Type application: func @type or func [type]."""

    func: SurfaceTerm
    type_arg: SurfaceType

    @override
    def __str__(self) -> str:
        return f"({self.func} @{self.type_arg})"


@dataclass(frozen=True, kw_only=True)
class ValBind(SurfaceNode):
    """Single value binding in a let expression.

    Represents one binding: name : type = value
    Used within SurfaceLet for both surface and scoped representations.

    Attributes:
        name: Variable name being bound
        type_ann: Optional type annotation
        value: The bound expression
    """

    name: str
    type_ann: SurfaceType | None
    value: SurfaceTerm

    @override
    def __str__(self) -> str:
        type_part = f" : {self.type_ann}" if self.type_ann else ""
        return f"{self.name}{type_part} = {self.value}"


@dataclass(frozen=True, kw_only=True)
class SurfaceLet(SurfaceTerm):
    """Local let binding with support for recursive groups.

    Syntax:
        let x : Int = 42 in x + 1
        let
          x = 1
          y = 2
        in x + y

    All bindings in a SurfaceLet are mutually recursive - they can all reference
    each other. This is detected via SCC analysis in the scope checking phase.

    Note: type annotation is optional for locals since they can be inferred.
    """

    bindings: list[ValBind]
    body: SurfaceTerm

    @override
    def __str__(self) -> str:
        if len(self.bindings) == 1:
            return f"let {self.bindings[0]} in {self.body}"
        else:
            bindings_str = "\n".join(f"  {b}" for b in self.bindings)
            return f"let\n{bindings_str}\nin {self.body}"


@dataclass(frozen=True, kw_only=True)
class SurfaceAnn(SurfaceTerm):
    """Type annotation: term : type."""

    term: SurfaceTerm
    type: SurfaceType

    @override
    def __str__(self) -> str:
        return f"({self.term} : {self.type})"


@dataclass(frozen=True, kw_only=True)
class SurfaceIf(SurfaceTerm):
    """Conditional expression: if cond then t else f.

    Syntactic sugar for: case cond of True -> t | False -> f
    """

    cond: SurfaceTerm
    then_branch: SurfaceTerm
    else_branch: SurfaceTerm

    @override
    def __str__(self) -> str:
        return f"if {self.cond} then {self.then_branch} else {self.else_branch}"


@dataclass(frozen=True, kw_only=True)
class SurfaceLit(SurfaceTerm):
    """Primitive literal: Int, String, Float, etc.

    Unified representation for all primitive literals.
    The prim_type field indicates the primitive type ("Int", "String", etc.).

    Attributes:
        prim_type: The primitive type name (e.g., "Int", "String")
        value: The literal value (int, str, float, etc.)
    """

    prim_type: str
    value: object

    @override
    def __str__(self) -> str:
        if self.prim_type == "String":
            return f'"{self.value}"'
        return str(self.value)


@dataclass(frozen=True, kw_only=True)
class GlobalVar(SurfaceTerm):
    """Global variable reference by name (after scope checking).

    Replaces SurfaceVar for global variables during scope checking.
    Unlike ScopedVar which uses de Bruijn indices for local variables,
    GlobalVar keeps the name and is resolved from TypeContext.globals.

    Attributes:
        name: Global variable name
    """

    name: str

    @override
    def __str__(self) -> str:
        return f"@{self.name}"


@dataclass(frozen=True, kw_only=True)
class SurfaceOp(SurfaceTerm):
    """Infix operator expression: left op right.

    This is a surface syntax construct that gets desugared to a primitive
    operation application. Operators include +, -, *, /, ==, <, >, <=, >=.
    """

    left: SurfaceTerm
    op: str  # The operator symbol: '+', '-', '*', '/', '==', '<', '>', '<=', '>='
    right: SurfaceTerm

    @override
    def __str__(self) -> str:
        return f"({self.left} {self.op} {self.right})"


@dataclass(frozen=True, kw_only=True)
class SurfaceTuple(SurfaceTerm):
    """Tuple expression: (e1, e2, ..., en) - desugars to nested Pairs.

    Sugar for: Pair e1 (Pair e2 (... en))
    """

    elements: list[SurfaceTerm]

    @override
    def __str__(self) -> str:
        elems_str = ", ".join(str(e) for e in self.elements)
        return f"({elems_str})"


class SurfacePatternBase(SurfaceNode):
    """Base class for all surface patterns."""

    pass


@dataclass(frozen=True, kw_only=True)
class SurfaceVarPattern(SurfacePatternBase):
    """Variable pattern (or potential constructor name before rename): x."""

    name: str

    @override
    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, kw_only=True)
class SurfaceWildcardPattern(SurfacePatternBase):
    """Wildcard pattern: _ — matches anything, binds no variable."""

    pass

    @override
    def __str__(self) -> str:
        return "_"


@dataclass(frozen=True, kw_only=True)
class SurfacePattern(SurfacePatternBase):
    """Flat pattern list: [Con, arg1, arg2, ...] or [var].

    All identifiers are SurfaceVarPattern at parse time.
    Rename phase disambiguates:
    - [VarPat("x")] -> single item: var or nullary con
    - [VarPat("Cons"), VarPat("x"), ...] -> multi item: constructor pattern
    """

    patterns: list[SurfacePatternBase]

    @override
    def __str__(self) -> str:
        return ' '.join(str(p) for p in self.patterns)


@dataclass(frozen=True, kw_only=True)
class SurfacePatternTuple(SurfacePatternBase):
    """Tuple pattern: (p1, p2, ..., pn) - desugars to nested Pairs.

    Sugar for: Pair p1 (Pair p2 (... pn))
    """

    elements: list[SurfacePatternBase]

    @override
    def __str__(self) -> str:
        elems_str = ", ".join(str(e) for e in self.elements)
        return f"({elems_str})"


@dataclass(frozen=True, kw_only=True)
class SurfacePatternCons(SurfacePatternBase):
    """Cons pattern: head : tail - desugars to Cons head tail.

    Sugar for: Cons head tail
    Right-associative: x : y : zs parses as x : (y : zs)
    """

    head: SurfacePatternBase
    tail: SurfacePatternBase

    @override
    def __str__(self) -> str:
        return f"{self.head} : {self.tail}"


@dataclass(frozen=True, kw_only=True)
class SurfaceLitPattern(SurfacePatternBase):
    """Literal pattern: 42, \"hello\"."""

    prim_type: str
    value: object

    @override
    def __str__(self) -> str:
        if self.prim_type == "String":
            return f'"{self.value}"'
        return str(self.value)


@dataclass(frozen=True, kw_only=True)
class SurfaceBranch(SurfaceNode):
    """Case branch: pattern -> body."""

    pattern: SurfacePatternBase
    body: SurfaceTerm

    @override
    def __str__(self) -> str:
        return f"{self.pattern} -> {self.body}"


@dataclass(frozen=True, kw_only=True)
class SurfaceCase(SurfaceTerm):
    """Pattern matching: case scrutinee of branches."""

    scrutinee: SurfaceTerm
    branches: list[SurfaceBranch]

    @override
    def __str__(self) -> str:
        branches_str = " | ".join(str(branch) for branch in self.branches)
        return f"case {self.scrutinee} of {{ {branches_str} }}"


type SurfaceTermRepr = (
    SurfaceVar |
    SurfaceAbs |
    SurfaceApp |
    SurfaceTypeApp |
    SurfaceLet |
    SurfaceAnn |
    SurfaceCase |
    SurfaceLit |
    GlobalVar |
    SurfaceOp )


# =============================================================================
# Surface Pragmas
# =============================================================================


@dataclass(frozen=True, kw_only=True)
class SurfacePragma(SurfaceNode):
    """Pragma annotation: {-# LLM raw_content #-}.

    Simplified storage - just keeps the raw string after the directive.
    Key=value parsing happens in later passes if needed.
    """

    directive: str  # e.g., "LLM"
    raw_content: str  # Raw string content after directive (e.g., "model=gpt-4 temperature=0.7")

    @override
    def __str__(self) -> str:
        return "{-# " + self.directive + " " + self.raw_content + " #-}"


# =============================================================================
# Surface Declarations
# =============================================================================


class SurfaceDeclaration(SurfaceNode):
    """Base class for surface declarations."""

    pass


@dataclass(frozen=True, kw_only=True)
class SurfaceConstructorInfo(SurfaceNode):
    """Data constructor with optional docstring."""

    name: str
    args: list[SurfaceType]
    docstring: str | None


@dataclass(frozen=True, kw_only=True)
class SurfaceDataDeclaration(SurfaceDeclaration):
    """Data type declaration: data Name params = Con1 args1 | Con2 args2 | ..."""

    name: str
    params: list[SurfaceTypeVar]
    constructors: list[SurfaceConstructorInfo]
    docstring: str | None
    pragma: dict[str, str] | None

    @override
    def __str__(self) -> str:
        params_str = " ".join(p.name for p in self.params) if self.params else ""
        constrs_str = " | ".join(
            f"{c.name} {' '.join(str(t) for t in c.args)}" for c in self.constructors
        )
        return f"data {self.name} {params_str} = {constrs_str}"


@dataclass(frozen=True, kw_only=True)
class SurfaceTermDeclaration(SurfaceDeclaration):
    """Named term declaration at module level.

    Syntax:
        -- | Function description
        func : Type -- ^ param -> Type
        func = \\x -> body

    Or with pragma:
        {-# LLM model=gpt-4 #-}
        -- | Translate text
        prim_op func : Type -- ^ param -> Type
    """

    name: str
    type_annotation: SurfaceType | None
    body: SurfaceTerm
    docstring: str | None
    pragma: dict[str, str] | None

    @override
    def __str__(self) -> str:
        return f"{self.name} : {self.type_annotation} = {self.body}"


@dataclass(frozen=True, kw_only=True)
class SurfacePrimTypeDecl(SurfaceDeclaration):
    """Primitive type declaration: prim_type Name [params].

    Declares a primitive type in the prelude. This registers the type
    name in the primitive_types registry for use by the type checker.

    Example: prim_type Int
             prim_type Ref a
    """

    name: str
    params: list[SurfaceTypeVar]
    docstring: str | None
    pragma: dict[str, str] | None

    @override
    def __str__(self) -> str:
        if self.params:
            return f"prim_type {self.name} {' '.join(p.name for p in self.params)}"
        return f"prim_type {self.name}"


@dataclass(frozen=True, kw_only=True)
class SurfacePrimOpDecl(SurfaceDeclaration):
    """Primitive operation declaration: prim_op name : type.

    Declares a primitive operation with its type signature.
    The name is registered as $prim.name in global_types.

    Example: prim_op int_plus : Int -> Int -> Int

    With pragma for LLM functions:
        {-# LLM model=gpt-4 #-}
        prim_op translate : String -> String
    """

    name: str
    type_annotation: SurfaceType | None
    docstring: str | None
    pragma: dict[str, str] | None

    @override
    def __str__(self) -> str:
        return f"prim_op {self.name} : {self.type_annotation}"


@dataclass(frozen=True, kw_only=True)
class SurfaceImportDeclaration(SurfaceDeclaration):
    """Import declaration: import [qualified] Module [as Alias] [import_spec]."""

    module: str
    qualified: bool = False
    alias: str | None
    items: list[str] | None
    hiding: bool = False

    @override
    def __str__(self) -> str:
        parts = ["import"]
        if self.qualified:
            parts.append("qualified")
        parts.append(self.module)
        if self.alias is not None:
            parts.extend(["as", self.alias])
        if self.items is not None:
            if self.hiding:
                parts.append("hiding")
            items_str = ", ".join(self.items)
            parts.append(f"({items_str})")
        return " ".join(parts)


type SurfaceDeclarationRepr = (
    SurfaceDataDeclaration |
    SurfaceTermDeclaration |
    SurfacePrimTypeDecl |
    SurfacePrimOpDecl |
    SurfaceImportDeclaration )
