from dataclasses import dataclass, fields
from .analysis import Serializable
from .identity import freeze, digest
from .serialization import theory_to_dict


@dataclass(frozen=True, slots=True)
class ComparisonResult(Serializable):
    status: str
    left_status: str
    right_status: str
    differences: object
    smallest_recorded_witness: str | None = None
    note: str = "Smallest recorded representative is not a globally minimal counterexample."

    def __post_init__(self):
        object.__setattr__(self, "differences", freeze(self.differences))


def compare_arguments(left, right):
    from .resources import consume

    consume(
        "comparison_work",
        len(left.subarguments) + len(right.subarguments),
        "COMPARISON_LIMIT",
    )
    names = (
        "conclusion",
        "top_rule",
        "top_rule_kind",
        "depth",
        "ordinary_premises",
        "axioms",
        "strict_rules",
        "defeasible_rules",
        "last_defeasible_rules",
        "semantic_signature",
    )

    def value(a, n):
        v = getattr(a, n)
        if n == "top_rule":
            return v.name if v else None
        return v

    return ComparisonResult(
        "OK",
        "OK",
        "OK",
        {n: (value(left, n), value(right, n)) for n in names if value(left, n) != value(right, n)},
    )


def compare_claims(left, right):
    from .resources import consume

    consume(
        "comparison_work",
        len(left.supporting_arguments) + len(right.supporting_arguments),
        "COMPARISON_LIMIT",
    )
    return ComparisonResult(
        "OK",
        "OK",
        "OK",
        {
            f.name: (getattr(left, f.name), getattr(right, f.name))
            for f in fields(left)
            if getattr(left, f.name) != getattr(right, f.name)
        },
    )


def _compare(left, right):
    if left.status not in ("OK", "REFERENCE_LIMIT") or right.status not in (
        "OK",
        "REFERENCE_LIMIT",
    ):
        return ComparisonResult(
            "INCOMPLETE_COMPARISON",
            left.status,
            right.status,
            {},
            note="No missing-class inference is made from a failed evaluation.",
        )
    from .resources import consume

    consume(
        "comparison_work",
        sum(
            len(r.arguments) + len(r.attacks) + len(r.defeats) + sum(len(e) for e in r.extensions)
            for r in (left, right)
        ),
        "COMPARISON_LIMIT",
    )
    if theory_to_dict(left.theory) != theory_to_dict(right.theory):
        raise ValueError("comparison requires the same theory")

    def view(r):
        ids = {r.ids[a]: a.signature_id for a in r.arguments}
        witnesses = {
            (
                a.attacker.signature_id,
                a.target.signature_id,
                digest("w_", a.witness.descriptor),
                a.kind,
            )
            for a in r.attacks
        }
        return {
            "classes": set(ids.values()),
            "attack_witnesses": witnesses,
            "defeats": {(ids[a], ids[b]) for a, b in r.defeats},
            "extensions": {frozenset(ids[i] for i in e) for e in r.extensions},
        }

    a, b = view(left), view(right)
    diff = {k: {"left_only": a[k] - b[k], "right_only": b[k] - a[k]} for k in a}
    diff["claim_statuses"] = {
        c: (left.statuses.get(c), right.statuses.get(c))
        for c in set(left.statuses) | set(right.statuses)
        if left.statuses.get(c) != right.statuses.get(c)
    }
    missing = a["classes"] ^ b["classes"]
    candidates = [x for r in (left, right) for x in r.arguments if x.signature_id in missing]
    witness = (
        min(candidates, key=lambda x: (x.depth, len(x.subarguments), x.id)).id
        if candidates
        else None
    )
    return ComparisonResult(
        "REFERENCE_LIMIT" if "REFERENCE_LIMIT" in (left.status, right.status) else "OK",
        left.status,
        right.status,
        diff,
        witness,
    )


def _setting(result, key):
    from .protocol import CONFIG_DEFAULTS

    return result.configuration.get(key, CONFIG_DEFAULTS[key])


def compare_semantics(left, right):
    if (
        left.configuration
        and right.configuration
        and any(
            _setting(left, k) != _setting(right, k)
            for k in (
                "ordering",
                "cycle_policy",
                "depth",
                "conflict_free",
                "transposition",
            )
        )
    ):
        raise ValueError("semantic comparison changes semantics only")
    return _compare(left, right)


def compare_policies(left, right):
    if (
        left.configuration
        and right.configuration
        and any(
            _setting(left, k) != _setting(right, k)
            for k in ("ordering", "semantics", "conflict_free", "transposition")
        )
    ):
        raise ValueError("policy comparison keeps ordering and semantics fixed")
    return _compare(left, right)
