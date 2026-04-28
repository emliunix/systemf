"""Utilities: locations, pretty printing, etc."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import TypeVar
from systemf.utils.location import Location, Span

__all__ = ["Location", "Span"]


T = TypeVar("T")
R = TypeVar("R")


@contextmanager
def capture_return(gen: Generator[T, None, R]) -> Generator[tuple[Generator[T, None, None], list[R]], None, None]:
    """Run a generator to completion and return its final return value."""
    res: list[R] = []
    def wrapper()-> Generator[T, None, None]:
        r = yield from gen
        res.append(r)
    yield (wrapper(), res)


def run_capture_return(gen: Generator[T, None, R]) -> tuple[list[T], R]:
    with capture_return(gen) as (gs, r):
        res = list(gs)
    return res, r[0]


A = TypeVar("A")
B = TypeVar("B")


def unzip(xs: list[tuple[A, B]]) -> tuple[list[A], list[B]]:
    return (
        [a for a, _ in xs],
        [b for _, b in xs]
    )
