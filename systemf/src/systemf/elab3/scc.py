"""
SCC components analysis (AI GEN)

Given a list of bindings, each binding potentially uses other bindings.
Define a graph of bindings, each node is a binding, and the edges are the "uses" relationship.

After SCC analysis, we take the topological sort output to construct nested let bindings
where each one is either a single binding or a group of mutually recursive bindings.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar('T')
K = TypeVar('K')


class DuplicateKeyError(Exception):
    """Raised when duplicate keys are found in input bindings."""
    pass


@dataclass
class Node(Generic[K, T]):
    """A node in the dependency graph.

    The key is the user's key type K (e.g., Name, str).
    Internal indices are managed separately by the algorithm.
    """
    key: K                # the user's key (e.g., Name, str)
    payload: T            # the binding
    edges: list[K]        # keys of dependencies


@dataclass
class SCC(Generic[K, T]):
    """A strongly connected component."""
    nodes: list[Node[K, T]]  # bindings in this component
    is_cyclic: bool          # True if mutual recursion or self-recursion


@dataclass
class SccGroup(Generic[T]):
    """Output group of bindings."""
    bindings: list[T]   # the actual binding payloads
    is_recursive: bool    # True if cyclic (needs fixpoint iteration)


def build_graph(bindings: list[tuple[T, K, list[K]]]) -> tuple[dict[K, int], list[Node[K, T]]]:
    """Build dependency graph from bindings.

    Input: list of (payload, def_key, uses_keys)
    Output: (key_to_idx mapping, nodes with user keys and user key edges)

    Raises:
        DuplicateKeyError: If duplicate def_keys are found
    """
    # Map: user key -> internal index (0, 1, 2, ...)
    # Check for duplicates
    key_to_idx: dict[K, int] = {}
    for i, (payload, def_key, uses) in enumerate(bindings):
        if def_key in key_to_idx:
            raise DuplicateKeyError(f"Duplicate key: {def_key}")
        key_to_idx[def_key] = i

    # Build nodes with user keys and user key edges
    nodes = []
    for payload, def_key, uses in bindings:
        # Filter to only include uses that are defined in this binding group
        edges = [use for use in uses if use in key_to_idx]
        nodes.append(Node(key=def_key, payload=payload, edges=edges))

    return key_to_idx, nodes


def find_sccs(key_to_idx: dict[K, int], nodes: list[Node[K, T]]) -> list[SCC[K, T]]:
    """Find strongly connected components using Tarjan's algorithm.

    Uses internal int indices for the algorithm but returns nodes with user keys.
    """
    n = len(nodes)

    # Build reverse mapping: idx -> node
    idx_to_node = {i: node for i, node in enumerate(nodes)}

    # Tarjan's algorithm state
    index_counter = [0]
    index: dict[int, int] = {}      # internal idx -> tarjan index
    lowlink: dict[int, int] = {}    # internal idx -> lowlink
    stack: list[int] = []           # stack of internal indices
    on_stack: set[int] = set()
    sccs: list[SCC[K, T]] = []

    def strongconnect(idx: int):
        """DFS for Tarjan's algorithm using internal indices."""
        index[idx] = index_counter[0]
        lowlink[idx] = index_counter[0]
        index_counter[0] += 1
        stack.append(idx)
        on_stack.add(idx)

        # Visit neighbors (convert user keys to internal indices)
        node = idx_to_node[idx]
        for neighbor_key in node.edges:
            neighbor_idx = key_to_idx[neighbor_key]
            if neighbor_idx not in index:
                # Unvisited - recurse
                strongconnect(neighbor_idx)
                lowlink[idx] = min(lowlink[idx], lowlink[neighbor_idx])
            elif neighbor_idx in on_stack:
                # Back edge
                lowlink[idx] = min(lowlink[idx], index[neighbor_idx])

        # If root of SCC, pop stack
        if lowlink[idx] == index[idx]:
            scc_indices = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc_indices.append(w)
                if w == idx:
                    break

            # Convert indices back to nodes
            scc_nodes = [idx_to_node[i] for i in scc_indices]

            # Determine if cyclic
            is_cyclic = (
                len(scc_nodes) > 1 or  # Multi-node = mutual recursion
                any(node.key in node.edges for node in scc_nodes)  # Self-loop
            )

            sccs.append(SCC(nodes=scc_nodes, is_cyclic=is_cyclic))

    # Run on all unvisited nodes
    for idx in range(n):
        if idx not in index:
            strongconnect(idx)

    return sccs


def process_output(sccs: list[SCC[K, T]]) -> list[SccGroup[T]]:
    """Convert SCCs to binding groups."""
    groups = []
    for scc in sccs:
        payloads = [node.payload for node in scc.nodes]
        groups.append(SccGroup(
            bindings=payloads,
            is_recursive=scc.is_cyclic
        ))
    return groups


def run_scc(bindings: list[tuple[T, K, list[K]]]) -> list[SccGroup[T]]:
    """Full pipeline from bindings to ordered groups.

    Raises:
        DuplicateKeyError: If duplicate def_keys are found
    """
    key_to_idx, nodes = build_graph(bindings)  # Step 2
    sccs = find_sccs(key_to_idx, nodes)         # Step 3
    return process_output(sccs)                  # Step 4
