from dataclasses import dataclass, field

from .model import Literal, Rule, Theory


def strict_closure(theory, literals):
    closed = set(literals)
    strict = [r for r in theory.rules if r.kind == "strict"]
    changed = True
    while changed:
        changed = False
        for rule in strict:
            if rule.consequent not in closed and all(a in closed for a in rule.antecedents):
                closed.add(rule.consequent)
                changed = True
    return closed


def conflicting_pairs(theory, literals):
    literals = set(literals)
    return sorted((x, y) for x, y in theory.conflicts if x in literals and y in literals)


def contradictories(theory, literal):
    literal = Literal(literal)
    found = {literal.negated}
    for x, y in theory.conflicts:
        if y == literal and (y, x) in theory.conflicts:
            found.add(Literal(x))
    return sorted(found)


def transpositions(rule, theory=None):

    def contra(l):
        return contradictories(theory, l) if theory is not None else [Literal(l).negated]

    result = []
    for index, phi in enumerate(rule.antecedents):
        for c in contra(rule.consequent):
            for d in contra(phi):
                antecedents = list(rule.antecedents)
                antecedents[index] = c
                result.append((tuple(sorted(set(antecedents))), d))
    return result


@dataclass(frozen=True)
class WellDefinednessReport:

    closed_under_transposition: bool
    missing_transpositions: tuple = ()
    axiom_consistent: bool = True
    axiom_conflicts: tuple = ()
    well_formed: bool = True
    ill_formed_contraries: tuple = ()
    notes: tuple = field(default_factory=tuple)

    @property
    def well_defined(self):
        return self.closed_under_transposition and self.axiom_consistent and self.well_formed

    def to_dict(self):
        return {
            "well_defined": self.well_defined,
            "closed_under_transposition": self.closed_under_transposition,
            "missing_transpositions": [
                {"from_rule": name, "antecedents": list(ants), "consequent": str(cons)}
                for name, ants, cons in self.missing_transpositions
            ],
            "axiom_consistent": self.axiom_consistent,
            "axiom_conflicts": [list(p) for p in self.axiom_conflicts],
            "well_formed": self.well_formed,
            "ill_formed_contraries": [
                {"contrary": x, "of": y, "reason": why} for x, y, why in self.ill_formed_contraries
            ],
            "notes": list(self.notes),
        }

    def warnings(self):
        out = []
        if self.missing_transpositions:
            out.append(
                "Strict rules are not closed under transposition (%d missing). Consistency "
                "postulates are not guaranteed; consider transposition=True."
                % len(self.missing_transpositions)
            )
        if not self.axiom_consistent:
            out.append("Axioms are inconsistent under strict-rule closure.")
        if not self.well_formed:
            out.append("A contrary targets an axiom or a strict-rule consequent (not well formed).")
        return out


def diagnose(theory):
    strict_bodies = {(r.antecedents, r.consequent) for r in theory.rules if r.kind == "strict"}
    missing = []
    for rule in sorted((r for r in theory.rules if r.kind == "strict"), key=lambda r: r.name):
        for antecedents, consequent in transpositions(rule, theory):
            if (antecedents, consequent) not in strict_bodies:
                missing.append((rule.name, tuple(map(str, antecedents)), consequent))
    axioms = {f.literal for f in theory.facts if f.kind == "axiom"}
    axiom_conflicts = conflicting_pairs(theory, strict_closure(theory, axioms))
    strict_heads = {r.consequent for r in theory.rules if r.kind == "strict"}
    ill_formed = []
    for x, y in sorted(theory.conflicts):
        if (y, x) in theory.conflicts:
            continue
        if y in axioms:
            ill_formed.append((str(x), str(y), "target is an axiom"))
        elif y in strict_heads:
            ill_formed.append((str(x), str(y), "target is a strict-rule consequent"))
    notes = []
    if not missing:
        notes.append("Closure under transposition is checked; contraposition is not tested.")
    return WellDefinednessReport(
        closed_under_transposition=not missing,
        missing_transpositions=tuple(missing),
        axiom_consistent=not axiom_conflicts,
        axiom_conflicts=tuple(axiom_conflicts),
        well_formed=not ill_formed,
        ill_formed_contraries=tuple(ill_formed),
        notes=tuple(notes),
    )


def close_under_transposition(theory, prefix="tp"):
    rules = list(theory.rules)
    used_names = {r.name for r in rules} | {str(l).lstrip("-") for l in theory.object_literals}
    bodies = {(r.antecedents, r.consequent, r.kind) for r in rules}
    changed = True
    while changed:
        changed = False
        for rule in [r for r in rules if r.kind == "strict"]:
            for index, (antecedents, consequent) in enumerate(transpositions(rule, theory)):
                if (antecedents, consequent, "strict") in bodies:
                    continue
                name = f"{prefix}_{rule.name}_{index + 1}"
                suffix = 1
                while name in used_names:
                    suffix += 1
                    name = f"{prefix}_{rule.name}_{index + 1}_{suffix}"
                used_names.add(name)
                rules.append(Rule(name, antecedents, consequent, "strict"))
                bodies.add((antecedents, consequent, "strict"))
                changed = True
    if len(rules) == len(theory.rules):
        return theory
    return Theory(
        theory.facts,
        tuple(rules),
        theory.rule_preferences,
        theory.premise_preferences,
        theory.contraries,
    )


@dataclass(frozen=True)
class PostulateReport:

    extensions: tuple
    applicable: bool
    assumptions: dict = None

    @property
    def satisfied(self):
        return all(all(e[k]["ok"] for k in POSTULATES) for e in self.extensions)

    def to_dict(self):
        return {
            "satisfied": self.satisfied,
            "guaranteed_by_theory": self.applicable,
            "assumptions": dict(self.assumptions or {}),
            "extensions": list(self.extensions),
        }


POSTULATES = (
    "subargument_closure",
    "strict_closure",
    "direct_consistency",
    "indirect_consistency",
)
COMPLETE_BASED = {
    "complete",
    "grounded",
    "preferred",
    "stable",
    "semistable",
    "ideal",
    "eager",
}


def check_postulates(evaluation):
    theory = evaluation.theory
    ids = evaluation.ids
    by_id = {ids[a]: a for a in evaluation.arguments}
    reports = []
    for extension in evaluation.extensions:
        members = [by_id[i] for i in extension]
        member_signatures = {a.semantic_signature for a in members}
        missing_subs = sorted(
            {
                s.id
                for a in members
                for s in a.subarguments
                if s.semantic_signature not in member_signatures
            }
        )
        conclusions = {a.conclusion for a in members}
        closure = strict_closure(theory, conclusions)
        reports.append(
            {
                "extension": sorted(extension),
                "subargument_closure": {
                    "ok": not missing_subs,
                    "missing": missing_subs,
                },
                "strict_closure": {
                    "ok": closure == conclusions,
                    "missing": sorted(map(str, closure - conclusions)),
                },
                "direct_consistency": {
                    "ok": not conflicting_pairs(theory, conclusions),
                    "conflicts": [
                        list(map(str, p)) for p in conflicting_pairs(theory, conclusions)
                    ],
                },
                "indirect_consistency": {
                    "ok": not conflicting_pairs(theory, closure),
                    "conflicts": [list(map(str, p)) for p in conflicting_pairs(theory, closure)],
                },
            }
        )
    semantics = (evaluation.configuration or {}).get("semantics")
    well_defined = diagnose(theory).well_defined
    return PostulateReport(
        tuple(reports),
        semantics in COMPLETE_BASED and well_defined,
        {
            "well_defined_theory": well_defined,
            "reasonable_ordering": True,
            "complete_based_semantics": semantics in COMPLETE_BASED,
        },
    )
