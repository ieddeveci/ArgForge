from dataclasses import dataclass, field
from .identity import memo_property as cached_property
from types import MappingProxyType
from itertools import product
import re


class Literal(str):
    __slots__ = ()

    def __new__(cls, value):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError("literal must be a nonempty trimmed string")
        if value.startswith("--") or value == "-":
            raise ValueError("negation is a single leading minus")
        return str.__new__(cls, value)

    @property
    def negated(self):
        return Literal(self[1:] if self.startswith("-") else "-" + self)


@dataclass(frozen=True, slots=True)
class Fact:
    literal: Literal
    kind: str = "premise"

    def __post_init__(self):
        object.__setattr__(self, "literal", Literal(self.literal))
        if self.kind not in ("axiom", "premise"):
            raise ValueError("invalid fact kind")


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    antecedents: tuple[Literal, ...]
    consequent: Literal
    kind: str = "defeasible"

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_]+", self.name):
            raise ValueError("rule name must contain only letters, digits or underscore")
        object.__setattr__(self, "antecedents", tuple(sorted(set(map(Literal, self.antecedents)))))
        object.__setattr__(self, "consequent", Literal(self.consequent))
        if self.kind not in ("strict", "defeasible"):
            raise ValueError("invalid rule kind")


def StrictRule(name, antecedents, consequent):
    return Rule(name, tuple(antecedents), consequent, "strict")


def DefeasibleRule(name, antecedents, consequent):
    return Rule(name, tuple(antecedents), consequent, "defeasible")


@dataclass(frozen=True, slots=True)
class RulePreference:
    stronger: str
    weaker: str


@dataclass(frozen=True, slots=True)
class PremisePreference:
    stronger: str
    weaker: str


@dataclass(frozen=True, slots=True)
class ContraryRelation:
    source: Literal
    target: Literal
    symmetric: bool = False

    def __post_init__(self):
        object.__setattr__(self, "source", Literal(self.source))
        object.__setattr__(self, "target", Literal(self.target))


def transitive_closure(pairs):
    result = set(pairs)
    while True:
        extra = {(a, d) for a, b in result for c, d in result if b == c}
        if extra <= result:
            return frozenset(result)
        result.update(extra)


@dataclass(frozen=True, slots=True)
class Theory:
    facts: tuple[Fact, ...] = ()
    rules: tuple[Rule, ...] = ()
    rule_preferences: tuple[RulePreference, ...] = ()
    premise_preferences: tuple[PremisePreference, ...] = ()
    contraries: tuple[ContraryRelation, ...] = ()
    _cache: object = field(
        default_factory=lambda: MappingProxyType({}),
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self):
        from .resources import enter_stage

        enter_stage("validate")
        for name in (
            "facts",
            "rules",
            "rule_preferences",
            "premise_preferences",
            "contraries",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        names = [r.name for r in self.rules]
        if len(set(names)) != len(names):
            raise ValueError("duplicate rule name")
        bodies = [(r.antecedents, r.consequent, r.kind) for r in self.rules]
        if len(set(bodies)) != len(bodies):
            raise ValueError("duplicate rule body")
        ordinary = {f.literal for f in self.facts if f.kind == "premise"}
        axioms = {f.literal for f in self.facts if f.kind == "axiom"}
        if ordinary & axioms:
            raise ValueError("knowledge base categories must be disjoint")
        object.__setattr__(
            self,
            "facts",
            tuple(sorted(set(self.facts), key=lambda f: (f.literal, f.kind))),
        )
        object.__setattr__(self, "rules", tuple(sorted(self.rules, key=lambda r: r.name)))
        for name in ("rule_preferences", "premise_preferences"):
            values = sorted(set(getattr(self, name)), key=lambda p: (p.stronger, p.weaker))
            object.__setattr__(self, name, tuple(values))
        object.__setattr__(
            self,
            "contraries",
            tuple(
                sorted(
                    set(self.contraries),
                    key=lambda c: (c.source, c.target, c.symmetric),
                )
            ),
        )
        positive_names = set(names)
        if self.object_literals & positive_names:
            raise ValueError("rule name collides with an object literal")
        defnames = {r.name for r in self.rules if r.kind == "defeasible"}
        for preferences, universe in (
            (self.rule_preferences, defnames),
            (self.premise_preferences, ordinary),
        ):
            if any(p.stronger not in universe or p.weaker not in universe for p in preferences):
                raise ValueError("preference endpoint outside declared domain")
            closure = transitive_closure((p.stronger, p.weaker) for p in preferences)
            if any(a == b for a, b in closure):
                raise ValueError("strict preference cycle")

    @cached_property
    def object_literals(self):
        return frozenset(
            [f.literal for f in self.facts]
            + [l for r in self.rules for l in (*r.antecedents, r.consequent)]
            + [l for c in self.contraries for l in (c.source, c.target)]
        )

    @cached_property
    def language(self):
        literals = self.object_literals | {
            Literal(r.name) for r in self.rules if r.kind == "defeasible"
        }
        return frozenset(literals | {Literal(l).negated for l in literals})

    @cached_property
    def conflicts(self):
        pairs = {(l, Literal(l).negated) for l in self.language}
        for c in self.contraries:
            pairs.add((c.source, c.target))
            if c.symmetric:
                pairs.add((c.target, c.source))
        return frozenset(pairs)

    @cached_property
    def rule_order(self):
        return transitive_closure((p.stronger, p.weaker) for p in self.rule_preferences)

    @cached_property
    def premise_order(self):
        return transitive_closure((p.stronger, p.weaker) for p in self.premise_preferences)

    @cached_property
    def topological_literals(self):
        dependencies = {l: set() for l in self.language}
        for r in self.rules:
            dependencies[r.consequent].update(r.antecedents)
        order = []
        while dependencies:
            ready = sorted(l for l, parents in dependencies.items() if not parents)
            if not ready:
                return None
            order.extend(ready)
            for l in ready:
                del dependencies[l]
            for parents in dependencies.values():
                parents.difference_update(ready)
        return tuple(order)

    def validate(self):
        Theory(
            self.facts,
            self.rules,
            self.rule_preferences,
            self.premise_preferences,
            self.contraries,
        )

    @classmethod
    def parse(cls, text):
        from .surface import parse_theory

        return parse_theory(text, cls)

    def to_source(self):
        from .surface import serialize_theory

        return serialize_theory(self)


@dataclass(frozen=True, slots=True)
class Argument:
    conclusion: Literal
    top_rule: Rule | None = None
    direct_subarguments: tuple["Argument", ...] = ()
    premise: Fact | None = None
    _hash: int = field(init=False, repr=False, compare=False)
    _cache: object = field(
        default_factory=lambda: MappingProxyType({}),
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self):
        object.__setattr__(self, "conclusion", Literal(self.conclusion))
        object.__setattr__(self, "direct_subarguments", tuple(self.direct_subarguments))
        if self.top_rule is None:
            if (
                self.premise is None
                or self.direct_subarguments
                or self.conclusion != self.premise.literal
            ):
                raise ValueError("invalid premise argument")
        elif (
            self.premise is not None
            or self.conclusion != self.top_rule.consequent
            or tuple(a.conclusion for a in self.direct_subarguments) != self.top_rule.antecedents
        ):
            raise ValueError("rule application does not match antecedents")
        object.__setattr__(
            self,
            "_hash",
            hash(
                (
                    self.conclusion,
                    self.top_rule,
                    self.premise,
                    tuple(hash(a) for a in self.direct_subarguments),
                )
            ),
        )

    def __hash__(self):
        return self._hash

    @cached_property
    def subarguments(self):
        return frozenset({self}.union(*(a.subarguments for a in self.direct_subarguments)))

    @cached_property
    def premises(self):
        return frozenset(
            [self.premise]
            if self.premise
            else set().union(*(a.premises for a in self.direct_subarguments))
        )

    @cached_property
    def ordinary_premises(self):
        return frozenset(f.literal for f in self.premises if f.kind == "premise")

    @cached_property
    def axioms(self):
        return frozenset(f.literal for f in self.premises if f.kind == "axiom")

    @cached_property
    def defeasible_rules(self):
        return frozenset(
            a.top_rule.name
            for a in self.subarguments
            if a.top_rule and a.top_rule.kind == "defeasible"
        )

    @cached_property
    def strict_rules(self):
        return frozenset(
            a.top_rule.name for a in self.subarguments if a.top_rule and a.top_rule.kind == "strict"
        )

    @cached_property
    def last_defeasible_rules(self):
        if self.top_rule and self.top_rule.kind == "defeasible":
            return frozenset({self.top_rule.name})
        return frozenset().union(*(a.last_defeasible_rules for a in self.direct_subarguments))

    @property
    def top_rule_kind(self):
        return self.top_rule.kind if self.top_rule else None

    @cached_property
    def depth(self):
        return 1 + max((a.depth for a in self.direct_subarguments), default=-1)

    height = property(lambda self: self.depth)
    is_strict = property(lambda self: not self.defeasible_rules)
    is_firm = property(lambda self: not self.ordinary_premises)

    @cached_property
    def descriptor(self):
        return (
            self.conclusion,
            self.top_rule.name if self.top_rule else None,
            self.top_rule_kind,
            self.last_defeasible_rules,
            self.defeasible_rules,
            self.ordinary_premises,
        )

    @property
    def attackable(self):
        if self.premise is not None:
            return self.premise.kind == "premise"
        return self.top_rule.kind == "defeasible"

    @cached_property
    def attacker_descriptor(self):
        return (
            self.conclusion,
            self.last_defeasible_rules,
            self.defeasible_rules,
            self.ordinary_premises,
        )

    @cached_property
    def semantic_signature(self):
        return self.descriptor, frozenset(a.descriptor for a in self.subarguments)

    @cached_property
    def attack_class_signature(self):
        return self.attacker_descriptor, frozenset(
            a.descriptor for a in self.subarguments if a.attackable
        )

    @cached_property
    def id(self):
        from .identity import digest

        return digest(
            "a_",
            (
                str(self.conclusion),
                (
                    (self.top_rule.name, self.top_rule.kind, self.top_rule.antecedents)
                    if self.top_rule
                    else None
                ),
                self.premise.kind if self.premise else None,
                tuple(a.id for a in self.direct_subarguments),
            ),
        )

    @cached_property
    def signature_id(self):
        from .identity import digest

        return digest("q_", self.semantic_signature)

    @cached_property
    def structure(self):
        return (
            ("fact", self.premise.kind, str(self.conclusion))
            if self.premise
            else (
                "rule",
                self.top_rule.name,
                tuple(a.structure for a in self.direct_subarguments),
            )
        )
