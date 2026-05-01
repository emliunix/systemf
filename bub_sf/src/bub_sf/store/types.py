"""ForkTapeStore types and interface."""

from __future__ import annotations

from typing import Protocol

from republic.tape.entries import TapeEntry
from republic.tape.query import TapeQuery
from republic.tape.store import AsyncTapeStore


class ForkTapeStore(AsyncTapeStore, Protocol):
    """Tape store with fork support."""

    async def create(self, name: str) -> None:
        """Create an empty tape. No-op if tape exists."""
        ...

    async def rename(self, old_name: str, new_name: str) -> None:
        """Rename a tape. Raises ValueError if old_name doesn't exist or new_name already exists."""
        ...

    async def fork(self, source_name: str, entry_id: int, target_name: str) -> None:
        """Fork source tape at the given entry_id."""
        ...


__all__ = ["ForkTapeStore", "TapeEntry", "TapeQuery"]
