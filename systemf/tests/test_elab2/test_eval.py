from systemf.elab2.eval import Builder, Val, VLit, VClosure, VData, VPartial, Lam, eval
import pytest


def b():
    return Builder()


def test_lit():
    B = b()
    assert eval(B.lit(42)) == VLit(42)


def test_identity():
    B = b()
    # (\x. x) 1
    t = B.app(B.lam("x", lambda: B.var("x")), B.lit(1))
    assert eval(t) == VLit(1)


def test_const():
    B = b()
    # (\x. \y. x) 1 2
    t = B.app(
        B.app(
            B.lam("x", lambda: B.lam("y", lambda: B.var("x"))),
            B.lit(1),
        ),
        B.lit(2),
    )
    assert eval(t) == VLit(1)


def test_shadow():
    B = b()
    # (\x. \x. x) 1 2
    t = B.app(
        B.app(
            B.lam("x", lambda: B.lam("x", lambda: B.var("x"))),
            B.lit(1),
        ),
        B.lit(2),
    )
    assert eval(t) == VLit(2)


def test_closure_captures_env():
    B = b()
    # (\x. \y. x) 10
    t = B.app(
        B.lam("x", lambda: B.lam("y", lambda: B.var("x"))),
        B.lit(10),
    )
    result = eval(t)
    assert isinstance(result, VClosure)


def test_apply_returned_closure():
    B = b()
    # ((\x. \y. x) 10) 20  =>  10
    t = B.app(
        B.app(
            B.lam("x", lambda: B.lam("y", lambda: B.var("x"))),
            B.lit(10),
        ),
        B.lit(20),
    )
    assert eval(t) == VLit(10)


def test_nested_application():
    B = b()
    # (\f. \x. f x) (\y. y) 7  =>  7
    t = B.app(
        B.app(
            B.lam("f", lambda: B.lam("x", lambda: B.app(B.var("f"), B.var("x")))),
            B.lam("y", lambda: B.var("y")),
        ),
        B.lit(7),
    )
    assert eval(t) == VLit(7)


def test_church_true():
    B = b()
    # true = \t. \f. t
    # true 1 0  =>  1
    t = B.app(
        B.app(
            B.lam("t", lambda: B.lam("f", lambda: B.var("t"))),
            B.lit(1),
        ),
        B.lit(0),
    )
    assert eval(t) == VLit(1)


def test_church_false():
    B = b()
    # false = \t. \f. f
    # false 1 0  =>  0
    t = B.app(
        B.app(
            B.lam("t", lambda: B.lam("f", lambda: B.var("f"))),
            B.lit(1),
        ),
        B.lit(0),
    )
    assert eval(t) == VLit(0)


def test_omega_like_self_apply():
    B = b()
    # (\x. x) (\x. x)  =>  closure
    t = B.app(
        B.lam("x", lambda: B.var("x")),
        B.lam("x", lambda: B.var("x")),
    )
    result = eval(t)
    assert isinstance(result, VClosure)


def test_deep_nesting():
    B = b()
    # (\a. \b. \c. a) 1 2 3  =>  1
    t = B.app(
        B.app(
            B.app(
                B.lam("a", lambda: B.lam("b", lambda: B.lam("c", lambda: B.var("a")))),
                B.lit(1),
            ),
            B.lit(2),
        ),
        B.lit(3),
    )
    assert eval(t) == VLit(1)


def test_let_simple():
    B = b()
    # let x = 5 in x  =>  5
    t = B.let("x", lambda: B.lit(5), lambda: B.var("x"))
    assert eval(t) == VLit(5)


def test_let_in_body():
    B = b()
    # let x = 1 in let y = 2 in x  =>  1
    t = B.let("x", lambda: B.lit(1), lambda: B.let("y", lambda: B.lit(2), lambda: B.var("x")))
    assert eval(t) == VLit(1)


def test_let_shadow():
    B = b()
    # let x = 1 in let x = 2 in x  =>  2
    t = B.let("x", lambda: B.lit(1), lambda: B.let("x", lambda: B.lit(2), lambda: B.var("x")))
    assert eval(t) == VLit(2)


def test_let_with_lambda():
    B = b()
    # let f = \x. x in f 42  =>  42
    t = B.let("f", lambda: B.lam("x", lambda: B.var("x")), lambda: B.app(B.var("f"), B.lit(42)))
    assert eval(t) == VLit(42)


def test_let_expr_uses_outer():
    B = b()
    # let x = 10 in let y = x in y  =>  10
    t = B.let("x", lambda: B.lit(10), lambda: B.let("y", lambda: B.var("x"), lambda: B.var("y")))
    assert eval(t) == VLit(10)


def test_let_recursive():
    B = b()
    # let f = \n. case n of { 0 -> 1; _ -> (*) n (f ((-) n 1)) } in f 5  =>  120
    t = B.let("f",
        lambda: B.lam("n", lambda: B.case(B.var("n"), [
            lambda: B.case_lit(0, lambda: B.lit(1)),
            lambda: B.case_default(lambda:
                B.app(B.app(B.var("*"), B.var("n")),
                    B.app(B.var("f"), B.app(B.app(B.var("-"), B.var("n")), B.lit(1))))),
        ])),
        lambda: B.app(B.var("f"), B.lit(5)))
    assert eval(t) == VLit(120)


# --- Data & Case ---

def test_data_nullary():
    B = b()
    # UNIT  =>  VData("UNIT", [])
    t = B.var("UNIT")
    assert eval(t) == VData("UNIT", [])


def test_data_with_fields():
    B = b()
    # PAIR 1 2  =>  VData("PAIR", [VLit(1), VLit(2)])
    t = B.app(B.app(B.var("PAIR"), B.lit(1)), B.lit(2))
    assert eval(t) == VData("PAIR", [VLit(1), VLit(2)])


def test_case_lit():
    B = b()
    # case 1 of { 1 -> 10; 2 -> 20 }  =>  10
    t = B.case(B.lit(1), [
        lambda: B.case_lit(1, lambda: B.lit(10)),
        lambda: B.case_lit(2, lambda: B.lit(20)),
    ])
    assert eval(t) == VLit(10)


def test_case_lit_second():
    B = b()
    # case 2 of { 1 -> 10; 2 -> 20 }  =>  20
    t = B.case(B.lit(2), [
        lambda: B.case_lit(1, lambda: B.lit(10)),
        lambda: B.case_lit(2, lambda: B.lit(20)),
    ])
    assert eval(t) == VLit(20)


def test_case_default():
    B = b()
    # case 99 of { 1 -> 10; _ -> 0 }  =>  0
    t = B.case(B.lit(99), [
        lambda: B.case_lit(1, lambda: B.lit(10)),
        lambda: B.case_default(lambda: B.lit(0)),
    ])
    assert eval(t) == VLit(0)


def test_case_data_nullary():
    B = b()
    # case TRUE of { TRUE -> 1; FALSE -> 0 }  =>  1
    t = B.case(B.var("TRUE"), [
        lambda: B.case_data("TRUE", [], lambda: B.lit(1)),
        lambda: B.case_data("FALSE", [], lambda: B.lit(0)),
    ])
    assert eval(t) == VLit(1)


def test_case_data_with_fields():
    B = b()
    # case PAIR 3 4 of { PAIR a b -> a }  =>  3
    t = B.case(B.app(B.app(B.var("PAIR"), B.lit(3)), B.lit(4)), [
        lambda: B.case_data("PAIR", ["a", "b"], lambda: B.var("a")),
    ])
    assert eval(t) == VLit(3)


def test_case_data_second_field():
    B = b()
    # case PAIR 3 4 of { PAIR a b -> b }  =>  4
    t = B.case(B.app(B.app(B.var("PAIR"), B.lit(3)), B.lit(4)), [
        lambda: B.case_data("PAIR", ["a", "b"], lambda: B.var("b")),
    ])
    assert eval(t) == VLit(4)


def test_case_nested_data():
    B = b()
    # let x = PAIR 10 20 in case x of { PAIR a b -> a }  =>  10
    t = B.let("x", lambda: B.app(B.app(B.var("PAIR"), B.lit(10)), B.lit(20)),
        lambda: B.case(B.var("x"), [
            lambda: B.case_data("PAIR", ["a", "b"], lambda: B.var("a")),
        ]))
    assert eval(t) == VLit(10)


def test_case_data_fallthrough():
    B = b()
    # case NIL of { CONS x xs -> x; NIL -> 0 }  =>  0
    t = B.case(B.var("NIL"), [
        lambda: B.case_data("CONS", ["x", "xs"], lambda: B.var("x")),
        lambda: B.case_data("NIL", [], lambda: B.lit(0)),
    ])
    assert eval(t) == VLit(0)


def test_case_no_match():
    B = b()
    # case 3 of { 1 -> 10; 2 -> 20 }  =>  error
    t = B.case(B.lit(3), [
        lambda: B.case_lit(1, lambda: B.lit(10)),
        lambda: B.case_lit(2, lambda: B.lit(20)),
    ])
    with pytest.raises(Exception, match="no matching case"):
        eval(t)


# --- Data constructors ---

def test_true():
    B = b()
    assert eval(B.var("TRUE")) == VData("TRUE", [])


def test_false():
    B = b()
    assert eval(B.var("FALSE")) == VData("FALSE", [])


def test_nil():
    B = b()
    assert eval(B.var("NIL")) == VData("NIL", [])


def test_cons():
    B = b()
    # CONS 1 NIL  =>  VData("CONS", [VLit(1), VData("NIL", [])])
    t = B.app(B.app(B.var("CONS"), B.lit(1)), B.var("NIL"))
    assert eval(t) == VData("CONS", [VLit(1), VData("NIL", [])])


def test_cons_nested():
    B = b()
    # CONS 1 (CONS 2 NIL)
    t = B.app(B.app(B.var("CONS"), B.lit(1)),
              B.app(B.app(B.var("CONS"), B.lit(2)), B.var("NIL")))
    assert eval(t) == VData("CONS", [VLit(1), VData("CONS", [VLit(2), VData("NIL", [])])])


def test_pair_nested():
    B = b()
    # PAIR (PAIR 1 2) 3
    t = B.app(B.app(B.var("PAIR"), B.app(B.app(B.var("PAIR"), B.lit(1)), B.lit(2))), B.lit(3))
    assert eval(t) == VData("PAIR", [VData("PAIR", [VLit(1), VLit(2)]), VLit(3)])


# --- ifte ---

def test_ifte_true():
    B = b()
    # if TRUE then 1 else 0  =>  1
    t = B.ifte(B.var("TRUE"), B.lit(1), B.lit(0))
    assert eval(t) == VLit(1)


def test_ifte_false():
    B = b()
    # if FALSE then 1 else 0  =>  0
    t = B.ifte(B.var("FALSE"), B.lit(1), B.lit(0))
    assert eval(t) == VLit(0)


def test_ifte_with_exprs():
    B = b()
    # let b = TRUE in if b then PAIR 1 2 else UNIT
    t = B.let("b", lambda: B.var("TRUE"),
        lambda: B.ifte(B.var("b"),
                       B.app(B.app(B.var("PAIR"), B.lit(1)), B.lit(2)),
                       B.var("UNIT")))
    assert eval(t) == VData("PAIR", [VLit(1), VLit(2)])


def test_ifte_nested():
    B = b()
    # if TRUE then (if FALSE then 1 else 2) else 3  =>  2
    t = B.ifte(B.var("TRUE"),
               B.ifte(B.var("FALSE"), B.lit(1), B.lit(2)),
               B.lit(3))
    assert eval(t) == VLit(2)


# --- Case on list ---

def test_case_cons_head():
    B = b()
    # case CONS 42 NIL of { CONS h t -> h; NIL -> 0 }  =>  42
    t = B.case(B.app(B.app(B.var("CONS"), B.lit(42)), B.var("NIL")), [
        lambda: B.case_data("CONS", ["h", "t"], lambda: B.var("h")),
        lambda: B.case_data("NIL", [], lambda: B.lit(0)),
    ])
    assert eval(t) == VLit(42)


def test_case_cons_tail():
    B = b()
    # case CONS 1 NIL of { CONS h t -> t; NIL -> NIL }  =>  VData("NIL", [])
    t = B.case(B.app(B.app(B.var("CONS"), B.lit(1)), B.var("NIL")), [
        lambda: B.case_data("CONS", ["h", "t"], lambda: B.var("t")),
        lambda: B.case_data("NIL", [], lambda: B.var("NIL")),
    ])
    assert eval(t) == VData("NIL", [])


# --- PrimOps ---

def test_primop_add():
    B = b()
    # (+) 1 2  =>  3
    t = B.app(B.app(B.var("+"), B.lit(1)), B.lit(2))
    assert eval(t) == VLit(3)


def test_primop_sub():
    B = b()
    # (-) 10 3  =>  7
    t = B.app(B.app(B.var("-"), B.lit(10)), B.lit(3))
    assert eval(t) == VLit(7)


def test_primop_mul():
    B = b()
    # (*) 4 5  =>  20
    t = B.app(B.app(B.var("*"), B.lit(4)), B.lit(5))
    assert eval(t) == VLit(20)


def test_primop_div():
    B = b()
    # (/) 10 3  =>  3
    t = B.app(B.app(B.var("/"), B.lit(10)), B.lit(3))
    assert eval(t) == VLit(3)


def test_primop_in_let():
    B = b()
    # let x = (+) 1 2 in (*) x 10  =>  30
    t = B.let("x", lambda: B.app(B.app(B.var("+"), B.lit(1)), B.lit(2)),
        lambda: B.app(B.app(B.var("*"), B.var("x")), B.lit(10)))
    assert eval(t) == VLit(30)


# --- Partial application ---

def test_partial_primop():
    B = b()
    # let add1 = (+) 1 in add1 2  =>  3
    t = B.let("add1", lambda: B.app(B.var("+"), B.lit(1)),
        lambda: B.app(B.var("add1"), B.lit(2)))
    assert eval(t) == VLit(3)


def test_partial_primop_is_value():
    B = b()
    # (+) 1  =>  VPartial
    t = B.app(B.var("+"), B.lit(1))
    result = eval(t)
    assert isinstance(result, VPartial)
    assert result.name == "+"
    assert result.done == [VLit(1)]


def test_partial_primop_passed_to_lambda():
    B = b()
    # (\f. f 5) ((+) 3)  =>  8
    t = B.app(
        B.lam("f", lambda: B.app(B.var("f"), B.lit(5))),
        B.app(B.var("+"), B.lit(3)))
    assert eval(t) == VLit(8)


def test_partial_data():
    B = b()
    # let mkpair = PAIR 1 in mkpair 2  =>  VData("PAIR", [VLit(1), VLit(2)])
    t = B.let("mkpair", lambda: B.app(B.var("PAIR"), B.lit(1)),
        lambda: B.app(B.var("mkpair"), B.lit(2)))
    assert eval(t) == VData("PAIR", [VLit(1), VLit(2)])


def test_partial_data_is_value():
    B = b()
    # PAIR 1  =>  VPartial
    t = B.app(B.var("PAIR"), B.lit(1))
    result = eval(t)
    assert isinstance(result, VPartial)
    assert result.name == "PAIR"
    assert result.done == [VLit(1)]


def test_partial_data_passed_to_lambda():
    B = b()
    # (\f. f 99) (CONS 1)  =>  VData("CONS", [VLit(1), VLit(99)])
    t = B.app(
        B.lam("f", lambda: B.app(B.var("f"), B.lit(99))),
        B.app(B.var("CONS"), B.lit(1)))
    assert eval(t) == VData("CONS", [VLit(1), VLit(99)])


def test_partial_data_in_case():
    B = b()
    # let mk = PAIR 10 in case mk 20 of { PAIR a b -> (+) a b }  =>  30
    t = B.let("mk", lambda: B.app(B.var("PAIR"), B.lit(10)),
        lambda: B.case(B.app(B.var("mk"), B.lit(20)), [
            lambda: B.case_data("PAIR", ["a", "b"],
                lambda: B.app(B.app(B.var("+"), B.var("a")), B.var("b"))),
        ]))
    assert eval(t) == VLit(30)
