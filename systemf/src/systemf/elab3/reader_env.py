"""
Reader environment for name resolution.

Maps surface names (OccName) to resolved Names with provenance.

Design based on GHC's GlobalRdrEnv:
- ReaderEnv.table: dict[str, list[RdrElt]] (OccName -> RdrElts)
- RdrElt split into LocalRdrElt (no import_specs) and ImportRdrElt (has import_specs)
- Lookup filters by qualified/unqualified based on RdrName
"""

import itertools

from collections import defaultdict
from dataclasses import dataclass
from typing import override

from systemf.elab3.types.ast import ImportDecl

from .types import Name


# =============================================================================
# RdrName (how user wrote the reference)
# =============================================================================

@dataclass(frozen=True)
class UnqualName:
    """Unqualified name: foo"""
    name: str

    @override
    def __repr__(self):
        return self.name


@dataclass(frozen=True)
class QualName:
    """Qualified name: M.foo"""
    qual: str
    name: str

    @override
    def __repr__(self):
        return f"{self.qual}.{self.name}"


type RdrName = UnqualName | QualName


# =============================================================================
# ImportSpec (how a name entered scope)
# =============================================================================


@dataclass(frozen=True)
class ImportSpec:
    """How an imported name entered scope."""
    module_name: str        # Source module (e.g., "Data.Maybe")
    alias: str | None       # Import alias if `as M` used
    is_qual: bool           # Qualified-only?

    @staticmethod
    def from_decl(decl: ImportDecl) -> ImportSpec:
        return ImportSpec(
            module_name=decl.module,
            alias=decl.alias,
            is_qual=decl.qualified
        )


# =============================================================================
# RdrElt (one binding in scope)
# =============================================================================

# TODO: think the usecases of LocalRdrElt, doesn't seem to be necessary
@dataclass(frozen=True)
class LocalRdrElt:
    """Locally defined binding.

    Invariant: No import_specs (enforced by type system).
    """
    name: Name

    @staticmethod
    def create(name: Name) -> LocalRdrElt:
        return LocalRdrElt(name)


@dataclass(frozen=True)
class ImportRdrElt:
    """Imported binding.

    Invariant: import_specs is non-empty (at least one import path).
    """
    name: Name
    import_specs: list[ImportSpec]

    @staticmethod
    def create(name: Name, spec: ImportSpec) -> ImportRdrElt:
        return ImportRdrElt(name, [spec])


RdrElt = LocalRdrElt | ImportRdrElt


# =============================================================================
# ReaderEnv (GlobalRdrEnv equivalent)
# =============================================================================

class ReaderEnv:
    """Maps surface names to resolved Names.

    Key is unqualified surface name (OccName).
    Value is list of RdrElts (handles name clashes/ambiguity).
    """
    table: dict[str, list[RdrElt]]

    def __init__(self, table: dict[str, list[RdrElt]]):
        self.table = table

    def lookup(self, rdr_name: RdrName) -> list[RdrElt]:
        """Look up by RdrName, filtered for qual/unqualified access."""

        match rdr_name:
            case UnqualName(occ):
                occ_name = occ
            case QualName(_, occ):
                occ_name = occ
        return [
            elt
            for elt in self.table.get(occ_name, [])
            if _filter_by_spec(elt, rdr_name)
        ]

    def merge(self, other: ReaderEnv) -> ReaderEnv:
        """Merge two envs. Other shadows self (later bindings win)."""
        return ReaderEnv.from_elts(list(
            elt
            for elts in itertools.chain(
                    self.table.values(),
                    other.table.values())
            for elt in elts))

    def __add__(self, other: ReaderEnv) -> ReaderEnv:
        """env1 + env2 proxies to merge. Other shadows self."""
        return self.merge(other)

    def shadow(self, new_names: set[Name]) -> ReaderEnv:
        """Convert to qualified-only for names sharing surface names with new_names.

        Old interactive bindings become accessible only via qualified syntax.
        """
        new_surfaces = {n.surface for n in new_names}
        table = {
            occ_name: [
                _shadow_rdr_elt(elt) if elt.name.surface in new_surfaces else elt
                for elt in elts
            ]
            for (occ_name, elts) in self.table.items()
        }
        return ReaderEnv(table)

    @staticmethod
    def empty() -> ReaderEnv:
        """Create empty environment."""
        return ReaderEnv({})

    @staticmethod
    def from_elts(elts: list[RdrElt]) -> ReaderEnv:
        """Create environment from list of RdrElts."""
        """Build from list of RdrElts, merging same-Name elts."""
        table: dict[str, list[RdrElt]] = defaultdict(list)

        for elt in elts:
            occ = elt.name.surface

            # Check if same Name already exists (merge import specs)
            for (i, e) in enumerate(table[occ]):
                if elt.name.unique == e.name.unique:
                    table[occ][i] = _merge_rdr_elts(elt, e)
                    break
            else:
                table[occ].append(elt)

        return ReaderEnv(table)


# =============================================================================
# Helper functions (module level)
# =============================================================================

def _merge_rdr_elts(a: RdrElt, b: RdrElt) -> RdrElt:
    """Merge two RdrElts for the same Name.

    Used when same Name arrives via multiple import paths.
    """
    match (a, b):
        case (ImportRdrElt(name, specs_a), ImportRdrElt(_, specs_b)):
            # Union the import specs
            return ImportRdrElt(name, specs_a + specs_b)
        case _:
            raise ValueError(f"Only ImportRdrElts can be merged: {a}, {b}")


def _filter_by_spec(elt: RdrElt, rdr_name: RdrName):
    match (elt, rdr_name):
        case (ImportRdrElt(_, specs), QualName(qual, _)):
            if any(spec for spec in specs if spec.alias == qual or spec.module_name == qual):
                return True
        case (ImportRdrElt(_, specs), UnqualName()):
            # allow unqualified access
            if any(spec for spec in specs if not spec.is_qual):
                return True
        case (LocalRdrElt(), UnqualName()):
            return True
        case _:
            return False


def _shadow_rdr_elt(elt: RdrElt) -> RdrElt:
    """Convert RdrElt to qualified-only (for REPL shadowing).

    Old interactive bindings become accessible only via qualified name
    (e.g., Repl3.x).
    """
    match elt:
        case LocalRdrElt(name):
            # Local becomes import with fake qualified spec
            spec = ImportSpec(
                module_name=name.mod,
                alias=None,
                is_qual=True  # Qualified-only!
            )
            return ImportRdrElt(name, [spec])
        case ImportRdrElt(name, specs):
            # Convert all specs to qualified-only
            return ImportRdrElt(name, [
                # force qualified import spec
                ImportSpec(spec.module_name, spec.alias, True)
                for spec in specs
            ])
        case _:
            return elt
