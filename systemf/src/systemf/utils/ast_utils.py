"""AST utility functions for comparing and working with AST nodes."""

from dataclasses import fields, is_dataclass
from typing import Any


def _is_dataclass_instance(obj: object) -> bool:
    """Check if an object is a dataclass instance."""
    return hasattr(obj, "__dataclass_fields__")


def structural_equals(a: object, b: object) -> bool:
    """Compare two AST nodes for structural equality, ignoring identifiers.

    This is useful for testing that different syntax produces equivalent AST.
    Ignores location/source_loc (depends on source formatting) and unique
    (generated IDs that differ between runs).

    Recursively compares dataclass fields, skipping any field named
    'location', 'source_loc', or 'unique'.

    Examples:
        >>> from systemf.surface.types import SurfaceLit
        >>> from systemf.utils.location import Location
        >>> loc1 = Location("file1", 1, 1)
        >>> loc2 = Location("file2", 5, 10)
        >>> a = SurfaceLit(prim_type="Int", value=42, location=loc1)
        >>> b = SurfaceLit(prim_type="Int", value=42, location=loc2)
        >>> structural_equals(a, b)
        True

        >>> c = SurfaceLit(prim_type="Int", value=43, location=loc1)
        >>> structural_equals(a, c)
        False

    Args:
        a: First AST node
        b: Second AST node

    Returns:
        True if nodes are structurally equal (ignoring location/unique), False otherwise
    """
    # Different types are not equal
    if type(a) != type(b):
        return False

    # Both None or both same non-dataclass object
    if not _is_dataclass_instance(a) or not _is_dataclass_instance(b):
        return a == b

    # Compare dataclass fields, ignoring location/source_loc/unique fields
    a_fields = getattr(a, "__dataclass_fields__")
    for field_name in a_fields:
        if field_name in ("location", "source_loc", "unique", "loc"):
            continue

        val_a = getattr(a, field_name)
        val_b = getattr(b, field_name)

        # Recursively compare nested structures
        if isinstance(val_a, (list, tuple)):
            if len(val_a) != len(val_b):
                return False
            for item_a, item_b in zip(val_a, val_b):
                if not structural_equals(item_a, item_b):
                    return False
        elif isinstance(val_a, dict):
            if val_a != val_b:
                return False
        elif _is_dataclass_instance(val_a):
            if not structural_equals(val_a, val_b):
                return False
        else:
            if val_a != val_b:
                return False

    return True


# Backwards compatibility alias
equals_ignore_location = structural_equals
