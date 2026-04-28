"""Tests for the `multiple` combinator in typecheck_expr2.

Verifies that `multiple` calls `fun` for each element in left-to-right order,
threading the continuation (cb) through, and collecting results in order.
"""

import pytest

from systemf.elab3.typecheck_expr import multiple


# =============================================================================
# Helpers
# =============================================================================

def tracking_fun(log: list[str]):
    """Return a `fun` that logs calls and doubles each input as its output."""
    def fun(x: int, cb):
        log.append(f"enter:{x}")
        t = x * 2
        r = cb()
        log.append(f"exit:{x}")
        return t, r
    return fun


# =============================================================================
# Tests
# =============================================================================


class TestMultipleOrdering:

    def test_empty_input(self):
        """Empty xs should just call cb and return empty ts."""
        log: list[str] = []
        ts, res = multiple([], tracking_fun(log), lambda: "done")
        assert ts == []
        assert res == "done"

    def test_single_element(self):
        ts, res = multiple([10], tracking_fun([]), lambda: "end")
        assert ts == [20]
        assert res == "end"

    def test_multiple_elements_results_in_order(self):
        ts, res = multiple([1, 2, 3], tracking_fun([]), lambda: "fin")
        assert ts == [2, 4, 6]
        assert res == "fin"

    def test_call_order_is_left_to_right(self):
        """fun is called left-to-right (1 enters before 2 enters before 3)."""
        log: list[str] = []
        multiple([1, 2, 3], tracking_fun(log), lambda: "x")
        # The enter events should appear in input order
        enters = [e for e in log if e.startswith("enter:")]
        assert enters == ["enter:1", "enter:2", "enter:3"]

    def test_continuation_nesting(self):
        """Each fun wraps the next one's continuation, so exits are in reverse."""
        log: list[str] = []
        multiple([1, 2, 3], tracking_fun(log), lambda: "x")
        exits = [e for e in log if e.startswith("exit:")]
        assert exits == ["exit:3", "exit:2", "exit:1"]

    def test_cb_return_value_threads_through(self):
        """The innermost cb's return value propagates back as the final result."""
        sentinel = object()
        _, res = multiple([1, 2], tracking_fun([]), lambda: sentinel)
        assert res is sentinel


class TestMultipleWithDifferentTypes:

    def test_string_inputs(self):
        def fun(s: str, cb):
            r = cb()
            return s.upper(), r
        ts, res = multiple(["a", "b", "c"], fun, lambda: 42)
        assert ts == ["A", "B", "C"]
        assert res == 42

    def test_fun_can_transform_cb_result(self):
        """fun sees the result from cb and can use it (though multiple
        only captures the `t` part, not the modified `r`)."""
        accumulator: list[int] = []

        def fun(x: int, cb):
            r = cb()
            accumulator.append(x)
            return x, r

        ts, res = multiple([10, 20, 30], fun, lambda: "base")
        assert ts == [10, 20, 30]
        # accumulator is filled in continuation (innermost first) order
        assert accumulator == [30, 20, 10]
        assert res == "base"
