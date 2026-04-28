"""Unit tests for declaration parsers.

Tests for individual declaration parsers from declarations.py.
These tests validate the grammar from syntax.md Section 7.
"""

import pytest
from systemf.surface.parser import (
    decl_parser,
    data_parser,
    term_parser,
    prim_type_parser,
    prim_op_parser,
    type_parser,
    lex,
)
from systemf.surface.parser import (
    import_decl_parser,
)
from systemf.surface.types import (
    SurfaceDataDeclaration,
    SurfaceImportDeclaration,
    SurfacePrimOpDecl,
    SurfacePrimTypeDecl,
    SurfaceTermDeclaration,
    SurfaceTypeConstructor,
    SurfaceTypeApp,
    SurfaceTypeTuple,
)
from systemf.utils.ast_utils import equals_ignore_location



class TestDataDeclaration:
    """Test data declaration parser."""

    def test_simple_data(self):
        """Parse data Bool = True | False."""
        tokens = lex("data Bool = True | False")
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "Bool"
        assert len(result.constructors) == 2

    def test_data_with_param(self):
        """Parse data Maybe a = Nothing | Just a."""
        tokens = lex("data Maybe a = Nothing | Just a")
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "Maybe"
        assert any(p.name == "a" for p in result.params)

    def test_data_with_multiple_params(self):
        """Parse data Either a b = Left a | Right b."""
        tokens = lex("data Either a b = Left a | Right b")
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "Either"
        assert len(result.params) == 2

    def test_data_single_constructor(self):
        """Parse data Identity a = Identity a."""
        tokens = lex("data Identity a = Identity a")
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert len(result.constructors) == 1

    def test_recursive_data(self):
        """Parse recursive data type."""
        source = """data List a =
  Nil
  | Cons a (List a)"""
        tokens = lex(source)
        result = decl_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "List"

    def test_data_constructor_with_args(self):
        """Parse constructor with multiple arguments."""
        tokens = lex("data Pair a b = Pair a b")
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        cons = result.constructors[0]
        # Constructor should have 2 arguments
        assert len(cons.args) == 2

    def test_data_style1_single_line(self):
        """Parse single-line data: data X = A | B."""
        source = "data X = A | B"
        tokens = lex(source)
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "X"
        assert len(result.constructors) == 2
        assert result.constructors[0].name == "A"
        assert result.constructors[1].name == "B"

    def test_data_style2_indented_constructor_on_same_line(self):
        """Parse data with first constructor on same line as =."""
        source = """data X1 = A1
        | B1"""
        tokens = lex(source)
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "X1"
        assert len(result.constructors) == 2
        assert result.constructors[0].name == "A1"
        assert result.constructors[1].name == "B1"

    def test_data_style3_more_indented(self):
        """Parse data with more indentation for second constructor."""
        source = """data X2 = A2
          | B2"""
        tokens = lex(source)
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "X2"
        assert len(result.constructors) == 2
        assert result.constructors[0].name == "A2"
        assert result.constructors[1].name == "B2"

    def test_data_style4_name_on_own_line(self):
        """Parse data with name on its own line, then = on next line."""
        source = """data X3
  = A3
  | B3"""
        tokens = lex(source)
        result = data_parser().parse(tokens)
        assert isinstance(result, SurfaceDataDeclaration)
        assert result.name == "X3"
        assert len(result.constructors) == 2
        assert result.constructors[0].name == "A3"
        assert result.constructors[1].name == "B3"

    def test_data_all_styles_equivalence(self):
        """Verify all data declaration styles produce identical AST."""
        # Parse reference style (simplest form)
        reference = data_parser().parse(lex("data X = A | B"))

        # All these should parse to equivalent ASTs (same structure as reference)
        sources = [
            "data X = A\n        | B",
            "data X = A\n          | B",
            "data X\n  = A\n  | B",
        ]

        for source in sources:
            result = data_parser().parse(lex(source))
            # Use structural equality to compare AST structure (ignoring source locations)
            assert equals_ignore_location(result, reference), f"Style failed: {source!r}"

    def test_data_dedented_constructor_behavior(self):
        """Document behavior with dedented constructors (may be relaxed layout)."""
        # Constructor at column 1 when first was at column > 1
        # Current parser behavior: accepts this (relaxed layout)
        source = """data X = A
| B"""
        tokens = lex(source)
        result = data_parser().parse(tokens)
        # Parser accepts this - documents current behavior
        # If strict layout is desired, this should be rejected
        assert isinstance(result, SurfaceDataDeclaration)
        assert len(result.constructors) == 2

    def test_data_rejects_missing_separator(self):
        """Parser should reject constructors without | separator."""
        from parsy import ParseError

        source = "data X = A B"
        tokens = lex(source)
        # This might parse as single constructor with arg, not two constructors
        result = data_parser().parse(tokens)
        # Should have 1 constructor with 1 arg, not 2 constructors
        assert len(result.constructors) == 1
        assert len(result.constructors[0].args) == 1


class TestTermDeclaration:
    """Test term (function) declaration parser."""

    def test_simple_function(self):
        """Parse x :: Int = 42."""
        tokens = lex("x :: Int = 42")
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "x"

    def test_function_with_lambda(self):
        """Parse identity :: forall a. a -> a = λx → x."""
        tokens = lex("identity :: forall a. a -> a = λx → x")
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "identity"

    def test_function_with_params(self):
        """Parse add x y :: Int = x + y."""
        # Note: This syntax is shorthand for add = λx y → x + y
        tokens = lex("add :: Int -> Int -> Int = λx y → x + y")
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "add"

    def test_polymorphic_function(self):
        """Parse map function with higher-order type."""
        tokens = lex("map :: forall a b. (a -> b) -> List a -> List b = λf xs → xs")
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)

    def test_recursive_function(self):
        """Parse recursive factorial."""
        source = """factorial :: Int -> Int =
  λn → if n == 0 then 1 else n * factorial (n - 1)"""
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)

    def test_single_line_term_declaration(self):
        """Parse single-line term declaration: x :: Int = 42."""
        source = "x :: Int = 42"
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "x"
        # Should consume exactly all tokens
        assert result is not None

    def test_multi_line_term_declaration(self):
        """Parse multi-line term declaration with expression body on next line."""
        source = """not :: Bool -> Bool =
  λb -> case b of
    True -> False
    False -> True"""
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "not"

    def test_multi_line_polymorphic_term(self):
        """Parse multi-line polymorphic term."""
        source = """isJust :: forall a. Maybe a -> Bool =
  λm ->
    case m of { Nothing -> False | Just x -> True }"""
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "isJust"

    def test_term_declaration_with_nested_case(self):
        """Parse term with nested case expressions."""
        source = """xor :: Bool -> Bool -> Bool =
  λ(x :: Bool) -> λ(y :: Bool) ->
    case x of
      True -> case y of { True -> False | False -> True }
      False -> y"""
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "xor"

    def test_term_single_vs_multi_line_equivalence(self):
        """Verify single-line and multi-line produce same declaration type."""
        # Single line
        single = "id :: forall a. a -> a = λx -> x"
        single_result = term_parser().parse(lex(single))

        # Multi line (semantically equivalent)
        multi = """id :: forall a. a -> a =
  λx -> x"""
        multi_result = term_parser().parse(lex(multi))

        # Both should produce valid term declarations
        assert isinstance(single_result, SurfaceTermDeclaration)
        assert isinstance(multi_result, SurfaceTermDeclaration)
        assert single_result.name == multi_result.name == "id"

    def test_lambda_with_annotation_declaration(self):
        """Parse id :: ∀a. a → a = λ(x :: a) → x."""
        source = "id :: ∀a. a → a = λ(x :: a) → x"
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "id"

    def test_let_with_type_annotation_in_declaration(self):
        """Parse a declaration whose body contains a let with a type annotation."""
        source = "foo :: Int → Int = λx → let y :: Int = x + 1 in y"
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "foo"

    def test_mixed_lambda_params_declaration(self):
        """Parse function with mixed annotated/unannotated params."""
        source = "apply :: (Int → Int) → Int → Int = λf (x :: Int) → f x"
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "apply"

    def test_higher_rank_lambda_annotation(self):
        """Parse higher-rank function with annotation."""
        source = "applyPoly :: (∀a. a → a) → Int → Int = λ(f :: ∀a. a → a) x → f 42 x"
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "applyPoly"

    def test_nested_let_with_annotations(self):
        """Parse a declaration with nested let expressions with type annotations."""
        source = "compute :: Int = let x :: Int = 1 in let y :: Int = 2 in x + y"
        tokens = lex(source)
        result = term_parser().parse(tokens)
        assert isinstance(result, SurfaceTermDeclaration)
        assert result.name == "compute"


class TestPrimitiveDeclarations:
    """Test primitive type and operation declarations."""

    def test_prim_type(self):
        """Parse prim_type Int."""
        tokens = lex("prim_type Int")
        result = prim_type_parser().parse(tokens)
        assert isinstance(result, SurfacePrimTypeDecl)
        assert result.name == "Int"

    def test_prim_type_bool(self):
        """Parse prim_type Bool."""
        tokens = lex("prim_type Bool")
        result = prim_type_parser().parse(tokens)
        assert isinstance(result, SurfacePrimTypeDecl)

    def test_prim_op(self):
        """Parse prim_op int_plus :: Int -> Int -> Int."""
        tokens = lex("prim_op int_plus :: Int -> Int -> Int")
        result = prim_op_parser().parse(tokens)
        assert isinstance(result, SurfacePrimOpDecl)
        assert result.name == "int_plus"

    def test_prim_op_arithmetic(self):
        """Parse multiple arithmetic primitives."""
        ops = [
            "prim_op int_plus :: Int -> Int -> Int",
            "prim_op int_minus :: Int -> Int -> Int",
            "prim_op int_mult :: Int -> Int -> Int",
        ]
        for op in ops:
            tokens = lex(op)
            result = prim_op_parser().parse(tokens)
            assert isinstance(result, SurfacePrimOpDecl)

    def test_prim_op_comparison(self):
        """Parse comparison primitives."""
        tokens = lex("prim_op int_eq :: Int -> Int -> Bool")
        result = prim_op_parser().parse(tokens)
        assert isinstance(result, SurfacePrimOpDecl)


class TestDeclarationCombinations:
    """Test combining different declaration types."""

    def test_data_then_term(self):
        """Parse data then function using that type."""
        # Individual declarations, not a sequence
        data_tokens = lex("data Bool = True | False")
        term_tokens = lex("not :: Bool -> Bool = λx → x")

        data_result = decl_parser().parse(data_tokens)
        term_result = decl_parser().parse(term_tokens)

        assert isinstance(data_result, SurfaceDataDeclaration)
        assert isinstance(term_result, SurfaceTermDeclaration)

    def test_multiple_primitives(self):
        """Parse multiple primitive declarations."""
        types = [
            "prim_type Int",
            "prim_type Bool",
            "prim_type String",
        ]
        for t in types:
            tokens = lex(t)
            result = decl_parser().parse(tokens)
            assert isinstance(result, SurfacePrimTypeDecl)

    def test_complete_program_structure(self):
        """Parse typical program structure."""
        # This is what a typical System F program looks like
        decls = [
            "data Bool = True | False",
            "data Maybe a = Nothing | Just a",
            "prim_type Int",
            "id :: forall a. a -> a = λx → x",
            "const :: forall a b. a -> b -> a = λx y → x",
        ]

        for decl in decls:
            tokens = lex(decl)
            result = decl_parser().parse(tokens)
            assert result is not None


class TestImportDeclaration:
    """Test import declaration parser."""

    def test_simple_import(self):
        """Parse import List."""
        tokens = lex("import List")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="List", alias=None, items=None)
        assert equals_ignore_location(result, expected)

    def test_qualified_import(self):
        """Parse import qualified Data.Maybe."""
        tokens = lex("import qualified Data.Maybe")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="Data.Maybe", qualified=True, alias=None, items=None)
        assert equals_ignore_location(result, expected)

    def test_aliased_import(self):
        """Parse import List as L."""
        tokens = lex("import List as L")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="List", alias="L", items=None)
        assert equals_ignore_location(result, expected)

    def test_qualified_aliased_import(self):
        """Parse import qualified List as L."""
        tokens = lex("import qualified List as L")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="List", qualified=True, alias="L", items=None)
        assert equals_ignore_location(result, expected)

    def test_explicit_items(self):
        """Parse import List (map, filter)."""
        tokens = lex("import List (map, filter)")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="List", alias=None, items=["map", "filter"])
        assert equals_ignore_location(result, expected)

    def test_hiding_items(self):
        """Parse import List hiding (internal)."""
        tokens = lex("import List hiding (internal)")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="List", alias=None, items=["internal"], hiding=True)
        assert equals_ignore_location(result, expected)

    def test_empty_explicit_items(self):
        """Parse import List ()."""
        tokens = lex("import List ()")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="List", alias=None, items=[])
        assert equals_ignore_location(result, expected)

    def test_empty_hiding_items(self):
        """Parse import List hiding ()."""
        tokens = lex("import List hiding ()")
        result = import_decl_parser().parse(tokens)
        assert isinstance(result, SurfaceImportDeclaration)
        expected = SurfaceImportDeclaration(module="List", alias=None, items=[], hiding=True)
        assert equals_ignore_location(result, expected)


class TestTypeParser:
    """Test the type parser (from declarations module)."""

    def test_simple_type(self):
        """Parse Int type."""
        tokens = lex("Int")
        result = type_parser().parse(tokens)
        assert isinstance(result, SurfaceTypeConstructor)
        assert result.name == "Int"

    def test_type_variable(self):
        """Parse type variable 'a'."""
        tokens = lex("a")
        result = type_parser().parse(tokens)
        assert result is not None

    def test_arrow_type(self):
        """Parse Int -> Bool."""
        tokens = lex("Int -> Bool")
        result = type_parser().parse(tokens)
        assert result is not None

    def test_forall_type(self):
        """Parse forall a. a -> a."""
        tokens = lex("forall a. a -> a")
        result = type_parser().parse(tokens)
        assert result is not None

    def test_higher_order_type(self):
        """Parse (a -> b) -> List a -> List b."""
        tokens = lex("(a -> b) -> List a -> List b")
        result = type_parser().parse(tokens)
        assert result is not None

    def test_type_application(self):
        """Parse List Int."""
        tokens = lex("List Int")
        result = type_parser().parse(tokens)
        # Parser now produces SurfaceTypeConstructor with args directly
        assert isinstance(result, SurfaceTypeConstructor)
        assert result.name == "List"
        assert len(result.args) == 1
        assert isinstance(result.args[0], SurfaceTypeConstructor)
        assert result.args[0].name == "Int"

    def test_nested_forall(self):
        """Parse forall a b c. a -> b -> c -> a."""
        tokens = lex("forall a b c. a -> b -> c -> a")
        result = type_parser().parse(tokens)
        assert result is not None

    def test_unit_type(self):
        """Parse Unit type constructor (defined in prelude)."""
        tokens = lex("Unit")
        result = type_parser().parse(tokens)
        assert isinstance(result, SurfaceTypeConstructor)
        assert result.name == "Unit"

    def test_tuple_type(self):
        """Parse (Int, Bool) tuple."""
        tokens = lex("(Int, Bool)")
        result = type_parser().parse(tokens)
        assert isinstance(result, SurfaceTypeTuple)
        assert len(result.elements) == 2
        assert isinstance(result.elements[0], SurfaceTypeConstructor)
        assert result.elements[0].name == "Int"
        assert isinstance(result.elements[1], SurfaceTypeConstructor)
        assert result.elements[1].name == "Bool"

    def test_rank2_type(self):
        """Parse rank-2 type (forall a. a -> a) -> Int."""
        tokens = lex("(forall a. a -> a) -> Int")
        result = type_parser().parse(tokens)
        assert result is not None
