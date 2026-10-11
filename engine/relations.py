from dataclasses import dataclass, field
from .model import Argument, Literal

ORDERINGS = (
    "last_link_elitist",
    "last_link_democratic",
    "weakest_link_elitist",
    "weakest_link_democratic",
)


def set_less(left, right, stronger, comparison):
    if not left:
        return False
    if not right:
        return True
    if comparison == "elitist":
        return any(all((y, x) in stronger for y in right) for x in left)
    if comparison == "democratic":
        return all(any((y, x) in stronger for y in right) for x in left)
    raise ValueError("unknown set comparator")


def _strictly_weaker(theory, left, right, ordering):
    mode, comparison = ordering.rsplit("_", 1)
    rp = (
        (left.last_defeasible_rules, right.last_defeasible_rules)
        if mode == "last_link"
        else (left.defeasible_rules, right.defeasible_rules)
    )
    pp = (left.ordinary_premises, right.ordinary_premises)
    if mode == "last_link":
        if any(rp):
            return (
                set_less(*rp, theory.rule_order, comparison),
                "last defeasible rules",
                rp,
                pp,
            )
        return (
            set_less(*pp, theory.premise_order, comparison),
            "ordinary premises: both arguments strict",
            rp,
            pp,
        )
    if left.is_strict and right.is_strict:
        return (
            set_less(*pp, theory.premise_order, comparison),
            "ordinary premises: both strict",
            rp,
            pp,
        )
    if left.is_firm and right.is_firm:
        return (
            set_less(*rp, theory.rule_order, comparison),
            "defeasible rules: both firm",
            rp,
            pp,
        )
    result = set_less(*pp, theory.premise_order, comparison) and set_less(
        *rp, theory.rule_order, comparison
    )
    return result, "both premise and rule sets must be strictly worse", rp, pp


def is_weaker(theory, left, right, ordering="last_link_elitist"):
    if ordering not in ORDERINGS:
        raise ValueError("unknown ordering")
    return _strictly_weaker(theory, left, right, ordering)[0]


def compare(theory, left, right, ordering="last_link_elitist"):
    from .resources import consume

    consume("preference_checks")
    if ordering not in ORDERINGS:
        raise ValueError("unknown ordering")
    mode, comparison = ordering.rsplit("_", 1)
    result, reason, rp, pp = _strictly_weaker(theory, left, right, ordering)
    return {
        "ordering": mode,
        "comparison": comparison,
        "left_rule_set": sorted(rp[0]),
        "right_rule_set": sorted(rp[1]),
        "left_premise_set": sorted(pp[0]),
        "right_premise_set": sorted(pp[1]),
        "less": result,
        "reason": reason,
    }


@dataclass(frozen=True, slots=True)
class Attack:
    attacker: Argument
    target: Argument
    witness: Argument
    kind: str
    element: str
    preference_independent: bool
    _id: str = field(init=False, repr=False, compare=False, hash=False, default="")

    def __post_init__(self):
        from .identity import digest

        object.__setattr__(
            self,
            "_id",
            digest(
                "t_",
                (
                    self.attacker.id,
                    self.target.id,
                    self.witness.id,
                    self.kind,
                    self.element,
                    self.preference_independent,
                ),
            ),
        )

    @property
    def id(self):
        return self._id


def succeeds(theory, attack, ordering="last_link_elitist"):
    if attack.preference_independent:
        return True
    from .resources import consume

    consume("preference_checks")
    return not is_weaker(theory, attack.attacker, attack.witness, ordering)


def attacks(theory, attacker, target):
    for witness in sorted(target.subarguments, key=lambda a: repr(a.structure)):
        element = None
        kind = None
        if witness.premise and witness.premise.kind == "premise":
            element = witness.conclusion
            kind = "undermine"
        elif witness.top_rule and witness.top_rule.kind == "defeasible":
            rule_literal = Literal(witness.top_rule.name)
            if (attacker.conclusion, rule_literal) in theory.conflicts:
                yield Attack(attacker, target, witness, "undercut", str(rule_literal), True)
            element = witness.conclusion
            kind = "rebut"
        if element is not None and (attacker.conclusion, element) in theory.conflicts:
            yield Attack(
                attacker,
                target,
                witness,
                kind,
                str(element),
                (element, attacker.conclusion) not in theory.conflicts,
            )


def explain_defeat(theory, attack, ordering="last_link_elitist"):
    preference = compare(theory, attack.attacker, attack.witness, ordering)
    return {
        "attack": attack,
        "preference": preference,
        "succeeds": attack.preference_independent or not preference["less"],
    }


def _attack_points(witness):
    if witness.premise is not None:
        if witness.premise.kind == "premise":
            yield "undermine", witness.conclusion
    elif witness.top_rule.kind == "defeasible":
        yield "undercut", Literal(witness.top_rule.name)
        yield "rebut", witness.conclusion


def all_attacks(theory, arguments, on_probe=None):
    by_conclusion = {}
    for argument in arguments:
        by_conclusion.setdefault(argument.conclusion, []).append(argument)
    attackers_of = {}
    for source, target in theory.conflicts:
        attackers_of.setdefault(target, []).append(source)
    for target in arguments:
        for witness in target.subarguments:
            for kind, element in _attack_points(witness):
                if on_probe is not None:
                    on_probe()
                for literal in attackers_of.get(element, ()):
                    independent = kind == "undercut" or (element, literal) not in theory.conflicts
                    for attacker in by_conclusion.get(literal, ()):
                        yield Attack(attacker, target, witness, kind, str(element), independent)


def attack(theory, left, right):
    return bool(tuple(attacks(theory, left, right)))


def defeat(theory, left, right, ordering="last_link_elitist"):
    return any(
        explain_defeat(theory, a, ordering)["succeeds"] for a in attacks(theory, left, right)
    )


def explain_attack(theory, left, right):
    return tuple(attacks(theory, left, right))
