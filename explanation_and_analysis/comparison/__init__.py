from dataclasses import asdict
from itertools import combinations, product
from ..common import key, identity, plain
from ..experiments import Config, research_evaluate, public_record


def claim_value(c):
    return (
        None
        if c is None
        else (
            c["credulous_acceptance"],
            c["skeptical_acceptance"],
            c["legacy_status"],
            c["extension_family_empty"],
        )
    )


def compare_claims(result, left, right):
    if result.status != "OK":
        return {"status": "INCOMPLETE_COMPARISON", "missing": [result.status]}
    return {
        "status": "OK",
        "left": result.claims[left],
        "right": result.claims[right],
        "cross_attacks": [
            a
            for a in result.attacks
            if (
                a["attacker"] in result.claims[left]["supporting_arguments"]
                and a["target"] in result.claims[right]["supporting_arguments"]
            )
            or (
                a["attacker"] in result.claims[right]["supporting_arguments"]
                and a["target"] in result.claims[left]["supporting_arguments"]
            )
        ],
        "interpretation": "Counts describe support multiplicity, not argumentative strength.",
    }


def projection(r):
    ids = {
        a.id: (a.id if r.evaluation.policy == "EXACT" else key(a)) for a in r.evaluation.arguments
    }
    return {
        "arguments": set(ids.values()),
        "defeats": {(ids[a], ids[b]) for a, b in r.evaluation.defeats},
        "extensions": {tuple(sorted(ids[i] for i in e)) for e in r.evaluation.extensions},
        "attacks": {tuple(a["invariant"]) for a in r.attacks},
    }


def compare_results(left, right):
    if left.metadata["theory_hash"] != right.metadata["theory_hash"] and not (
        isinstance(left.metadata.get("submitted_source"), str)
        and left.metadata["submitted_source"] == right.metadata.get("submitted_source")
    ):
        raise ValueError("Configuration comparison requires the same canonical theory")
    if left.status != "OK" or right.status != "OK":
        return {
            "status": "INCOMPLETE_COMPARISON",
            "left_status": left.status,
            "right_status": right.status,
            "missing": [r.config.id for r in (left, right) if r.status != "OK"],
        }
    a, b = projection(left), projection(right)
    d = {"status": "OK", "left": asdict(left.config), "right": asdict(right.config)}
    for field in a:
        d[field] = {
            "added": plain(b[field] - a[field]),
            "removed": plain(a[field] - b[field]),
        }
    au = set().union(*(set(e) for e in a["extensions"])) if a["extensions"] else set()
    bu = set().union(*(set(e) for e in b["extensions"])) if b["extensions"] else set()
    d["credulously_accepted_arguments"] = {
        "added": sorted(bu - au),
        "removed": sorted(au - bu),
    }
    d["claims"] = {
        c: {
            "left": claim_value(left.claims.get(c)),
            "right": claim_value(right.claims.get(c)),
        }
        for c in sorted(set(left.claims) | set(right.claims))
        if claim_value(left.claims.get(c)) != claim_value(right.claims.get(c))
    }
    ax = {tuple(x["invariant"]): x for x in left.attacks}
    bx = {tuple(x["invariant"]): x for x in right.attacks}
    changes = []
    for k in sorted(ax.keys() & bx.keys()):
        x, y = ax[k], bx[k]
        if (
            x["preference"]["less"] != y["preference"]["less"]
            or x["succeeds_as_defeat"] != y["succeeds_as_defeat"]
        ):
            changes.append(
                {
                    "attack_invariant": k,
                    "left_comparison": x["preference"],
                    "right_comparison": y["preference"],
                    "left_defeat": x["succeeds_as_defeat"],
                    "right_defeat": y["succeeds_as_defeat"],
                }
            )
    d["comparison_witnesses"] = changes
    d["earliest_divergence"] = next(
        (n for n in ["arguments", "attacks"] if a[n] != b[n]),
        (
            "preference_comparison"
            if changes
            else (
                "defeat"
                if a["defeats"] != b["defeats"]
                else (
                    "extension_family"
                    if a["extensions"] != b["extensions"]
                    else "claim_projection" if d["claims"] else None
                )
            )
        ),
    )
    d["compact_difference_witness"] = {
        "comparison": changes[:1],
        "defeat_added": d["defeats"]["added"][:1],
        "defeat_removed": d["defeats"]["removed"][:1],
        "extension_added": d["extensions"]["added"][:1],
        "extension_removed": d["extensions"]["removed"][:1],
        "changed_claim": next(iter(d["claims"]), None),
        "causal_status": "Observed first differences; no single-edge counterfactual necessity or globally minimal theory edit is asserted.",
    }
    return public_record(d)


class Study:
    def __init__(self, results):
        self.results = tuple(results)
        known = {
            r.metadata["submitted_source"]: r.metadata
            for r in self.results
            if r.metadata.get("canonical_theory") is not None
            and isinstance(r.metadata.get("submitted_source"), str)
        }
        for r in self.results:
            m = known.get(r.metadata.get("submitted_source"))
            if r.metadata.get("canonical_theory") is None and m is not None:
                r.metadata.update(
                    theory_hash=m["theory_hash"],
                    canonical_theory=m["canonical_theory"],
                    theory_hash_scope="canonical theory from identical submitted source",
                )
        hashes = {r.metadata["theory_hash"] for r in self.results}
        if len(hashes) > 1:
            raise ValueError("one theory per configuration study")
        if len({r.config.id for r in self.results}) != len(self.results):
            raise ValueError("duplicate configurations")

    def matrix(self):
        return [
            {
                "configuration_id": r.config.id,
                **asdict(r.config),
                "status": r.status,
                "claim": c,
                "claim_result": claim_value(v),
                "extensions": (
                    len(r.evaluation.extensions) if r.evaluation.status == "OK" else None
                ),
                "theory_hash": r.metadata["theory_hash"],
                "engine_version": r.metadata["engine_version"],
                "solver_version": r.metadata["solver_version"],
                "timestamp": r.metadata["timestamp"],
                "resource_policy": r.metadata["resource_policy"],
                "provenance": r.metadata["provenance"],
            }
            for r in self.results
            for c, v in (r.claims.items() if r.claims else [(None, None)])
        ]

    def robustness(self):
        missing = [r.config.id for r in self.results if r.status != "OK"]
        good = [r for r in self.results if r.status == "OK"]
        out = {}
        axes = {
            "semantics": ("SEMANTICALLY_ROBUST", "SEMANTICS_SENSITIVE"),
            "ordering": ("ORDERING_ROBUST", "ORDERING_SENSITIVE"),
            "lifting": ("LIFTING_ROBUST", "LIFTING_SENSITIVE"),
            "policy": ("CYCLICALLY_ROBUST", "CYCLIC_POLICY_SENSITIVE"),
            "conflict_free": (
                "CONFLICT_FREENESS_ROBUST",
                "CONFLICT_FREENESS_SENSITIVE",
            ),
            "transposition": ("TRANSPOSITION_ROBUST", "TRANSPOSITION_SENSITIVE"),
        }
        for c in sorted({c for r in good for c in r.claims}):
            values = [claim_value(r.claims.get(c)) for r in good]
            same = len(set(values)) == 1
            labels = [
                (
                    "FULLY_ROBUST"
                    if same and not missing
                    else (
                        "ROBUST_ON_COMPLETED_CONFIGURATIONS" if same else "CONFIGURATION_SENSITIVE"
                    )
                )
            ]
            evidence = {}
            for axis, (robust, sensitive) in axes.items():
                pairs = [
                    (a, b)
                    for a, b in combinations(good, 2)
                    if getattr(a.config, axis) != getattr(b.config, axis)
                    and all(getattr(a.config, k) == getattr(b.config, k) for k in axes if k != axis)
                ]
                changed = [
                    (a.config.id, b.config.id)
                    for a, b in pairs
                    if claim_value(a.claims.get(c)) != claim_value(b.claims.get(c))
                ]
                label = (
                    sensitive
                    if changed
                    else (
                        robust
                        if pairs and not missing
                        else (
                            axis.upper() + "_ROBUST_ON_COMPLETED_PAIRS"
                            if pairs
                            else axis.upper() + "_NOT_COMPARED"
                        )
                    )
                )
                labels.append(label)
                evidence[axis] = {"pairs": len(pairs), "changed_pairs": changed}
            pp = [
                (a, b)
                for a, b in combinations(good, 2)
                if (a.config.ordering, a.config.lifting) != (b.config.ordering, b.config.lifting)
                and a.config.semantics == b.config.semantics
                and a.config.policy == b.config.policy
                and a.config.conflict_free == b.config.conflict_free
                and a.config.transposition == b.config.transposition
            ]
            labels.append(
                "PREFERENCE_SENSITIVE"
                if any(claim_value(a.claims.get(c)) != claim_value(b.claims.get(c)) for a, b in pp)
                else (
                    "PREFERENCE_ROBUST" if pp and not missing else "PREFERENCE_NOT_FULLY_COMPARED"
                )
            )
            out[c] = {
                "labels": labels,
                "missing_configurations": missing,
                "completed_configurations": [r.config.id for r in good],
                "axis_evidence": evidence,
                "result_definition": [
                    "credulous",
                    "skeptical_claim",
                    "legacy",
                    "extension_family_empty",
                ],
            }
        return out

    def to_dict(self):
        return public_record(
            {
                "schema_version": "study-2",
                "results": [r.to_dict() for r in self.results],
                "matrix": self.matrix(),
                "robustness": self.robustness(),
                "missing_configurations": [r.config.id for r in self.results if r.status != "OK"],
            }
        )


def configuration_grid(semantics=None, policies=("QUOTIENT",)):
    from engine.protocol import SEMANTICS

    return [
        Config(s, o, l, p)
        for s, o, l, p in product(
            sorted(SEMANTICS) if semantics is None else semantics,
            ("last_link", "weakest_link"),
            ("elitist", "democratic"),
            policies,
        )
    ]


def compare_configurations(theory, configs, limits=None):
    return Study([research_evaluate(theory, c, limits) for c in configs])


def compare_semantics(
    theory, left, right, ordering="last_link", lifting=None, limits=None, *, set_ordering=None
):
    lifting = Config(ordering=ordering, lifting=lifting, set_ordering=set_ordering).lifting
    s = compare_configurations(
        theory,
        [Config(left, ordering, lifting), Config(right, ordering, lifting)],
        limits,
    )
    return compare_results(*s.results)


def compare_policies(
    theory,
    left="P_LITERAL",
    right="QUOTIENT",
    semantics="grounded",
    ordering="last_link",
    lifting=None,
    limits=None,
    *,
    set_ordering=None
):
    lifting = Config(ordering=ordering, lifting=lifting, set_ordering=set_ordering).lifting
    s = compare_configurations(
        theory,
        [
            Config(semantics, ordering, lifting, left),
            Config(semantics, ordering, lifting, right),
        ],
        limits,
    )
    return compare_results(*s.results)


def viewpoints(result):
    if result.status != "OK":
        return {"status": result.status, "complete": False}
    e = result.evaluation
    sets = [set(x) for x in e.extensions]
    claims = [{str(a.conclusion) for a in e.arguments if a.id in x} for x in sets]
    union = lambda xs: set().union(*xs) if xs else set()
    inter = lambda xs: set.intersection(*xs) if xs else set()
    return {
        "status": "OK",
        "complete": True,
        "semantics": result.config.semantics,
        "extension_count": len(sets),
        "common_arguments": sorted(inter(sets)),
        "some_arguments": sorted(union(sets)),
        "divergent_arguments": sorted(union(sets) - inter(sets)),
        "common_claims": sorted(inter(claims)),
        "some_claims": sorted(union(claims)),
        "divergent_claims": sorted(union(claims) - inter(claims)),
        "empty_family": not sets,
        "empty_family_explanation": (
            "No conflict-free position defeats every argument outside it."
            if not sets and result.config.semantics == "stable"
            else None
        ),
    }


def consensus_context(study):
    by = {r.config.semantics: r for r in study.results}
    out = {}
    if len(by) != len(study.results):
        raise ValueError("Select one ordering/lifting/policy for consensus context")
    for sem, context in [("ideal", "preferred"), ("eager", "semistable")]:
        if sem in by and context in by:
            a, b = by[sem], by[context]
            if (a.config.ordering, a.config.lifting, a.config.policy) != (
                b.config.ordering,
                b.config.lifting,
                b.config.policy,
            ):
                raise ValueError("consensus context configurations must match")
            out[sem] = {
                "result": viewpoints(a),
                "family_context": viewpoints(b),
                "claim_survival": {c: v["skeptical_acceptance"] for c, v in b.claims.items()},
            }
    return out


def explain_change(left, right, claim, max_candidates=8, limits=None):
    from engine import Theory, Fact, ContraryRelation, Limits
    from argforge_platform import evaluate
    from engine.evaluation import project_claim

    d = compare_results(left, right)
    if d["status"] != "OK":
        return d
    if claim not in d["claims"]:
        return {"status": "NO_CLAIM_CHANGE", "claim": claim}
    if left.config.semantics != right.config.semantics:
        return {
            "status": "NOT_APPLICABLE",
            "reason": "Different semantics: report exact family differences, not edge causation.",
            "difference": d,
        }
    a, b = projection(left), projection(right)
    if a["arguments"] != b["arguments"] or len(a["arguments"]) > 60:
        return {
            "status": "EXPLANATION_LIMIT",
            "reason": "Single-edge intervention requires identical class universe of at most 60.",
            "difference": d,
        }
    if not 1 <= max_candidates <= 20:
        raise ValueError("max_candidates must be 1..20")
    keys = sorted(a["arguments"])
    names = {k: "node_" + str(i) for i, k in enumerate(keys)}
    back = {v: k for k, v in names.items()}
    conc = {
        (x.id if left.evaluation.policy == "EXACT" else key(x)): str(x.conclusion)
        for x in left.evaluation.arguments
    }
    target = claim_value(right.claims[claim])
    attempts = []
    for action, edge in (
        [("add", x) for x in sorted(b["defeats"] - a["defeats"])]
        + [("remove", x) for x in sorted(a["defeats"] - b["defeats"])]
    )[:max_candidates]:
        edges = set(a["defeats"])
        edges.add(edge) if action == "add" else edges.remove(edge)
        theory = Theory(
            tuple(Fact(names[k]) for k in keys),
            contraries=tuple(ContraryRelation(names[x], names[y]) for x, y in sorted(edges)),
        )
        ev = evaluate(
            theory,
            semantics=left.config.semantics,
            limits=limits or Limits(wall_seconds=5, solver_models=512, extensions=512),
        )
        if ev.status != "OK":
            attempts.append({"action": action, "edge": edge, "status": ev.status})
            continue
        m = {x.id: back[str(x.conclusion)] for x in ev.arguments}
        ext = [{m[i] for i in e} for e in ev.extensions]
        bear = {k for k in keys if conc[k] == claim}
        accepted = [bool(e & bear) for e in ext]
        defeaters = {}
        for x, y in edges:
            defeaters.setdefault(y, set()).add(x)
        value = (
            any(accepted),
            all(accepted) if ext else None,
            (project_claim(bear, [frozenset(e) for e in ext], defeaters) if ext else None),
            not ext,
        )
        attempts.append(
            {
                "action": action,
                "edge": edge,
                "status": "OK",
                "claim_value": value,
                "reproduces_right_claim": value == target,
                "interpretation": "This single AF edge intervention is sufficient relative to the left graph; necessity and minimal source edits are not established.",
            }
        )
    return {
        "status": (
            "OK" if all(x["status"] == "OK" for x in attempts) else "INCOMPLETE_EXPLANATION"
        ),
        "claim": claim,
        "tested": attempts,
        "unexamined_candidates": max(0, len(a["defeats"] ^ b["defeats"]) - len(attempts)),
        "difference": d,
    }
