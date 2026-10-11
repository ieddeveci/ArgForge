from engine.relations import explain_defeat
from ..common import plain, require, key


def explain_attacks(evaluation, attacker=None, target=None):
    require(evaluation)
    t = evaluation.theory
    out = []
    node_key = lambda a: a.id if evaluation.policy == "EXACT" else key(a)
    for a in evaluation.attacks:
        if attacker is not None and a.attacker.id != attacker:
            continue
        if target is not None and a.target.id != target:
            continue
        d = explain_defeat(t, a, evaluation.configuration["ordering"])
        declared = [
            plain(c)
            for c in t.contraries
            if (str(c.source), str(c.target)) == (str(a.attacker.conclusion), a.element)
            or c.symmetric
            and (str(c.target), str(c.source)) == (str(a.attacker.conclusion), a.element)
        ]
        out.append(
            dict(
                id=a.id,
                attacker=a.attacker.id,
                target=a.target.id,
                witness=a.witness.id,
                kind=a.kind,
                attacker_conclusion=str(a.attacker.conclusion),
                attacked_element=a.element,
                conflict={
                    "directed_pair": [str(a.attacker.conclusion), a.element],
                    "reverse_conflict": (a.element, a.attacker.conclusion) in t.conflicts,
                    "explicit_declarations": declared,
                    "default_signed_conflict": str(a.attacker.conclusion)
                    == ("-" + a.element if not a.element.startswith("-") else a.element[1:]),
                },
                preference_relevant=not a.preference_independent,
                preference=plain(d["preference"]),
                succeeds_as_defeat=d["succeeds"],
                reason=(
                    "preference-independent attack"
                    if a.preference_independent
                    else (
                        "attacker strictly weaker than attacked witness"
                        if d["preference"]["less"]
                        else "attacker not strictly weaker than attacked witness"
                    )
                ),
                invariant=[
                    node_key(a.attacker),
                    node_key(a.target),
                    (
                        a.witness.id
                        if evaluation.policy == "EXACT"
                        else identity_descriptor(a.witness)
                    ),
                    a.kind,
                    a.element,
                    a.preference_independent,
                ],
            )
        )
    return out


def identity_descriptor(a):
    from ..common import identity

    return identity(a.semantic_signature[0])


def explain_claim(result, claim):
    if result.status != "OK":
        return {"status": result.status, "complete": False}
    require(result.evaluation)
    c = result.claims.get(claim)
    if c is None:
        raise KeyError(claim)
    return {
        "claim": claim,
        "acceptance": c,
        "explanation_scope": "Exact membership and local defeat/defense witnesses; no unique global causal proof claimed.",
        "support_trees": [result.arguments[i] for i in c["supporting_arguments"]],
        "incoming_attacks": [x for x in result.attacks if x["target"] in c["supporting_arguments"]],
        "defense_triples": [
            x for x in result.defense if x["defended"] in c["supporting_arguments"]
        ],
    }
