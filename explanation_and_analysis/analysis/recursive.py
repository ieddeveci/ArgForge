from itertools import product
from engine.model import Argument
from engine.analysis import graph_analysis
from ..common import key


def recursive_families(e, max_candidates=5000, max_classes=300):
    classes = {key(a): a for a in e.arguments}
    unknown = {k: {"classification": "UNKNOWN_BOUNDED", "witness_scc": None} for k in classes}
    if not str(e.policy).startswith("QUOTIENT"):
        return {"status": "NOT_APPLICABLE", "classes": {}}
    if len(classes) > max_classes:
        return {"status": "ANALYSIS_LIMIT", "classes": unknown, "candidates": 0}
    pools = {}
    transfers = []
    edges = set()
    count = 0
    complete = True
    for k, a in classes.items():
        pools.setdefault(str(a.conclusion), []).append(a)
    for rule in e.theory.rules:
        for children in product(*(pools.get(str(x), []) for x in rule.antecedents)):
            if count >= max_candidates:
                complete = False
                break
            count += 1
            parent = Argument(rule.consequent, rule, children)
            pk = key(parent)
            if pk not in classes:
                raise ValueError(
                    "Result is not closed under the observed frozen signature transfer"
                )
            childkeys = [key(a) for a in children]
            transfers.append({"parent_class": pk, "child_classes": childkeys, "rule": rule.name})
            edges.update((c, pk) for c in childkeys)
        if not complete:
            break
    g = graph_analysis(classes, edges)
    cycles = [tuple(c) for c in g.sccs if len(c) > 1 or any((a, a) in edges for a in c)]
    witness = {k: c for c in cycles for k in c}
    while True:
        add = {b: witness[a] for a, b in edges if a in witness and b not in witness}
        if not add:
            break
        witness.update(add)
    result = {
        k: {
            "classification": (
                "INFINITE_FAMILY_CERTIFIED"
                if k in witness
                else "FINITE_FAMILY_CERTIFIED" if complete else "UNKNOWN_BOUNDED"
            ),
            "witness_scc": list(witness[k]) if k in witness else None,
        }
        for k in classes
    }
    return {
        "status": "OK" if complete else "ANALYSIS_LIMIT",
        "classes": result,
        "candidates": count,
        "transfer_edges": [list(x) for x in sorted(edges)],
        "transfers": transfers,
        "certificate_basis": "A cyclic class-transfer context can be pumped with other child representatives fixed; reachability propagates an infinite family. Finite classification requires complete transfer enumeration.",
    }
