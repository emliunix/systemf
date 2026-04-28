from collections.abc import Generator
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass
class Cons[T]:
    fst: T
    snd: Cons[T] | None

    def to_list(self) -> list[T]:
        def _go(xs: Cons[T]) -> Generator[T, None, None]:
            yield xs.fst
            if xs.snd:
                yield from _go(xs.snd)

        return list(_go(self))


def cons(x: T, xs: Cons[T] | None) -> Cons[T]:
    return Cons(x, xs)


def car(xs: Cons[T]) -> T:
    return xs.fst


def cdr(xs: Cons[T]) -> Cons[T] | None:
    return xs.snd


def lookup(xs: Cons[tuple[str, T]] | None, n: str) -> T | None:
    while xs:
        (k, v) = car(xs)
        if k == n:
            return v
        xs = cdr(xs)
    return None
