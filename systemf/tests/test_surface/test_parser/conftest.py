"""Fixtures for testing multiple declarations parsing.

Provides example programs with multiple declarations as pytest fixtures.
"""

import pytest


@pytest.fixture
def simple_multiple_decls():
    """Simple multiple declarations without docstrings."""
    return """data Bool = True | False

data Maybe a = Nothing | Just a

not :: Bool -> Bool = \\b ->
  case b of
    True -> False
    False -> True"""


@pytest.fixture
def bool_with_tostring():
    """Bool type with toString function (rank-0)."""
    return """-- | Boolean type with two values
data Bool = True | False

-- | Convert Bool to String
-- | Returns "true" or "false"
toString :: Bool -> String = \\b ->
  case b of
    True -> "true"
    False -> "false"
"""


@pytest.fixture
def rank2_const_function():
    """Rank-2 polymorphic const function."""
    return """-- | The constant function (rank-2 polymorphic)
-- | Returns first argument, ignores second
const :: forall a. forall b. a -> b -> a = \\x y -> x"""


@pytest.fixture
def maybe_type_with_frommaybe():
    """Maybe type with fromMaybe function."""
    return """-- | Maybe type representing optional values
data Maybe a = Nothing | Just a

-- | Extract value from Maybe with default
fromMaybe :: forall a. a -> Maybe a -> a = \\default ma ->
  case ma of
    Nothing -> default
    Just x -> x"""


@pytest.fixture
def natural_numbers_with_conversion():
    """Natural numbers type with Int conversion."""
    return """-- | Natural numbers
data Nat = Zero | Succ Nat

-- | Convert Nat to Int
natToInt :: Nat -> Int = \\n ->
  case n of
    Zero -> 0
    Succ m -> 1 + natToInt m"""


@pytest.fixture
def list_type_with_length():
    """List type with length function."""
    return """-- | List data type
data List a = Nil | Cons a (List a)

-- | Get length of list
length :: forall a. List a -> Int = \\xs ->
  case xs of
    Nil -> 0
    Cons y ys -> 1 + length ys"""


@pytest.fixture
def llm_function_with_pragma():
    """LLM function with pragma and docstrings."""
    return """{-# LLM model=gpt-4 temperature=0.7 #-}
-- | Translate English to French
translate :: String -> String = \\text -> text"""


@pytest.fixture
def complete_prelude_subset():
    """Complete subset of prelude with multiple types and functions."""
    return """-- | Boolean type with two values
data Bool = True | False

-- | Convert Bool to String
-- | Returns "true" or "false"
toString :: Bool -> String = \\b ->
  case b of
    True -> "true"
    False -> "false"

-- | The constant function (rank-2 polymorphic)
-- | Returns first argument, ignores second
const :: forall a. forall b. a -> b -> a = \\x y -> x

-- | Maybe type representing optional values
data Maybe a = Nothing | Just a

-- | Extract value from Maybe with default
fromMaybe :: forall a. a -> Maybe a -> a = \\default ma ->
  case ma of
    Nothing -> default
    Just x -> x

-- | Natural numbers
data Nat = Zero | Succ Nat

-- | Convert Nat to Int
natToInt :: Nat -> Int = \\n ->
  case n of
    Zero -> 0
    Succ m -> 1 + natToInt m

-- | List data type
data List a = Nil | Cons a (List a)

-- | Get length of list
length :: forall a. List a -> Int = \\xs ->
  case xs of
    Nil -> 0
    Cons y ys -> 1 + length ys"""


@pytest.fixture
def term_without_body():
    """PrimOp declaration (signature only, no body)."""
    return """-- | Integer addition primitive
prim_op int_plus :: Int -> Int -> Int"""


@pytest.fixture
def mixed_declarations():
    """Mix of data, term, prim_type, and prim_op declarations."""
    return """-- | Boolean type
data Bool = True | False

-- | Primitive integer type
prim_type Int

-- | Integer addition
prim_op int_plus :: Int -> Int -> Int

-- | Logical negation
not :: Bool -> Bool = \\b ->
  case b of
    True -> False
    False -> True"""


@pytest.fixture
def elab3_syntax_sample():
    """Sample program exercising all elab3-required surface syntax."""
    return """import List

data Bool = True | False

data Maybe a = Nothing | Just a

data List a = Nil | Cons a (List a)

id :: forall a. a -> a = λx -> x

const :: forall a b. a -> b -> a = λx y -> x

fromMaybe :: forall a. a -> Maybe a -> a = λdefault ma ->
  case ma of
    Nothing -> default
    Just x -> x

length :: forall a. List a -> Int =
  λxs ->
    let
      go acc ys = case ys of
        Nil -> acc
        Cons z zs -> go (acc + 1) zs
    in go 0 xs

factorial :: Int -> Int = λn ->
  case n of
    0 -> 1
    m -> m * factorial (m - 1)

greet :: String -> String = λname ->
  case name of
    "world" -> "hello world"
    other -> "hello " ++ other
"""
