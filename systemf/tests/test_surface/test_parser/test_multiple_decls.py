"""Tests for parsing multiple declarations with fixtures.

Uses conftest.py fixtures to test complex multi-declaration programs.
"""

import pytest
from systemf.surface.parser import parse_program, lex
from systemf.surface.types import (
    SurfaceDataDeclaration,
    SurfaceTermDeclaration,
    SurfacePrimTypeDecl,
    SurfacePrimOpDecl,
    SurfacePattern,
    SurfaceBranch,
    SurfaceVarPattern,
    SurfaceAbs,
    SurfaceCase,
    SurfaceVar,
)


class TestMultipleDeclarationsParsing:
    """Test parsing programs with multiple declarations using fixtures."""

    def test_simple_multiple_decls(self, simple_multiple_decls):
        """Parse simple multiple declarations without docstrings."""
        _, result = parse_program(simple_multiple_decls)

        assert result is not None
        assert len(result) == 3

        assert isinstance(result[0], SurfaceDataDeclaration)
        assert result[0].name == "Bool"

        assert isinstance(result[1], SurfaceDataDeclaration)
        assert result[1].name == "Maybe"

        assert isinstance(result[2], SurfaceTermDeclaration)
        assert result[2].name == "not"

    def test_bool_with_tostring(self, bool_with_tostring):
        """Parse Bool type with toString function."""
        _, result = parse_program(bool_with_tostring)

        assert result is not None
        assert len(result) == 2

        # First declaration: Bool data type
        assert isinstance(result[0], SurfaceDataDeclaration)
        assert result[0].name == "Bool"
        assert result[0].docstring == "Boolean type with two values"

        # Second declaration: toString function
        assert isinstance(result[1], SurfaceTermDeclaration)
        assert result[1].name == "toString"
        assert result[1].docstring == 'Convert Bool to String\nReturns "true" or "false"'

    def test_rank2_const_function(self, rank2_const_function):
        """Parse rank-2 polymorphic const function."""
        _, result = parse_program(rank2_const_function)

        assert result is not None
        assert len(result) == 1

        assert isinstance(result[0], SurfaceTermDeclaration)
        assert result[0].name == "const"
        assert "constant function" in result[0].docstring
        assert "rank-2" in result[0].docstring

    def test_maybe_with_frommaybe(self, maybe_type_with_frommaybe):
        """Parse Maybe type with fromMaybe function."""
        _, result = parse_program(maybe_type_with_frommaybe)

        assert result is not None
        assert len(result) == 2

        assert isinstance(result[0], SurfaceDataDeclaration)
        assert result[0].name == "Maybe"
        assert result[0].docstring == "Maybe type representing optional values"

        assert isinstance(result[1], SurfaceTermDeclaration)
        assert result[1].name == "fromMaybe"
        assert "Extract value" in result[1].docstring

    def test_natural_numbers(self, natural_numbers_with_conversion):
        """Parse natural numbers with conversion function."""
        _, result = parse_program(natural_numbers_with_conversion)

        assert result is not None
        assert len(result) == 2

        assert isinstance(result[0], SurfaceDataDeclaration)
        assert result[0].name == "Nat"

        assert isinstance(result[1], SurfaceTermDeclaration)
        assert result[1].name == "natToInt"

    def test_list_with_length(self, list_type_with_length):
        """Parse List type with length function."""
        _, result = parse_program(list_type_with_length)

        assert result is not None
        assert len(result) == 2

        assert isinstance(result[0], SurfaceDataDeclaration)
        assert result[0].name == "List"

        assert isinstance(result[1], SurfaceTermDeclaration)
        assert result[1].name == "length"

    def test_llm_with_pragma(self, llm_function_with_pragma):
        """Parse LLM function with pragma."""
        _, result = parse_program(llm_function_with_pragma)

        assert result is not None
        assert len(result) == 1

        decl = result[0]
        assert isinstance(decl, SurfaceTermDeclaration)
        assert decl.name == "translate"
        assert decl.docstring == "Translate English to French"
        assert decl.pragma is not None
        assert "LLM" in decl.pragma
        assert "model=gpt-4" in decl.pragma["LLM"]

    def test_complete_prelude(self, complete_prelude_subset):
        """Parse complete prelude subset with all features."""
        _, result = parse_program(complete_prelude_subset)

        assert result is not None
        assert len(result) == 9

        # Check all declarations are present
        names = [d.name for d in result]
        assert "Bool" in names
        assert "toString" in names
        assert "const" in names
        assert "Maybe" in names
        assert "fromMaybe" in names
        assert "Nat" in names
        assert "natToInt" in names
        assert "List" in names
        assert "length" in names

        # Check docstrings are preserved
        bool_decl = next(d for d in result if d.name == "Bool")
        assert bool_decl.docstring == "Boolean type with two values"

        const_decl = next(d for d in result if d.name == "const")
        assert "constant function" in const_decl.docstring

    def test_prim_op_no_body(self, term_without_body):
        """Parse prim_op declaration (signature only, no body)."""
        _, result = parse_program(term_without_body)

        assert result is not None
        assert len(result) == 1

        assert isinstance(result[0], SurfacePrimOpDecl)
        assert result[0].name == "int_plus"
        assert result[0].docstring == "Integer addition primitive"

    def test_mixed_declarations(self, mixed_declarations):
        """Parse mix of all declaration types."""
        _, result = parse_program(mixed_declarations)

        assert result is not None
        assert len(result) == 4

        assert isinstance(result[0], SurfaceDataDeclaration)
        assert result[0].name == "Bool"

        assert isinstance(result[1], SurfacePrimTypeDecl)
        assert result[1].name == "Int"

        assert isinstance(result[2], SurfacePrimOpDecl)
        assert result[2].name == "int_plus"

        assert isinstance(result[3], SurfaceTermDeclaration)
        assert result[3].name == "not"


class TestDeclarationMetadata:
    """Test that docstrings and pragmas are correctly attached."""

    def test_multiline_docstring_concatenation(self):
        """Multiple -- | lines should be concatenated with newlines (Idris2-style)."""
        source = """-- | First line of doc
-- | Second line of doc
data Test = A | B"""

        _, result = parse_program(source)
        assert result[0].docstring == "First line of doc\nSecond line of doc"

    def test_pragma_parsed_as_dict(self):
        """Pragma should be parsed into dict[str, str]."""
        source = """{-# LLM model=gpt-4 temperature=0.7 #-}
test :: Int = 1"""

        _, result = parse_program(source)
        assert result[0].pragma == {"LLM": "model=gpt-4 temperature=0.7"}

    def test_multiple_pragmas(self):
        """Multiple pragmas should be merged."""
        source = """{-# INLINE #-}
{-# LLM model=gpt-4 #-}
test :: Int = 1"""

        _, result = parse_program(source)
        assert "INLINE" in result[0].pragma
        assert "LLM" in result[0].pragma

    def test_empty_docstring(self):
        """Empty docstring (just -- |) should be empty string."""
        source = """-- |
data Test = A"""

        _, result = parse_program(source)
        assert result[0].docstring == ""

    def test_no_docstring_no_pragma(self):
        """Declaration without docstring or pragma should have None."""
        source = "data Bool = True | False"

        _, result = parse_program(source)
        assert result[0].docstring is None
        assert result[0].pragma is None


class TestElab3SyntaxSample:
    """Test that all elab3-required syntax constructs parse correctly."""

    def test_elab3_sample_program(self, elab3_syntax_sample):
        """Parse comprehensive sample with imports, data, terms, lambda, let, case, literals."""
        from systemf.surface.types import (
            SurfaceImportDeclaration,
            SurfaceDataDeclaration,
            SurfaceTermDeclaration,
            SurfaceConstructorInfo,
            SurfaceTypeVar,
            SurfaceTypeArrow,
            SurfaceTypeForall,
            SurfaceTypeConstructor,
            SurfaceAbs,
            SurfaceVar,
            SurfaceCase,
            SurfaceBranch,
            SurfacePattern,
            SurfaceLitPattern,
            SurfaceLit,
            SurfaceLet,
            ValBind,
            SurfaceApp,
            SurfaceOp,
        )
        from systemf.utils.ast_utils import equals_ignore_location

        _, result = parse_program(elab3_syntax_sample)

        expected = [
            SurfaceDataDeclaration(
                name="Bool",
                params=[],
                constructors=[
                    SurfaceConstructorInfo(name="True", args=[], docstring=None),
                    SurfaceConstructorInfo(name="False", args=[], docstring=None),
                ],
                docstring=None,
                pragma=None,
            ),
            SurfaceDataDeclaration(
                name="Maybe",
                params=[SurfaceTypeVar(name="a")],
                constructors=[
                    SurfaceConstructorInfo(name="Nothing", args=[], docstring=None),
                    SurfaceConstructorInfo(name="Just", args=[SurfaceTypeVar(name="a")], docstring=None),
                ],
                docstring=None,
                pragma=None,
            ),
            SurfaceDataDeclaration(
                name="List",
                params=[SurfaceTypeVar(name="a")],
                constructors=[
                    SurfaceConstructorInfo(name="Nil", args=[], docstring=None),
                    SurfaceConstructorInfo(
                        name="Cons",
                        args=[
                            SurfaceTypeVar(name="a"),
                            SurfaceTypeConstructor(name="List", args=[SurfaceTypeVar(name="a")]),
                        ],
                        docstring=None,
                    ),
                ],
                docstring=None,
                pragma=None,
            ),
            SurfaceTermDeclaration(
                name="id",
                type_annotation=SurfaceTypeForall(
                    vars=["a"],
                    body=SurfaceTypeArrow(arg=SurfaceTypeVar(name="a"), ret=SurfaceTypeVar(name="a"), ),
                ),
                body=SurfaceAbs(params=[("x", None)], body=SurfaceVar(name="x")),
                docstring=None,
                pragma=None,
            ),
            SurfaceTermDeclaration(
                name="const",
                type_annotation=SurfaceTypeForall(
                    vars=["a", "b"],
                    body=SurfaceTypeArrow(
                        arg=SurfaceTypeVar(name="a"),
                        ret=SurfaceTypeArrow(
                            arg=SurfaceTypeVar(name="b"),
                            ret=SurfaceTypeVar(name="a"),
                        ),
                    ),
                ),
                body=SurfaceAbs(
                    params=[("x", None), ("y", None)],
                    body=SurfaceVar(name="x"),
                ),
                docstring=None,
                pragma=None,
            ),
            SurfaceTermDeclaration(
                name="fromMaybe",
                type_annotation=SurfaceTypeForall(
                    vars=["a"],
                    body=SurfaceTypeArrow(
                        arg=SurfaceTypeVar(name="a"),
                        ret=SurfaceTypeArrow(
                            arg=SurfaceTypeConstructor(name="Maybe", args=[SurfaceTypeVar(name="a")]),
                            ret=SurfaceTypeVar(name="a"),
                        ),
                    ),
                ),
                body=SurfaceAbs(
                    params=[("default", None), ("ma", None)],
                    body=SurfaceCase(
                        scrutinee=SurfaceVar(name="ma"),
                        branches=[
                            SurfaceBranch(
                                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="Nothing")]),
                                body=SurfaceVar(name="default"),
                            ),
                            SurfaceBranch(
                                pattern=SurfacePattern(
                                    patterns=[
                                        SurfaceVarPattern(name="Just"),
                                        SurfacePattern(patterns=[SurfaceVarPattern(name="x")]),
                                    ],
                                ),
                                body=SurfaceVar(name="x"),
                            ),
                        ],
                    ),
                ),

                docstring=None,

                pragma=None,
             ),
            SurfaceTermDeclaration(
                name="length",
                type_annotation=SurfaceTypeForall(
                    vars=["a"],
                    body=SurfaceTypeArrow(
                        arg=SurfaceTypeConstructor(name="List", args=[SurfaceTypeVar(name="a")]),
                        ret=SurfaceTypeConstructor(name="Int", args=[]),
                    ),
                ),
                body=SurfaceAbs(
                    params=[("xs", None)],
                    body=SurfaceLet(
                        bindings=[
                            ValBind(
                                name="go",
                                type_ann=None,
                                value=SurfaceAbs(
                                    params=[("acc", None)],
                                    body=SurfaceAbs(
                                        params=[("ys", None)],
                                        body=SurfaceCase(
                                        scrutinee=SurfaceVar(name="ys"),
                                        branches=[
                                            SurfaceBranch(
                                                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="Nil")]),
                                                body=SurfaceVar(name="acc"),
                                            ),
                                            SurfaceBranch(
                                                pattern=SurfacePattern(
                                    patterns=[
                                        SurfaceVarPattern(name="Cons"),
                                        SurfacePattern(patterns=[SurfaceVarPattern(name="z")]),
                                        SurfacePattern(patterns=[SurfaceVarPattern(name="zs")]),
                                    ]
                                ),
                                                body=SurfaceApp(
                                                    func=SurfaceApp(
                                                        func=SurfaceVar(name="go"),
                                                        arg=SurfaceOp(
                                                            left=SurfaceVar(name="acc"),
                                                            op="+",
                                                            right=SurfaceLit(
                                                                prim_type="Int", value=1
                                                            ),
                                                        ),
                                                    ),
                                                    arg=SurfaceVar(name="zs"),
                                                ),
                                            ),
                                        ],
                                    ),
                                ),
                            ),
                            )
                        ],
                        body=SurfaceApp(
                            func=SurfaceApp(
                                func=SurfaceVar(name="go"),
                                arg=SurfaceLit(prim_type="Int", value=0),
                            ),
                            arg=SurfaceVar(name="xs"),
                        ),
                    ),
                ),

                docstring=None,

                pragma=None,
             ),
            SurfaceTermDeclaration(
                name="factorial",
                type_annotation=SurfaceTypeArrow(
                    arg=SurfaceTypeConstructor(name="Int", args=[]),
                    ret=SurfaceTypeConstructor(name="Int", args=[]),
                ),
                body=SurfaceAbs(
                    params=[("n", None)],
                    body=SurfaceCase(
                        scrutinee=SurfaceVar(name="n"),
                        branches=[
                            SurfaceBranch(
                                pattern=SurfaceLitPattern(prim_type="Int", value=0),
                                body=SurfaceLit(prim_type="Int", value=1),
                            ),
                            SurfaceBranch(
                                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="m")]),
                                body=SurfaceOp(
                                    left=SurfaceVar(name="m"),
                                    op="*",
                                    right=SurfaceApp(
                                        func=SurfaceVar(name="factorial"),
                                        arg=SurfaceOp(
                                            left=SurfaceVar(name="m"),
                                            op="-",
                                            right=SurfaceLit(prim_type="Int", value=1),
                                        ),
                                    ),
                                ),
                            ),
                        ],
                    ),
                ),

                docstring=None,

                pragma=None,
             ),
            SurfaceTermDeclaration(
                name="greet",
                type_annotation=SurfaceTypeArrow(
                    arg=SurfaceTypeConstructor(name="String", args=[]),
                    ret=SurfaceTypeConstructor(name="String", args=[]),
                ),
                body=SurfaceAbs(
                    params=[("name", None)],
                    body=SurfaceCase(
                        scrutinee=SurfaceVar(name="name"),
                        branches=[
                            SurfaceBranch(
                                pattern=SurfaceLitPattern(
                                    prim_type="String", value="world"
                                ),
                                body=SurfaceLit(
                                    prim_type="String", value="hello world"
                                ),
                            ),
                            SurfaceBranch(
                                pattern=SurfacePattern(patterns=[SurfaceVarPattern(name="other")]),
                                body=SurfaceOp(
                                    left=SurfaceLit(
                                        prim_type="String", value="hello "
                                    ),
                                    op="++",
                                    right=SurfaceVar(name="other"),
                                ),
                            ),
                        ],
                    ),
                ),

                docstring=None,

                pragma=None,
             ),
        ]

        assert len(result) == len(expected)
        for actual, exp in zip(result, expected):
            assert equals_ignore_location(actual, exp)


class TestMixedDeclarationStyles:
    """Test mixing single-line and multi-line declarations."""

    def test_single_line_followed_by_multi_line(self):
        """Parse single-line term followed by multi-line term."""
        source = """id :: forall a. a -> a = λx -> x

not :: Bool -> Bool =
  λb -> case b of
    True -> False
    False -> True"""
        _, result = parse_program(source)
        assert len(result) == 2
        assert result[0].name == "id"
        assert result[1].name == "not"

    def test_multi_line_followed_by_single_line(self):
        """Parse multi-line term followed by single-line term."""
        source = """map :: forall a b. (a -> b) -> List a -> List b =
  λf xs -> xs

const :: forall a b. a -> b -> a = λx y -> x"""
        _, result = parse_program(source)
        assert len(result) == 2
        assert result[0].name == "map"
        assert result[1].name == "const"

    def test_mixed_styles_in_sequence(self):
        """Parse sequence of mixed single-line and multi-line declarations."""
        source = """-- Single line
x :: Int = 1

-- Multi-line
y :: Int -> Int =
  λn -> n + 1

-- Single line
z :: Int = 3

-- Multi-line
w :: Bool -> Bool =
  λb -> not b"""
        _, result = parse_program(source)
        assert len(result) == 4
        assert result[0].name == "x"
        assert result[1].name == "y"
        assert result[2].name == "z"
        assert result[3].name == "w"

    def test_polymorphic_functions_mixed_styles(self):
        """Parse polymorphic functions with both single and multi-line bodies."""
        source = """-- Single line polymorphic
id :: forall a. a -> a = λx -> x

-- Multi-line polymorphic
mapMaybe :: forall a b. (a -> b) -> Maybe a -> Maybe b =
  λf m ->
    case m of
      Nothing -> Nothing
      Just x -> Just (f x)

-- Another single line
const :: forall a b. a -> b -> a = λx y -> x"""
        _, result = parse_program(source)
        assert len(result) == 3
        assert result[0].name == "id"
        assert result[1].name == "mapMaybe"
        assert result[2].name == "const"

    def test_multi_line_with_type_abstraction(self):
        """Parse multi-line terms with type abstraction (removed Λ)."""
        source = """isJust :: forall a. Maybe a -> Bool =
  λm ->
    case m of { Nothing -> False | Just x -> True }

isNothing :: forall a. Maybe a -> Bool =
  λm ->
    case m of { Nothing -> True | Just x -> False }

just :: forall a. a -> Maybe a = λx -> Just x"""
        _, result = parse_program(source)
        assert len(result) == 3
        assert result[0].name == "isJust"
        assert result[1].name == "isNothing"
        assert result[2].name == "just"


class TestImportOrdering:
    """Test that import declarations must appear before other declarations."""

    def test_imports_at_top_succeed(self):
        """Imports before declarations parse successfully."""
        source = """import List (map, filter)
import qualified Data.Maybe as M

x :: Int = 42
y :: Int = 43"""
        imports, decls = parse_program(source)
        assert len(imports) == 2
        assert len(decls) == 2
        assert imports[0].module == "List"
        assert imports[1].module == "Data.Maybe"
        assert decls[0].name == "x"
        assert decls[1].name == "y"

    def test_import_only_module_succeed(self):
        """Module with only imports parses successfully."""
        source = """import List
import qualified Data.Maybe"""
        imports, decls = parse_program(source)
        assert len(imports) == 2
        assert len(decls) == 0
        assert imports[0].module == "List"
        assert imports[1].module == "Data.Maybe"

    def test_import_after_term_fails(self):
        """Import after a term declaration causes parse error."""
        source = """x :: Int = 42
import List"""
        with pytest.raises(Exception) as exc_info:
            parse_program(source)
        assert "import declarations must appear before other declarations" in str(exc_info.value)

    def test_scattered_imports_fails(self):
        """Imports interleaved with declarations cause parse error."""
        source = """import List
x :: Int = 42
import Data.Maybe"""
        with pytest.raises(Exception) as exc_info:
            parse_program(source)
        assert "import declarations must appear before other declarations" in str(exc_info.value)

    def test_docstring_before_import_succeed(self):
        """Docstring before an import is allowed (silently discarded)."""
        source = """-- | Module doc
import List

x :: Int = 42"""
        imports, decls = parse_program(source)
        assert len(imports) == 1
        assert len(decls) == 1
        assert imports[0].module == "List"
        assert decls[0].name == "x"
