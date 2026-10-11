from dataclasses import dataclass, fields
from .identity import freeze, canonical, digest
from .relations import compare, ORDERINGS


class Serializable:
    __slots__ = ()

    def __post_init__(self):
        for f in fields(self):
            object.__setattr__(self, f.name, freeze(getattr(self, f.name)))

    def to_dict(self):
        def convert(x):
            if hasattr(x, "to_dict"):
                return x.to_dict()
            if isinstance(x, tuple):
                return [convert(v) for v in x]
            return canonical(x)

        return {f.name: convert(getattr(self, f.name)) for f in fields(self)}


@dataclass(frozen=True, slots=True)
class GraphAnalysis(Serializable):
    name: str
    nodes: tuple
    edges: tuple
    self_loops: tuple
    in_degree: object
    out_degree: object
    sccs: tuple
    scc_membership: object
    weak_components: tuple
    cycle_members: tuple
    sources: tuple
    sinks: tuple

    def __post_init__(self):
        Serializable.__post_init__(self)


def graph_analysis(nodes, edges, name="graph"):
    nodes = tuple(sorted(set(nodes)))
    edges = tuple(sorted(set(edges)))
    universe = set(nodes)
    if any(a not in universe or b not in universe for a, b in edges):
        raise ValueError("edge endpoint outside graph")
    out = {a: set() for a in nodes}
    inc = {a: set() for a in nodes}
    for a, b in edges:
        out[a].add(b)
        inc[b].add(a)
    seen = set()
    finish = []
    for root in nodes:
        if root in seen:
            continue
        stack = [(root, False)]
        while stack:
            a, done = stack.pop()
            if done:
                finish.append(a)
                continue
            if a in seen:
                continue
            seen.add(a)
            stack.append((a, True))
            stack.extend((b, False) for b in sorted(out[a], reverse=True) if b not in seen)
    seen = set()
    sccs = []
    for root in reversed(finish):
        if root in seen:
            continue
        component = set()
        stack = [root]
        seen.add(root)
        while stack:
            a = stack.pop()
            component.add(a)
            for b in inc[a]:
                if b not in seen:
                    seen.add(b)
                    stack.append(b)
        sccs.append(tuple(sorted(component)))
    sccs = tuple(sorted(sccs))
    membership = {a: digest("s_", c) for c in sccs for a in c}
    weak = []
    seen = set()
    for root in nodes:
        if root in seen:
            continue
        component = set()
        stack = [root]
        seen.add(root)
        while stack:
            a = stack.pop()
            component.add(a)
            for b in inc[a] | out[a]:
                if b not in seen:
                    seen.add(b)
                    stack.append(b)
        weak.append(tuple(sorted(component)))
    loops = tuple(a for a in nodes if a in out[a])
    cyclic = set(loops) | {a for c in sccs if len(c) > 1 for a in c}
    return GraphAnalysis(
        name,
        nodes,
        edges,
        loops,
        {a: len(inc[a]) for a in nodes},
        {a: len(out[a]) for a in nodes},
        sccs,
        membership,
        tuple(sorted(weak)),
        tuple(sorted(cyclic)),
        tuple(a for a in nodes if not inc[a]),
        tuple(a for a in nodes if not out[a]),
    )


@dataclass(frozen=True, slots=True)
class ArgumentAnalysis(Serializable):
    id: str
    conclusion: str
    top_rule: str | None
    top_kind: str | None
    depth: int
    height: int
    direct_subargument_count: int
    recursive_subargument_count: int
    ordinary_premises: tuple
    axioms: tuple
    strict_rules: tuple
    defeasible_rules: tuple
    last_defeasible_rules: tuple
    strict: bool
    firm: bool
    raw_attackers: tuple
    attackers_by_type: object
    defeaters: tuple
    defenders: tuple
    defended_attackers: tuple
    defeat_scc: str
    cycle_dependence: bool
    quotient_class: str | None
    signature: tuple

    def __post_init__(self):
        Serializable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class ClaimAnalysis(Serializable):
    claim: str
    supporting_arguments: tuple
    counterclaim_arguments: tuple
    accepted_arguments_per_extension: tuple
    credulous_acceptance: bool
    skeptical_acceptance: bool | None
    single_skeptical_bearers: tuple | None
    extension_family_empty: bool
    legacy_status: str | None
    attackers: tuple
    defeaters: tuple
    defenders: tuple
    shortest_support: tuple
    deepest_support: tuple
    preference_sensitive_support: tuple
    cycle_dependent_support: tuple
    quotient_dependent_support: tuple | None


@dataclass(frozen=True, slots=True)
class AnalysisResult(Serializable):
    status: str
    arguments: tuple = ()
    claims: tuple = ()
    graphs: tuple = ()
    error: str | None = None


def analyze(result, *, literal_reference=None, max_nodes=1000, max_edges=10000):
    if result.status not in ("OK", "REFERENCE_LIMIT"):
        return AnalysisResult(result.status, error="evaluation is incomplete; no analysis computed")
    if (
        len(result.arguments) > max_nodes
        or len(result.attacks) > max_edges
        or len(result.defeats) > max_edges
    ):
        return AnalysisResult("ANALYSIS_LIMIT", error="analysis graph budget exceeded")
    from .resources import consume

    consume(
        "analysis_work",
        len(result.arguments) ** 2 + len(result.attacks) * 4 + len(result.defeats),
        "ANALYSIS_LIMIT",
    )
    t = result.theory
    args = result.arguments
    ids = result.ids
    dependency_edges = {(str(a), str(r.consequent)) for r in t.rules for a in r.antecedents}
    if len(t.language) > max_nodes or len(dependency_edges) > max_edges:
        return AnalysisResult("ANALYSIS_LIMIT", error="dependency graph budget exceeded")
    dg = graph_analysis(map(str, t.language), dependency_edges, "rule_dependency")
    ag = graph_analysis(
        ids.values(),
        {(ids[a.attacker], ids[a.target]) for a in result.attacks},
        "raw_attack",
    )
    fg = graph_analysis(ids.values(), result.defeats, "defeat")
    incoming = {i: set() for i in ids.values()}
    raw = {i: {k: set() for k in ("rebut", "undermine", "undercut")} for i in ids.values()}
    for x, y in result.defeats:
        incoming[y].add(x)
    for a in result.attacks:
        raw[ids[a.target]][a.kind].add(ids[a.attacker])
    cyclic_rules = {
        r.name
        for r in t.rules
        if any(
            str(a) in dg.cycle_members
            and dg.scc_membership[str(a)] == dg.scc_membership[str(r.consequent)]
            for a in r.antecedents
        )
    }
    arecords = []
    for a in args:
        i = ids[a]
        attackers = incoming[i]
        defenders = set().union(*(incoming[x] for x in attackers)) if attackers else set()
        covered = {x for x in attackers if incoming[x]}
        arecords.append(
            ArgumentAnalysis(
                i,
                str(a.conclusion),
                a.top_rule.name if a.top_rule else None,
                a.top_rule_kind,
                a.depth,
                a.height,
                len(a.direct_subarguments),
                len(a.subarguments) - 1,
                tuple(sorted(a.ordinary_premises)),
                tuple(sorted(a.axioms)),
                tuple(sorted(a.strict_rules)),
                tuple(sorted(a.defeasible_rules)),
                tuple(sorted(a.last_defeasible_rules)),
                a.is_strict,
                a.is_firm,
                tuple(sorted(set().union(*raw[i].values()))),
                {k: tuple(sorted(v)) for k, v in raw[i].items()},
                tuple(sorted(attackers)),
                tuple(sorted(defenders)),
                tuple(sorted(covered)),
                fg.scc_membership[i],
                bool(cyclic_rules & (a.strict_rules | a.defeasible_rules)),
                a.signature_id if str(result.policy).startswith("QUOTIENT") else None,
                a.semantic_signature,
            )
        )
    amap = {a.id: a for a in arecords}
    byclaim = {}
    for a in args:
        byclaim.setdefault(str(a.conclusion), []).append(a)
    sensitive = set()
    for event in result.attacks:
        if event.preference_independent:
            continue
        outcomes = {compare(t, event.attacker, event.witness, mode)["less"] for mode in ORDERINGS}
        if len(outcomes) > 1:
            sensitive.update((ids[event.attacker], ids[event.target]))
    reference_classes = None
    if literal_reference is not None:
        if (
            literal_reference.status != "OK"
            or literal_reference.policy not in ("P_LITERAL", "EXACT")
            or literal_reference.theory != t
        ):
            raise ValueError("literal reference must be complete P_LITERAL on the same theory")
        reference_classes = {a.semantic_signature for a in literal_reference.arguments}
    claims = []
    for c, support in sorted(byclaim.items()):
        bearers = {ids[a] for a in support}
        accepted = tuple(tuple(sorted(bearers & e)) for e in result.extensions)
        empty = not result.extensions
        shared = (
            set.intersection(*(set(e) & bearers for e in result.extensions)) if not empty else None
        )
        shortest = min(a.depth for a in support)
        deepest = max(a.depth for a in support)

        def collect(field):
            return tuple(sorted({x for i in bearers for x in getattr(amap[i], field)}))

        claims.append(
            ClaimAnalysis(
                c,
                tuple(sorted(bearers)),
                tuple(sorted(ids[a] for a in args if (a.conclusion, c) in t.conflicts)),
                accepted,
                any(accepted),
                None if empty else all(bool(e) for e in accepted),
                None if empty else tuple(sorted(shared)),
                empty,
                result.statuses.get(c),
                collect("raw_attackers"),
                collect("defeaters"),
                collect("defenders"),
                tuple(sorted(ids[a] for a in support if a.depth == shortest)),
                tuple(sorted(ids[a] for a in support if a.depth == deepest)),
                tuple(sorted(bearers & sensitive)),
                tuple(sorted(i for i in bearers if amap[i].cycle_dependence)),
                (
                    None
                    if reference_classes is None
                    else tuple(
                        sorted(
                            ids[a] for a in support if a.semantic_signature not in reference_classes
                        )
                    )
                ),
            )
        )
    return AnalysisResult(
        result.status,
        tuple(sorted(arecords, key=lambda a: a.id)),
        tuple(claims),
        (dg, ag, fg),
    )
