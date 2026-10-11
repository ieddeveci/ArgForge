from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field


STATUS_COLOURS = {
    "IN": "forestgreen",
    "OUT": "firebrick",
    "UNDEC": "goldenrod",
    "JUSTIFIED": "forestgreen",
    "DEFENSIBLE": "steelblue",
    "UNDECIDED": "goldenrod",
    "OVERRULED": "firebrick",
}


def _quote(value):
    return json.dumps(str(value), ensure_ascii=False)


@dataclass(frozen=True)
class Graph:
    kind: str
    nodes: tuple
    edges: tuple
    directed: bool = True
    description: str = ""
    _index: dict = field(default=None, compare=False, repr=False)

    def __post_init__(self):
        from types import MappingProxyType

        object.__setattr__(self, "nodes", tuple(MappingProxyType(dict(n)) for n in self.nodes))
        object.__setattr__(self, "edges", tuple(MappingProxyType(dict(e)) for e in self.edges))
        ids = [n["id"] for n in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate node id")
        known = set(ids)
        for e in self.edges:
            if e["source"] not in known or e["target"] not in known:
                raise ValueError("edge endpoint outside node set: %r" % (e,))
        out = {i: [] for i in ids}
        inc = {i: [] for i in ids}
        for e in self.edges:
            out[e["source"]].append(e["target"])
            inc[e["target"]].append(e["source"])
        object.__setattr__(self, "_index", {"out": out, "in": inc})

    @property
    def node_ids(self):
        return [n["id"] for n in self.nodes]

    def successors(self, node):
        return list(self._index["out"][node])

    def predecessors(self, node):
        return list(self._index["in"][node])

    def adjacency(self):
        return {k: list(v) for k, v in self._index["out"].items()}

    def edge_set(self):
        return {(e["source"], e["target"]) for e in self.edges}

    def to_dict(self):
        return {
            "kind": self.kind,
            "directed": self.directed,
            "description": self.description,
            "nodes": [dict(n) for n in self.nodes],
            "edges": [dict(e) for e in self.edges],
        }

    def to_json(self, **kwargs):
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)

    def to_dot(self, label_key="label"):
        lines = ["digraph %s {" % _quote(self.kind), "  rankdir=BT;"]
        for n in self.nodes:
            attrs = {"label": n.get(label_key, n["id"])}
            colour = STATUS_COLOURS.get(n.get("label_status") or n.get("status"))
            if colour:
                attrs["color"] = colour
            lines.append(
                "  %s [%s];"
                % (_quote(n["id"]), ", ".join("%s=%s" % (k, _quote(v)) for k, v in attrs.items()))
            )
        for e in self.edges:
            extra = ", ".join(
                "%s=%s" % (k, _quote(v)) for k, v in e.items() if k not in ("source", "target")
            )
            lines.append(
                "  %s -> %s%s;"
                % (_quote(e["source"]), _quote(e["target"]), " [%s]" % extra if extra else "")
            )
        lines.append("}")
        return "\n".join(lines)

    def to_networkx(self):
        try:
            import networkx as nx
        except ImportError as exc:
            raise ImportError("to_networkx() needs the optional 'networkx' package") from exc
        graph = nx.MultiDiGraph() if self.directed else nx.MultiGraph()
        for n in self.nodes:
            graph.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
        for e in self.edges:
            graph.add_edge(
                e["source"],
                e["target"],
                **{k: v for k, v in e.items() if k not in ("source", "target")},
            )
        return graph

    def strongly_connected_components(self):
        index, low, on_stack, stack, result = {}, {}, set(), [], []
        counter = 0
        for root in self.node_ids:
            if root in index:
                continue
            work = [(root, iter(self._index["out"][root]))]
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            on_stack.add(root)
            while work:
                node, children = work[-1]
                advanced = False
                for child in children:
                    if child not in index:
                        index[child] = low[child] = counter
                        counter += 1
                        stack.append(child)
                        on_stack.add(child)
                        work.append((child, iter(self._index["out"][child])))
                        advanced = True
                        break
                    if child in on_stack:
                        low[node] = min(low[node], index[child])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    result.append(sorted(component))
        return sorted(result, key=lambda c: (-len(c), c))

    def has_odd_cycle(self, component):
        members = set(component)
        if len(members) == 1:
            (only,) = members
            return only in self._index["out"][only]
        colour = {}
        for start in sorted(members):
            if start in colour:
                continue
            colour[start] = 0
            queue = deque([start])
            while queue:
                node = queue.popleft()
                neighbours = self._index["out"][node] + self._index["in"][node]
                for other in neighbours:
                    if other not in members:
                        continue
                    if other not in colour:
                        colour[other] = 1 - colour[node]
                        queue.append(other)
                    elif colour[other] == colour[node]:
                        return True
        return False

    def weakly_connected_components(self):
        seen, result = set(), []
        for root in self.node_ids:
            if root in seen:
                continue
            component, queue = [], deque([root])
            seen.add(root)
            while queue:
                node = queue.popleft()
                component.append(node)
                for other in self._index["out"][node] + self._index["in"][node]:
                    if other not in seen:
                        seen.add(other)
                        queue.append(other)
            result.append(sorted(component))
        return sorted(result, key=lambda c: (-len(c), c))

    def longest_path_length(self):
        indegree = {n: len(self._index["in"][n]) for n in self.node_ids}
        queue = deque(n for n, d in indegree.items() if d == 0)
        depth = {n: 0 for n in self.node_ids}
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for child in self._index["out"][node]:
                depth[child] = max(depth[child], depth[node] + 1)
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if visited != len(self.nodes):
            return None
        return max(depth.values(), default=0)

    def distances_from(self, source, reverse=False):
        direction = self._index["in" if reverse else "out"]
        dist = {source: 0}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for other in direction[node]:
                if other not in dist:
                    dist[other] = dist[node] + 1
                    queue.append(other)
        return dist

    def metrics(self):
        n, m = len(self.nodes), len(self.edge_set())
        sccs = self.strongly_connected_components()
        cyclic = [c for c in sccs if len(c) > 1 or c[0] in self._index["out"][c[0]]]
        in_deg = {k: len(set(v)) for k, v in self._index["in"].items()}
        out_deg = {k: len(set(v)) for k, v in self._index["out"].items()}
        edges = self.edge_set()
        mutual = sum(1 for a, b in edges if a != b and (b, a) in edges) // 2
        return {
            "nodes": n,
            "edges": m,
            "density": (m / (n * (n - 1))) if n > 1 else 0.0,
            "self_loops": sorted(a for a, b in edges if a == b),
            "mutual_pairs": mutual,
            "sources": sorted(k for k, v in in_deg.items() if v == 0),
            "sinks": sorted(k for k, v in out_deg.items() if v == 0),
            "max_in_degree": max(in_deg.values(), default=0),
            "max_out_degree": max(out_deg.values(), default=0),
            "in_degree": in_deg,
            "out_degree": out_deg,
            "strongly_connected_components": len(sccs),
            "cyclic_components": len(cyclic),
            "largest_cyclic_component": max((len(c) for c in cyclic), default=0),
            "odd_cycle_components": sum(1 for c in cyclic if self.has_odd_cycle(c)),
            "even_cycle_only_components": sum(1 for c in cyclic if not self.has_odd_cycle(c)),
            "weak_components": len(self.weakly_connected_components()),
            "acyclic": not cyclic,
            "longest_path": self.longest_path_length(),
        }
