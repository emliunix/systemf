from __future__ import annotations

import pytest

from systemf.elab3.scc import (
    DuplicateKeyError,
    Node,
    SccGroup,
    SCC,
    build_graph,
    find_sccs,
    process_output,
    run_scc,
)


class TestBuildGraph:
    def test_empty(self):
        key_to_idx, nodes = build_graph([])
        assert key_to_idx == {}
        assert nodes == []

    def test_single_binding(self):
        key_to_idx, nodes = build_graph([("x = 1", "x", [])])
        assert key_to_idx == {"x": 0}
        assert len(nodes) == 1
        assert nodes[0].key == "x"
        assert nodes[0].payload == "x = 1"
        assert nodes[0].edges == []

    def test_independent_bindings(self):
        key_to_idx, nodes = build_graph([
            ("x = 1", "x", []),
            ("y = 2", "y", []),
            ("z = 3", "z", []),
        ])
        assert len(nodes) == 3
        assert all(node.edges == [] for node in nodes)
        assert key_to_idx == {"x": 0, "y": 1, "z": 2}

    def test_dependency_chain(self):
        key_to_idx, nodes = build_graph([
            ("z = x + y", "z", ["x", "y"]),
            ("y = 2", "y", []),
            ("x = 1", "x", []),
        ])
        assert nodes[0].key == "z"
        assert nodes[0].edges == ["x", "y"]
        assert nodes[1].edges == []
        assert nodes[2].edges == []

    def test_external_use_filtered(self):
        key_to_idx, nodes = build_graph([
            ("x = y + z", "x", ["y", "z"]),
        ])
        assert nodes[0].edges == []

    def test_duplicate_key_raises(self):
        with pytest.raises(DuplicateKeyError):
            build_graph([
                ("x = 1", "x", []),
                ("x = 2", "x", []),
            ])


class TestFindSCCs:
    def test_empty(self):
        sccs = find_sccs({}, [])
        assert sccs == []

    def test_single_node_no_edges(self):
        key_to_idx = {"x": 0}
        nodes = [Node(key="x", payload="x", edges=[])]
        sccs = find_sccs(key_to_idx, nodes)
        assert len(sccs) == 1
        assert len(sccs[0].nodes) == 1
        assert sccs[0].is_cyclic is False

    def test_self_recursive(self):
        key_to_idx = {"fact": 0}
        nodes = [Node(key="fact", payload="fact", edges=["fact"])]
        sccs = find_sccs(key_to_idx, nodes)
        assert len(sccs) == 1
        assert len(sccs[0].nodes) == 1
        assert sccs[0].is_cyclic is True

    def test_two_independent(self):
        key_to_idx = {"x": 0, "y": 1}
        nodes = [
            Node(key="x", payload="x", edges=[]),
            Node(key="y", payload="y", edges=[]),
        ]
        sccs = find_sccs(key_to_idx, nodes)
        assert len(sccs) == 2
        assert all(len(scc.nodes) == 1 for scc in sccs)
        assert all(not scc.is_cyclic for scc in sccs)

    def test_mutual_recursion_two_way(self):
        key_to_idx = {"even": 0, "odd": 1}
        nodes = [
            Node(key="even", payload="even", edges=["odd"]),
            Node(key="odd", payload="odd", edges=["even"]),
        ]
        sccs = find_sccs(key_to_idx, nodes)
        assert len(sccs) == 1
        assert len(sccs[0].nodes) == 2
        assert sccs[0].is_cyclic is True

    def test_mutual_recursion_three_way(self):
        key_to_idx = {"a": 0, "b": 1, "c": 2}
        nodes = [
            Node(key="a", payload="a", edges=["b"]),
            Node(key="b", payload="b", edges=["c"]),
            Node(key="c", payload="c", edges=["a"]),
        ]
        sccs = find_sccs(key_to_idx, nodes)
        assert len(sccs) == 1
        assert len(sccs[0].nodes) == 3
        assert sccs[0].is_cyclic is True

    def test_topological_order(self):
        key_to_idx = {"z": 0, "y": 1, "x": 2}
        nodes = [
            Node(key="z", payload="z", edges=["y"]),
            Node(key="y", payload="y", edges=["x"]),
            Node(key="x", payload="x", edges=[]),
        ]
        sccs = find_sccs(key_to_idx, nodes)
        assert len(sccs) == 3
        assert sccs[0].nodes[0].payload == "x"
        assert sccs[1].nodes[0].payload == "y"
        assert sccs[2].nodes[0].payload == "z"

    def test_mixed_independent_and_recursive(self):
        key_to_idx = {"x": 0, "y": 1, "z": 2, "w": 3}
        nodes = [
            Node(key="x", payload="x", edges=["y"]),
            Node(key="y", payload="y", edges=["x"]),
            Node(key="z", payload="z", edges=["x"]),
            Node(key="w", payload="w", edges=[]),
        ]
        sccs = find_sccs(key_to_idx, nodes)
        assert len(sccs) == 3
        cyclic = [scc for scc in sccs if scc.is_cyclic]
        assert len(cyclic) == 1
        assert len(cyclic[0].nodes) == 2

    def test_diamond_dependency(self):
        key_to_idx = {"d": 0, "b": 1, "c": 2, "a": 3}
        nodes = [
            Node(key="d", payload="d", edges=["b", "c"]),
            Node(key="b", payload="b", edges=["a"]),
            Node(key="c", payload="c", edges=["a"]),
            Node(key="a", payload="a", edges=[]),
        ]
        sccs = find_sccs(key_to_idx, nodes)
        payloads = [scc.nodes[0].payload for scc in sccs]
        assert payloads.index("a") < payloads.index("b")
        assert payloads.index("a") < payloads.index("c")
        assert payloads.index("b") < payloads.index("d")
        assert payloads.index("c") < payloads.index("d")


class TestProcessOutput:
    def test_single_non_recursive(self):
        sccs = [SCC(nodes=[Node(key="x", payload="x", edges=[])], is_cyclic=False)]
        groups = process_output(sccs)
        assert len(groups) == 1
        assert groups[0].bindings == ["x"]
        assert groups[0].is_recursive is False

    def test_recursive(self):
        sccs = [
            SCC(
                nodes=[
                    Node(key="even", payload="even", edges=["odd"]),
                    Node(key="odd", payload="odd", edges=["even"]),
                ],
                is_cyclic=True,
            )
        ]
        groups = process_output(sccs)
        assert len(groups) == 1
        assert set(groups[0].bindings) == {"even", "odd"}
        assert groups[0].is_recursive is True


class TestRunScc:
    def test_empty(self):
        assert run_scc([]) == []

    def test_independent(self):
        groups = run_scc([
            ("x = 1", "x", []),
            ("y = 2", "y", []),
        ])
        assert len(groups) == 2
        assert all(not g.is_recursive for g in groups)

    def test_self_recursive(self):
        groups = run_scc([
            ("factorial n = ...", "factorial", ["factorial"]),
        ])
        assert len(groups) == 1
        assert groups[0].is_recursive is True
        assert len(groups[0].bindings) == 1

    def test_mutual_recursion(self):
        groups = run_scc([
            ("even n = ...", "even", ["odd"]),
            ("odd n = ...", "odd", ["even"]),
        ])
        assert len(groups) == 1
        assert groups[0].is_recursive is True
        assert len(groups[0].bindings) == 2

    def test_complex(self):
        groups = run_scc([
            ("z = x + 1", "z", ["x"]),
            ("y = x + 1", "y", ["x"]),
            ("x = y + 1", "x", ["y"]),
            ("w = 42", "w", []),
        ])
        assert len(groups) == 3
        recursive = [g for g in groups if g.is_recursive]
        assert len(recursive) == 1
        assert len(recursive[0].bindings) == 2

    def test_topological_ordering(self):
        groups = run_scc([
            ("d = a + b + c", "d", ["a", "b", "c"]),
            ("c = a + b", "c", ["a", "b"]),
            ("b = a", "b", ["a"]),
            ("a = 1", "a", []),
        ])
        assert len(groups) == 4
        assert all(not g.is_recursive for g in groups)
        payloads = [g.bindings[0] for g in groups]
        assert payloads[0] == "a = 1"
        assert payloads[-1] == "d = a + b + c"
