from dataclasses import asdict
from .model import (
    Theory,
    Fact,
    Rule,
    RulePreference,
    PremisePreference,
    ContraryRelation,
    Argument,
)
from .relations import Attack
from .identity import canonical

SCHEMA_VERSION = "1.1"


def theory_to_dict(t):
    return {
        k: sorted(
            [canonical(asdict(x)) for x in getattr(t, k)],
            key=lambda v: repr(sorted(v.items())),
        )
        for k in (
            "facts",
            "rules",
            "rule_preferences",
            "premise_preferences",
            "contraries",
        )
    }


def theory_from_dict(d):
    from .protocol import validate_theory_data

    validate_theory_data(d)
    return Theory(
        tuple(Fact(**v) for v in d["facts"]),
        tuple(Rule(**v) for v in d["rules"]),
        tuple(RulePreference(**v) for v in d["rule_preferences"]),
        tuple(PremisePreference(**v) for v in d["premise_preferences"]),
        tuple(ContraryRelation(**v) for v in d["contraries"]),
    )


def evaluation_to_dict(r, include_timings=False):
    nodes = {}
    for a in r.arguments:
        for s in a.subarguments:
            if s.id in nodes and nodes[s.id] != s:
                raise ValueError("argument ID collision")
            nodes[s.id] = s
    data = {
        "schema_version": SCHEMA_VERSION,
        "status": r.status,
        "error": r.error,
        "policy": r.policy,
        "configuration": dict(r.configuration),
        "resource": canonical(r.resource),
        "theory": theory_to_dict(r.theory) if r.theory else None,
        "arguments": sorted(a.id for a in r.arguments),
        "argument_nodes": [
            {
                "id": a.id,
                "conclusion": str(a.conclusion),
                "top_rule": a.top_rule.name if a.top_rule else None,
                "premise": asdict(a.premise) if a.premise else None,
                "children": [s.id for s in a.direct_subarguments],
                "signature": canonical(a.semantic_signature),
                "signature_id": a.signature_id,
                "depth": a.depth,
            }
            for a in sorted(nodes.values(), key=lambda a: (a.depth, a.id))
        ],
        "attacks": [
            {
                "id": a.id,
                "attacker": a.attacker.id,
                "target": a.target.id,
                "witness": a.witness.id,
                "kind": a.kind,
                "element": a.element,
                "preference_independent": a.preference_independent,
            }
            for a in sorted(r.attacks, key=lambda a: a.id)
        ],
        "defeats": [
            {
                "id": d.id,
                "attacker": d.attacker,
                "target": d.target,
                "witnesses": list(d.witnesses),
            }
            for d in r.framework.defeats
        ],
        "extensions": (
            None
            if r.status not in ("OK", "REFERENCE_LIMIT")
            else [
                {"id": e.id, "arguments": sorted(e)}
                for e in sorted(r.extensions, key=lambda e: sorted(e))
            ]
        ),
        "claims": dict(sorted(r.statuses.items())),
    }
    if include_timings:
        data["timings"] = dict(r.timings)
    return data


def evaluation_from_dict(d, *, _trusted=False, limits=None):
    if not _trusted:
        return validate_evaluation_data(d, limits=limits)
    from .evaluation import Evaluation

    if d["schema_version"] not in ("1.0", SCHEMA_VERSION):
        raise ValueError("unsupported evaluation schema")
    t = theory_from_dict(d["theory"]) if d["theory"] is not None else None
    rules = {r.name: r for r in t.rules} if t else {}
    nodes = {}
    for v in d["argument_nodes"]:
        a = Argument(
            v["conclusion"],
            rules[v["top_rule"]] if v["top_rule"] else None,
            tuple(nodes[i] for i in v["children"]),
            Fact(**v["premise"]) if v["premise"] else None,
        )
        if a.id != v["id"]:
            raise ValueError("argument identity mismatch")
        nodes[a.id] = a
    args = tuple(nodes[i] for i in d["arguments"])
    events = tuple(
        Attack(
            nodes[a["attacker"]],
            nodes[a["target"]],
            nodes[a["witness"]],
            a["kind"],
            a["element"],
            a["preference_independent"],
        )
        for a in d["attacks"]
    )
    return Evaluation(
        d["status"],
        args,
        events,
        frozenset((e["attacker"], e["target"]) for e in d["defeats"]),
        tuple(frozenset(e["arguments"]) for e in (d["extensions"] or [])),
        {a: a.id for a in args},
        d["claims"],
        d.get("timings", {}),
        d["error"],
        d["policy"],
        t,
        d["configuration"],
        d.get("resource", {}),
        defeat_witnesses={
            (e["attacker"], e["target"]): tuple(e["witnesses"]) for e in d["defeats"]
        },
    )


def validate_evaluation_data(d, *, limits=None):
    from .protocol import object_keys, configuration
    from .evaluation import _evaluate_core, Evaluation

    object_keys(
        d,
        (
            "schema_version",
            "status",
            "error",
            "policy",
            "configuration",
            "theory",
            "arguments",
            "argument_nodes",
            "attacks",
            "defeats",
            "extensions",
            "claims",
        ),
        ("timings", "resource"),
    )
    if d["schema_version"] not in ("1.0", SCHEMA_VERSION):
        raise ValueError("unsupported schema")
    if d["status"] not in ("OK", "REFERENCE_LIMIT"):
        allowed = {
            "PROCESS_RESOURCE_FAILURE",
            "MEMORY_FAILURE",
            "PROCESS_TERMINATED",
            "VALIDATION_ERROR",
            "CONFIGURATION_ERROR",
            "CONSTRUCTION_LIMIT",
            "RELATION_LIMIT",
            "SEMANTICS_LIMIT",
            "TIME_LIMIT",
            "MEMORY_LIMIT",
            "OUTPUT_LIMIT",
            "INTERNAL_ERROR",
            "CANCELLED",
            "CYCLE_POLICY_REQUIRED",
            "CYCLE_REJECTED",
        }
        if type(d["status"]) is not str or d["status"] not in allowed:
            raise ValueError("invalid evaluation status")
        if d["error"] is not None and type(d["error"]) is not str:
            raise ValueError("invalid error")
        if d["extensions"] or d["claims"]:
            raise ValueError("an incomplete evaluation cannot carry an extension family or claims")
        if d["theory"] is None and not d["arguments"]:
            expected = Evaluation(d["status"], error=d["error"])
        else:
            from dataclasses import replace

            theory = theory_from_dict(d["theory"])
            c = configuration(d["configuration"])
            resource = d.get("resource") if isinstance(d.get("resource"), dict) else {}
            stage = "defeat" if resource.get("framework_complete") else "construct"
            partial = _evaluate_core(theory, **c, limits=limits, stop_after=stage)
            if partial.status not in ("FRAMEWORK_COMPLETE", "CONSTRUCTION_COMPLETE"):
                raise ValueError("partial evaluation could not be re-derived")
            expected = replace(
                partial, status=d["status"], error=d["error"], extensions=(), statuses={}
            )
    else:
        theory = theory_from_dict(d["theory"])
        c = configuration(d["configuration"])
        expected = _evaluate_core(theory, **c, limits=limits)
        if expected.status not in ("OK", "REFERENCE_LIMIT"):
            from .resources import ResourceLimit

            raise ResourceLimit(
                expected.status,
                expected.error or "validation evaluation did not complete",
            )
    actual = {k: v for k, v in d.items() if k not in ("timings", "resource")}
    import json

    wire = lambda v: json.dumps(
        canonical(v),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if wire(actual) != wire({k: v for k, v in expected.to_dict().items() if k != "resource"}):
        raise ValueError("serialized evaluation does not match validated theory/configuration")
    if "timings" in d:
        import math

        if type(d["timings"]) is not dict or any(
            type(v) not in (float, int) or not math.isfinite(v) or v < 0
            for v in d["timings"].values()
        ):
            raise ValueError("invalid timings")
    return expected
