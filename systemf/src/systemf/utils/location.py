"""Source locations for error reporting."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """Source code location with line and column info."""

    line: int
    column: int
    file: str | None = None

    def __str__(self) -> str:
        if self.file:
            return f"{self.file}:{self.line}:{self.column}"
        return f"line {self.line}, column {self.column}"


@dataclass(frozen=True)
class Span:
    """Source span from start to end location."""

    start: Location
    end: Location

    def __str__(self) -> str:
        if self.start.file:
            return f"{self.start.file}:{self.start.line}:{self.start.column}-{self.end.column}"
        return f"{self.start.line}:{self.start.column}-{self.end.column}"
