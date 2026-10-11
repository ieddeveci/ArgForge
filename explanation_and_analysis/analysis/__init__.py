from engine.analysis import analyze
from ..common import require, plain, key, identity
from ..explanation import explain_attacks


def graph_layers(e):
    base = analyze(
        e,
        max_nodes=max(1000, len(e.theory.language), len(e.arguments)),
        max_edges=max(10000, len(e.attacks), len(e.defeats)),
    )
    if base.status != "OK":
        raise ValueError(base.status)
    layers = {g.name: plain(g) for g in base.graphs}
    for name, g in layers.items():
        if name == "raw_attack":
            g["typed_witness_counts"] = {
                kind: sum(x.kind == kind for x in e.attacks)
                for kind in ("rebut", "undermine", "undercut")
            }
        components = g["sccs"]
        membership = {n: i for i, c in enumerate(components) for n in c}
        g["condensation"] = {
            "nodes": list(range(len(components))),
            "edges": sorted(
                {
                    (membership[a], membership[b])
                    for a, b in g["edges"]
                    if membership[a] != membership[b]
                }
            ),
        }
        g["largest_scc"] = max(map(len, components), default=0)
        g["cyclic_sccs"] = [
            i
            for i, c in enumerate(components)
            if len(c) > 1 or any(n in g["self_loops"] for n in c)
        ]
        if name == "rule_dependency":
            regions = []
            for i, c in enumerate(components):
                members = set(c)
                rules = [
                    r
                    for r in e.theory.rules
                    if str(r.consequent) in members or any(str(a) in members for a in r.antecedents)
                ]
                regions.append(
                    {
                        "id": i,
                        "members": c,
                        "rules": [r.name for r in rules],
                        "entry_rules": [
                            r.name
                            for r in rules
                            if str(r.consequent) in members
                            and any(str(a) not in members for a in r.antecedents)
                        ],
                        "exit_rules": [
                            r.name
                            for r in rules
                            if str(r.consequent) not in members
                            and any(str(a) in members for a in r.antecedents)
                        ],
                        "entry_literals": sorted(
                            {b for a, b in g["edges"] if a not in members and b in members}
                        ),
                        "exit_literals": sorted(
                            {a for a, b in g["edges"] if a in members and b not in members}
                        ),
                        "classes_with_rules_in_region": sorted(
                            {
                                key(a)
                                for a in e.arguments
                                if (a.strict_rules | a.defeasible_rules) & {r.name for r in rules}
                            }
                        ),
                    }
                )
            for region in regions:
                reachable = set(region["members"])
                while True:
                    new = reachable | {b for a, b in g["edges"] if a in reachable}
                    if new == reachable:
                        break
                    reachable = new
                region["reachable_classes_by_conclusion"] = sorted(
                    {key(a) for a in e.arguments if str(a.conclusion) in reachable}
                )
                region["reachability_scope"] = (
                    "Syntactic rule-dependency reachability; not proof that every rule is jointly applicable."
                )
            g["regions"] = regions
    return base, layers


def enrich(e, max_nodes=3000, max_edges=100000):
    require(e)
    if (
        len(e.arguments) > max_nodes
        or len(e.theory.language) > max_nodes
        or len(e.attacks) > max_edges
        or len(e.defeats) > max_edges
    ):
        return {
            "status": "ANALYSIS_LIMIT",
            "arguments": {},
            "claims": {},
            "graphs": {},
            "attacks": [],
            "defense": [],
            "quotient": {},
        }
    base, graphs = graph_layers(e)
    args = {a.id: a for a in e.arguments}
    incoming = {i: set() for i in args}
    outgoing = {i: set() for i in args}
    for a, b in e.defeats:
        incoming[b].add(a)
        outgoing[a].add(b)
    defense = []
    for a in sorted(args):
        for b in sorted(incoming[a]):
            for c in sorted(incoming[b]):
                if len(defense) >= max_edges:
                    return {
                        "status": "ANALYSIS_LIMIT",
                        "arguments": {},
                        "claims": {},
                        "graphs": {},
                        "attacks": [],
                        "defense": [],
                        "quotient": {},
                    }
                defense.append({"defender": c, "attacker": b, "defended": a})
    if len(defense) > max_edges:
        return {
            "status": "ANALYSIS_LIMIT",
            "arguments": {},
            "claims": {},
            "graphs": {},
            "attacks": [],
            "defense": [],
            "quotient": {},
        }
    defended_by = {}
    for x in defense:
        defended_by.setdefault(x["defender"], set()).add(x["defended"])
    ar = {}
    regions = graphs["rule_dependency"]["regions"]
    for old in base.arguments:
        a = args[old.id]
        d = plain(old)
        d.update(
            direct_subarguments=[x.id for x in a.direct_subarguments],
            all_subarguments=sorted(x.id for x in a.subarguments),
            arguments_defeated=sorted(outgoing[a.id]),
            arguments_defended=sorted(defended_by.get(a.id, ())),
            dependency_sccs_involved=[
                g["id"] for g in regions if (a.strict_rules | a.defeasible_rules) & set(g["rules"])
            ],
            representative_argument=a.id if str(e.policy).startswith("QUOTIENT") else None,
        )
        ar[a.id] = d
    claims = {}
    exts = list(e.extensions)
    existing = {c.claim: plain(c) for c in base.claims}
    for literal in sorted(map(str, e.theory.language)):
        supports = [a for a in e.arguments if str(a.conclusion) == literal]
        opposed = [a for a in e.arguments if (a.conclusion, literal) in e.theory.conflicts]
        ids = {a.id for a in supports}
        opp = {a.id for a in opposed}
        d = existing.get(
            literal,
            dict(
                claim=literal,
                supporting_arguments=[],
                counterclaim_arguments=sorted(opp),
                accepted_arguments_per_extension=[[] for _ in exts],
                credulous_acceptance=False,
                skeptical_acceptance=False if exts else None,
                single_skeptical_bearers=[] if exts else None,
                extension_family_empty=not exts,
                legacy_status=None,
                defeaters=[],
                defenders=[],
                attackers=[],
                preference_sensitive_support=[],
                cycle_dependent_support=[],
            ),
        )
        least = min((len(a.defeasible_rules) for a in supports), default=None)
        d.update(
            accepted_opposing_arguments_per_extension=[sorted(opp & set(x)) for x in exts],
            fewest_defeasible_support=sorted(
                a.id for a in supports if len(a.defeasible_rules) == least
            ),
            non_cycle_dependent_support=sorted(ids - set(d["cycle_dependent_support"])),
            opposing_claims=sorted({str(a.conclusion) for a in opposed}),
            support_count=len(ids),
            opposing_support_count=len(opp),
            supporting_classes=sorted({key(a) for a in supports}),
            opposing_classes=sorted({key(a) for a in opposed}),
            opposing_shortest_support=sorted(
                a.id for a in opposed if a.depth == min((x.depth for x in opposed), default=None)
            ),
            opposing_fewest_defeasible_support=sorted(
                a.id
                for a in opposed
                if len(a.defeasible_rules)
                == min((len(x.defeasible_rules) for x in opposed), default=None)
            ),
        )
        d.setdefault("shortest_support", [])
        d.setdefault("deepest_support", [])
        claims[literal] = d
    quotient = {}
    if str(e.policy).startswith("QUOTIENT"):
        for a in e.arguments:
            descriptor, subs = a.semantic_signature
            quotient[key(a)] = {
                "signature": plain(a.semantic_signature),
                "conclusion": str(a.conclusion),
                "TopRule": a.top_rule.name if a.top_rule else None,
                "TopKind": a.top_rule_kind,
                "LastDefRules": sorted(a.last_defeasible_rules),
                "DefRules": sorted(a.defeasible_rules),
                "OrdPremises": sorted(a.ordinary_premises),
                "SubDesc": plain(subs),
                "representative_argument": a.id,
                "cycle_dependent": ar[a.id]["cycle_dependence"],
                "dependency_sccs_involved": ar[a.id]["dependency_sccs_involved"],
                "population": "One representative is shown for a class of potentially many finite structured arguments.",
                "recursive_family": "NOT_INFERRED_FROM_REPRESENTATIVE_ALONE",
            }
    if quotient:
        from .recursive import recursive_families

        recursion = recursive_families(e)
        for k in quotient:
            quotient[k]["recursive_family"] = recursion["classes"][k]
            ar[quotient[k]["representative_argument"]]["recursive_family"] = recursion["classes"][k]
    else:
        recursion = {"status": "NOT_APPLICABLE", "classes": {}}
    return {
        "recursive_analysis": recursion,
        "status": "OK",
        "arguments": ar,
        "claims": claims,
        "graphs": graphs,
        "attacks": explain_attacks(e),
        "defense": defense,
        "quotient": quotient,
    }


def dialectical_neighborhood(result, argument, depth=3, max_nodes=300):
    if result.status != "OK":
        return {"status": result.status, "nodes": [], "layers": [], "complete": False}
    if not 0 <= depth <= 20:
        raise ValueError("depth must be 0..20")
    if argument not in result.arguments:
        raise KeyError(argument)
    seen = {argument}
    front = {argument}
    layers = []
    for distance in range(1, depth + 1):
        nxt = {a for a, b in result.evaluation.defeats if b in front}
        fresh = nxt - seen
        if len(seen | fresh) > max_nodes:
            return {
                "status": "NODE_LIMIT",
                "nodes": sorted(seen),
                "layers": layers,
                "complete": False,
            }
        layers.append(
            {
                "distance": distance,
                "nodes": sorted(fresh),
                "meaning": "incoming defeat walk; even distance is not a semantic acceptance certificate",
            }
        )
        seen |= fresh
        front = fresh
    return {"status": "OK", "nodes": sorted(seen), "layers": layers, "complete": True}
