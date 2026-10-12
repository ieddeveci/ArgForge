from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from functools import cached_property

from engine.evaluation import Evaluation, _evaluate_core
from engine.model import (
    ContraryRelation,
    Fact,
    PremisePreference,
    Rule,
    RulePreference,
    Theory,
)
from engine.protocol import CONFIG_DEFAULTS
from engine.relations import ORDERINGS, compare, succeeds
from engine.resources import Limits
from engine.semantics import SEMANTICS, grounded_labelling
from engine.serialization import theory_from_dict, theory_to_dict
from engine.surface import parse_declarations
from engine.wellformed import (
    check_postulates,
    close_under_transposition,
    diagnose,
)

from .gradual import METHODS as STRENGTH_METHODS
from .gradual import strengths as _strengths
from .graphs import Graph

from dataclasses import fields as _fields
from types import MappingProxyType


def freeze(value):
    if isinstance(value, (dict, MappingProxyType)):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    if isinstance(value, tuple) and not hasattr(value, "_fields"):
        return tuple(freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(value)
    return value


def plain(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, frozenset):
        return sorted(plain(v) for v in value)
    if hasattr(value, "__dataclass_fields__"):
        return {f.name: plain(getattr(value, f.name)) for f in _fields(value)}
    return value


def frozen_property(function):
    return cached_property(lambda self: freeze(function(self)))


LABELS = ("IN", "OUT", "UNDEC")

FEATURE_BASIS = {
    "claims": "invariant",
    "claims_justified": "invariant",
    "claims_defensible": "invariant",
    "claims_undecided": "invariant",
    "claims_overruled": "invariant",
    "roles": "invariant",
    "claim_strength_mean": "invariant",
    "well_defined": "invariant",
    "extensions": "invariant_except_cf_adm",
    "empty_family": "invariant",
    "postulates_satisfied": "invariant_except_cf_adm",
    "arguments": "representation",
    "attacks": "representation",
    "rebuts": "representation",
    "undermines": "representation",
    "undercuts": "representation",
    "defeats": "representation",
    "attack_success_rate": "representation",
    "mean_extension_size": "representation",
    "sceptical_fraction": "representation",
    "credulous_fraction": "representation",
    "grounded_in": "representation",
    "grounded_out": "representation",
    "grounded_undec": "representation",
    "strength_mean": "representation",
    "strength_min": "representation",
    "strength_max": "representation",
    "max_depth": "representation",
    "defeat_density": "representation",
    "cyclic_components": "representation",
    "odd_cycle_components": "representation",
}
CLAIM_STATUSES = ("JUSTIFIED", "DEFENSIBLE", "UNDECIDED", "OVERRULED", "UNSUPPORTED")
GRAPH_KINDS = ("defeat", "attack", "support", "claim", "rule_dependency", "conflict")


class ArgumentationError(RuntimeError):

    def __init__(self, status, message, details=None):
        super().__init__("%s: %s" % (status, message))
        self.status = status
        self.details = details or {}


class TheoryBuilder:

    def __init__(self, theory=None):
        self._facts, self._rules, self._rp, self._pp, self._cs = [], [], [], [], []
        if theory is not None:
            self.extend(theory)

    def premise(self, *literals):
        self._facts.extend(Fact(l, "premise") for l in literals)
        return self

    def axiom(self, *literals):
        self._facts.extend(Fact(l, "axiom") for l in literals)
        return self

    def _name(self, kind):
        prefix = "r" if kind == "defeasible" else "s"
        taken = {r.name for r in self._rules}
        i = sum(1 for r in self._rules if r.kind == kind) + 1
        while f"{prefix}{i}" in taken:
            i += 1
        return f"{prefix}{i}"

    def defeasible(self, name, antecedents=None, consequent=None):
        if consequent is None:
            name, antecedents, consequent = self._name("defeasible"), name, antecedents
        self._rules.append(Rule(name, tuple(antecedents or ()), consequent, "defeasible"))
        return self

    def strict(self, name, antecedents=None, consequent=None):
        if consequent is None:
            name, antecedents, consequent = self._name("strict"), name, antecedents
        self._rules.append(Rule(name, tuple(antecedents or ()), consequent, "strict"))
        return self

    def undercut(self, rule_name, antecedents=(), name=None, strict=False):
        kind = "strict" if strict else "defeasible"
        self._rules.append(
            Rule(name or self._name(kind), tuple(antecedents), "-" + rule_name, kind)
        )
        return self

    def prefer_rule(self, stronger, weaker):
        self._rp.append(RulePreference(stronger, weaker))
        return self

    def prefer_premise(self, stronger, weaker):
        self._pp.append(PremisePreference(stronger, weaker))
        return self

    def contrary(self, attacker, target):
        self._cs.append(ContraryRelation(attacker, target, False))
        return self

    def contradictory(self, left, right):
        self._cs.append(ContraryRelation(left, right, True))
        return self

    def source(self, text):
        f, r, rp, pp, cs = parse_declarations(text)
        self._facts.extend(f)
        self._rules.extend(r)
        self._rp.extend(rp)
        self._pp.extend(pp)
        self._cs.extend(cs)
        return self

    def extend(self, theory):
        theory = as_theory(theory)
        self._facts.extend(theory.facts)
        self._rules.extend(theory.rules)
        self._rp.extend(theory.rule_preferences)
        self._pp.extend(theory.premise_preferences)
        self._cs.extend(theory.contraries)
        return self

    def build(self):
        return Theory(
            tuple(self._facts),
            tuple(self._rules),
            tuple(self._rp),
            tuple(self._pp),
            tuple(self._cs),
        )


def as_theory(value):
    if isinstance(value, Theory):
        return value
    if isinstance(value, TheoryBuilder):
        return value.build()
    if isinstance(value, str):
        return Theory.parse(value)
    if isinstance(value, dict):
        return theory_from_dict(value)
    raise TypeError("expected Theory, source text, theory dict or TheoryBuilder")


@dataclass(frozen=True)
class SolverConfig:

    semantics: str = "grounded"
    ordering: str = "last_link"
    set_ordering: str = "elitist"
    conflict_free: str = "defeat"
    transposition: bool = False
    cycle_policy: str = "QUOTIENT"

    def __post_init__(self):
        if self.semantics not in SEMANTICS:
            raise ValueError("semantics must be one of %s" % sorted(SEMANTICS))
        if self.ordering in ORDERINGS:
            mode, lift = self.ordering.rsplit("_", 1)
            object.__setattr__(self, "ordering", mode)
            object.__setattr__(self, "set_ordering", lift)
        if self.ordering not in ("last_link", "weakest_link"):
            raise ValueError("ordering must be 'last_link' or 'weakest_link'")
        if self.set_ordering not in ("elitist", "democratic"):
            raise ValueError("set_ordering must be 'elitist' or 'democratic'")
        if self.conflict_free not in ("defeat", "attack"):
            raise ValueError("conflict_free must be 'defeat' or 'attack'")
        if type(self.transposition) is not bool:
            raise ValueError("transposition must be a boolean")
        if self.cycle_policy not in (
            "QUOTIENT",
            "QUOTIENT_ATTACKABLE",
            "P_LITERAL",
            "P_RULE",
            "P_STATE",
            "REJECT",
        ):
            raise ValueError("unsupported cycle_policy")

    @property
    def engine_ordering(self):
        return self.ordering + "_" + self.set_ordering

    def to_dict(self):
        return plain(self)


def _limits(timeout):
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not (isinstance(timeout, (int, float)) and 0 < timeout <= 3600):
        raise ValueError("timeout must be a number of seconds in (0, 3600]")
    seconds = {k: float(timeout) for k in asdict(Limits()) if k.endswith("_seconds")}
    return Limits(time_only=True, **seconds)


def solve(
    theory,
    *,
    semantics="grounded",
    ordering="last_link",
    set_ordering="elitist",
    conflict_free="defeat",
    transposition=False,
    cycle_policy="QUOTIENT",
    timeout=60,
    isolated=False,
    require_well_defined=False,
):
    config = SolverConfig(
        semantics, ordering, set_ordering, conflict_free, transposition, cycle_policy
    )
    return Reasoner(config, timeout=timeout, isolated=isolated, cache_size=0).solve(
        theory, require_well_defined=require_well_defined
    )


class Reasoner:

    def __init__(self, config=None, *, timeout=60, isolated=False, cache_size=256, **options):
        if type(isolated) is not bool:
            raise ValueError("isolated must be True or False")
        _limits(timeout)
        self.config = (
            config
            if isinstance(config, SolverConfig)
            else SolverConfig(**(config or {}), **options)
        )
        self.timeout = timeout
        self.isolated = isolated
        self.cache_size = cache_size
        self._cache = OrderedDict()
        self.hits = self.misses = 0

    def solve(self, theory, *, require_well_defined=False):
        if type(require_well_defined) is not bool:
            raise ValueError("require_well_defined must be True or False")
        import threading
        from time import monotonic

        started = monotonic()
        submitted = as_theory(theory)
        key = (submitted, self.config)
        lock = self.__dict__.setdefault("_lock", threading.Lock())
        with lock:
            cached = self._cache.get(key) if self.cache_size else None
            if cached is not None:
                self.hits += 1
                self._cache.move_to_end(key)
        if cached is not None:
            result = Result(cached, self.config, submitted)
        else:
            with lock:
                self.misses += 1
            result = self._solve(submitted, started)
            if self.cache_size and result.ok:
                with lock:
                    self._cache[key] = result.evaluation
                    while len(self._cache) > self.cache_size:
                        self._cache.popitem(last=False)
        if require_well_defined and not result.well_definedness["evaluated"]["well_defined"]:
            raise ArgumentationError(
                "NOT_WELL_DEFINED", "; ".join(result.warnings), result.well_definedness
            )
        return result

    def _solve(self, theory, started=None):
        c = self.config
        kwargs = dict(
            semantics=c.semantics,
            ordering=c.engine_ordering,
            cycle_policy=c.cycle_policy,
            conflict_free=c.conflict_free,
            transposition=c.transposition,
        )
        if self.isolated:
            from time import monotonic

            from argforge_platform import evaluate as isolated_evaluate

            remaining = self.timeout
            if started is not None and self.timeout is not None:
                remaining = self.timeout - (monotonic() - started)
                if remaining <= 0:
                    return Result(
                        Evaluation(
                            "TIME_LIMIT",
                            error="Total evaluation deadline exceeded before the worker started",
                            resource={
                                "phase": "parse",
                                "limit_kind": "total_time",
                                "limit_value": self.timeout,
                                "complete": False,
                            },
                        ),
                        c,
                        theory,
                    )
            evaluation = isolated_evaluate(theory, **kwargs, limits=_limits(remaining) or Limits())
        else:
            evaluation = _evaluate_core(
                theory, **kwargs, limits=_limits(self.timeout), deadline_start=started
            )
        return Result(evaluation, c, theory)

    def clear_cache(self):
        self._cache.clear()


@dataclass(frozen=True)
class ArgumentInfo:
    id: str
    alias: str
    conclusion: str
    kind: str
    top_rule: str | None
    text: str
    direct_subarguments: tuple
    subarguments: tuple
    ordinary_premises: tuple
    axioms: tuple
    defeasible_rules: tuple
    strict_rules: tuple
    last_defeasible_rules: tuple
    depth: int
    strict: bool
    firm: bool
    representative: bool

    def to_dict(self):
        return plain(self)


@dataclass(frozen=True)
class AttackInfo:
    id: str
    attacker: str
    target: str
    on: str
    type: str
    element: str
    preference_independent: bool
    succeeds: bool
    reason: str
    comparison: dict | None = None

    def to_dict(self):
        return plain(self)


@dataclass(frozen=True)
class ArgumentStatus:
    id: str
    sceptical: bool | None
    credulous: bool
    acceptance: float | None
    labels: tuple
    grounded_label: str
    grounded_round: int | None
    defeaters: tuple
    defeated: tuple

    def to_dict(self):
        return plain(self)


@dataclass(frozen=True)
class ClaimInfo:
    claim: str
    status: str
    sceptical: bool | None
    credulous: bool
    acceptance: float | None
    bearers: tuple
    accepted_bearers: tuple
    grounded_label: str
    strength: float
    opponents: tuple
    opposing_bearers: tuple

    def to_dict(self):
        return plain(self)


def _rule_text(rule):
    arrow = " -> " if rule.kind == "strict" else " => "
    return " & ".join(rule.antecedents) + arrow + rule.consequent


class Result:

    def __init__(
        self, evaluation: Evaluation, config: SolverConfig, submitted: Theory | None = None
    ):
        self.evaluation = evaluation
        self.config = config
        self.submitted_theory = submitted

    @property
    def status(self):
        return self.evaluation.status

    @property
    def ok(self):
        return self.evaluation.status in ("OK", "REFERENCE_LIMIT")

    @property
    def error(self):
        return self.evaluation.error

    def raise_for_status(self):
        if not self.ok:
            raise ArgumentationError(self.status, self.error or "evaluation did not complete")
        return self

    def _require(self):
        if not self.ok:
            raise ArgumentationError(self.status, self.error or "evaluation did not complete")

    @property
    def theory(self):
        return self.evaluation.theory

    @property
    def timings(self):
        return dict(self.evaluation.timings)

    @cached_property
    def _objects(self):
        self._require()
        return {self.evaluation.ids[a]: a for a in self.evaluation.arguments}

    @frozen_property
    def arguments(self):
        objs = self._objects
        order = sorted(objs, key=lambda i: (objs[i].depth, str(objs[i].conclusion), i))
        alias = {i: "A%d" % (n + 1) for n, i in enumerate(order)}
        quotient = str(self.evaluation.policy).startswith("QUOTIENT")
        out = {}
        for i in order:
            a = objs[i]
            if a.premise is not None:
                kind, top, text = a.premise.kind, None, "%s %s" % (a.premise.kind, a.conclusion)
            else:
                kind, top, text = a.top_rule.kind, a.top_rule.name, _rule_text(a.top_rule)
            out[i] = ArgumentInfo(
                id=i,
                alias=alias[i],
                conclusion=str(a.conclusion),
                kind=kind,
                top_rule=top,
                text=text,
                direct_subarguments=tuple(c.id for c in a.direct_subarguments),
                subarguments=tuple(
                    sorted(s.id for s in a.subarguments if s is not a and s.id != i)
                ),
                ordinary_premises=tuple(sorted(map(str, a.ordinary_premises))),
                axioms=tuple(sorted(map(str, a.axioms))),
                defeasible_rules=tuple(sorted(a.defeasible_rules)),
                strict_rules=tuple(sorted(a.strict_rules)),
                last_defeasible_rules=tuple(sorted(a.last_defeasible_rules)),
                depth=a.depth,
                strict=a.is_strict,
                firm=a.is_firm,
                representative=quotient,
            )
        return out

    def argument(self, ref):
        if ref in self.arguments:
            return self.arguments[ref]
        for info in self.arguments.values():
            if info.alias == ref:
                return info
        raise KeyError(ref)

    def _id(self, ref):
        return self.argument(ref).id

    @frozen_property
    def attacks(self):
        self._require()
        theory, ordering = self.evaluation.theory, self.config.engine_ordering
        out = []
        for e in self.evaluation.attacks:
            ok = succeeds(theory, e, ordering)
            c = None
            if e.preference_independent:
                reason = "%s is preference-independent" % (
                    "undercut" if e.kind == "undercut" else "contrary attack"
                )
            else:
                c = freeze(compare(theory, e.attacker, e.witness, ordering))
                reason = (
                    "attacker strictly weaker (%s)"
                    if c["less"]
                    else "attacker not strictly weaker (%s)"
                ) % c["reason"]
            out.append(
                AttackInfo(
                    e.id,
                    e.attacker.id,
                    e.target.id,
                    e.witness.id,
                    e.kind,
                    e.element,
                    e.preference_independent,
                    ok,
                    reason,
                    c,
                )
            )
        return sorted(out, key=lambda x: (x.attacker, x.target, x.id))

    @cached_property
    def defeats(self):
        self._require()
        return frozenset(self.evaluation.defeats)

    @frozen_property
    def extensions(self):
        self._require()
        return [frozenset(e) for e in self.evaluation.extensions]

    @cached_property
    def _defeaters(self):
        d = {i: set() for i in self._objects}
        for x, y in self.defeats:
            d[y].add(x)
        return d

    @cached_property
    def _defeated(self):
        d = {i: set() for i in self._objects}
        for x, y in self.defeats:
            d[x].add(y)
        return d

    @frozen_property
    def labellings(self):
        out = []
        for ext in self.extensions:
            out.append(
                {
                    i: "IN" if i in ext else "OUT" if self._defeaters[i] & ext else "UNDEC"
                    for i in self._objects
                }
            )
        return out

    @frozen_property
    def grounded(self):
        label, rounds = grounded_labelling(self._objects, self.defeats)
        return {i: {"label": label[i], "round": rounds.get(i)} for i in self._objects}

    @frozen_property
    def argument_statuses(self):
        exts, n = self.extensions, len(self.extensions)
        out = {}
        for i in self._objects:
            labels = tuple(l[i] for l in self.labellings)
            count = sum(1 for e in exts if i in e)
            out[i] = ArgumentStatus(
                id=i,
                sceptical=(count == n) if n else None,
                credulous=count > 0,
                acceptance=(count / n) if n else None,
                labels=labels,
                grounded_label=self.grounded[i]["label"],
                grounded_round=self.grounded[i]["round"],
                defeaters=tuple(sorted(self._defeaters[i])),
                defeated=tuple(sorted(self._defeated[i])),
            )
        return out

    def argument_status(self, ref):
        return self.argument_statuses[self._id(ref)]

    @cached_property
    def _bearers(self):
        out = {}
        for i, a in self._objects.items():
            out.setdefault(str(a.conclusion), set()).add(i)
        return out

    @frozen_property
    def claims(self):
        return {c: self.claim(c) for c in sorted(self._bearers)}

    def claim(self, literal):
        self._require()
        literal = str(literal)
        bearers = self._bearers.get(literal, set())
        exts, n = self.extensions, len(self.extensions)
        accepted = tuple(tuple(sorted(bearers & e)) for e in exts)
        conflicts = self.evaluation.theory.conflicts
        opponents = sorted(c for c in self._bearers if (c, literal) in conflicts)
        if not bearers:
            status = "UNSUPPORTED"
        elif not n:
            status = "NO_EXTENSIONS"
        else:
            status = self.evaluation.statuses[literal]
        g = {self.grounded[b]["label"] for b in bearers}
        hc = self.strengths(collapse_clones=True)
        count = sum(1 for x in accepted if x)
        return ClaimInfo(
            claim=literal,
            status=status,
            sceptical=(count == n) if n and bearers else (None if not n else False),
            credulous=count > 0,
            acceptance=(count / n) if n else None,
            bearers=tuple(sorted(bearers)),
            accepted_bearers=accepted,
            grounded_label=(
                "IN" if "IN" in g else "UNDEC" if "UNDEC" in g else "OUT" if g else "NONE"
            ),
            strength=max((hc[b] for b in bearers), default=0.0),
            opponents=tuple(opponents),
            opposing_bearers=tuple(sorted(b for c in opponents for b in self._bearers[c])),
        )

    def is_justified(self, literal):
        return self.claim(literal).status == "JUSTIFIED"

    @frozen_property
    def argument_classes(self):
        groups = {}
        for i, a in self._objects.items():
            key = (str(a.conclusion), frozenset(self._defeaters[i]), frozenset(self._defeated[i]))
            groups.setdefault(key, []).append(i)
        return sorted((sorted(g) for g in groups.values()), key=lambda g: (-len(g), g))

    @frozen_property
    def redundancy(self):
        same_reasons = {}
        for i, a in self.arguments.items():
            key = (a.conclusion, a.ordinary_premises, a.axioms, a.defeasible_rules, a.strict_rules)
            same_reasons.setdefault(key, []).append(i)
        return {
            "arguments": len(self._objects),
            "claims": len(self._bearers),
            "distinct_premise_and_rule_sets": len(same_reasons),
            "dialectical_roles": len(self.argument_classes),
            "arguments_per_claim": {c: len(b) for c, b in sorted(self._bearers.items())},
        }

    def strengths(self, method="h_categorizer", weights=None, collapse_clones=False):
        self._require()
        key = (method, None if weights is None else tuple(sorted(weights.items())), collapse_clones)
        cache = self.__dict__.setdefault("_strength_cache", {})
        if key not in cache:
            if not collapse_clones:
                cache[key] = _strengths(self._objects, self.defeats, method, weights)
            else:
                role = {i: k for k, members in enumerate(self.argument_classes) for i in members}
                class_weights = None
                if weights is not None:
                    class_weights = {
                        k: max(weights.get(i, 1.0) for i in m)
                        for k, m in enumerate(self.argument_classes)
                    }
                edges = {(role[x], role[y]) for x, y in self.defeats}
                values = _strengths(range(len(self.argument_classes)), edges, method, class_weights)
                cache[key] = {i: values[role[i]] for i in self._objects}
            cache[key] = freeze(cache[key])
        return cache[key]

    @frozen_property
    def well_definedness(self):
        evaluated = self.evaluation.theory
        submitted = self.submitted_theory if self.submitted_theory is not None else evaluated
        if evaluated is None:
            evaluated = submitted
        if evaluated is None:
            return {"submitted": None, "evaluated": {"well_defined": None}}
        out = {"evaluated": diagnose(evaluated).to_dict()}
        out["submitted"] = (
            out["evaluated"] if submitted == evaluated else diagnose(submitted).to_dict()
        )
        return out

    @frozen_property
    def postulates(self):
        self._require()
        return check_postulates(self.evaluation).to_dict()

    @frozen_property
    def warnings(self):
        out = []
        report = self.well_definedness["evaluated"]
        if report and report.get("well_defined") is False:
            if report["missing_transpositions"]:
                out.append(
                    "Strict rules are not closed under transposition (%d missing); consistency "
                    "is not guaranteed. Use transposition=True."
                    % len(report["missing_transpositions"])
                )
            if not report["axiom_consistent"]:
                out.append("Axioms are inconsistent under strict-rule closure.")
            if not report["well_formed"]:
                out.append("A contrary targets an axiom or a strict-rule consequent.")
        if self.ok:
            if not self.postulates["satisfied"]:
                out.append("Rationality postulates are violated by at least one extension.")
            if not self.extensions:
                out.append("The %s family is empty." % self.config.semantics)
            if str(self.evaluation.policy).startswith("QUOTIENT"):
                out.append("Cyclic rules: arguments are representatives of quotient classes.")
        return out

    def explain(self, ref, *, language="ENG", extension=0):
        from .language import argument_text, check, localize

        check(language)
        i = self._id(ref)
        per_extension = []
        for k, ext in enumerate(self.extensions):
            label = self.labellings[k][i]
            defeaters = sorted(self._defeaters[i])
            if label == "IN":
                why = [
                    {"defeater": b, "countered_by": sorted(self._defeaters[b] & ext)}
                    for b in defeaters
                ]
                if not defeaters:
                    text = "in the extension; it has no defeaters"
                elif all(w["countered_by"] for w in why):
                    text = "in the extension; every defeater is defeated by a member"
                else:
                    text = (
                        "in the extension without being defended; this semantics does not "
                        "require defence"
                    )
            elif label == "OUT":
                why = [{"defeated_by": sorted(self._defeaters[i] & ext)}]
                text = "defeated by a member of the extension"
            else:
                why = [
                    {"defeater": b, "label": self.labellings[k][b]}
                    for b in defeaters
                    if self.labellings[k][b] != "OUT"
                ]
                text = "neither accepted nor defeated by the extension"
            defended = all(any((c, b) in self.defeats for c in ext) for b in defeaters)
            per_extension.append(
                {
                    "extension": k,
                    "label": label,
                    "reason": text,
                    "witnesses": why,
                    "defended": defended,
                }
            )
        info = self.argument(i)
        out = {
            "argument": i,
            "alias": info.alias,
            "conclusion": info.conclusion,
            "structure": info.to_dict(),
            "status": self.argument_statuses[i].to_dict(),
            "incoming_attacks": [a.to_dict() for a in self.attacks if a.target == i],
            "outgoing_attacks": [a.to_dict() for a in self.attacks if a.attacker == i],
            "per_extension": per_extension,
            "grounded_proof": self.grounded_proof(i),
            "grounded_scope": (
                "grounded extension under defeat conflict-freeness (Def. 13)"
                if self.config.conflict_free == "defeat"
                else "grounded extension under defeat conflict-freeness (Def. 13), not the "
                "selected attack-based semantics; they agree when the theory is well defined "
                "(Prop. 16)"
            ),
        }
        out = localize(out, language)
        out["text"] = argument_text(self, i, extension=extension, language=language)
        return out

    def explain_claim(self, literal, *, language="ENG", extension=0):
        from .language import check, claim_text, localize

        check(language)
        c = self.claim(literal)
        reasons = {
            "JUSTIFIED": "every extension contains an argument for it (not necessarily the same one)",
            "DEFENSIBLE": "some, but not all, extensions contain an argument for it",
            "OVERRULED": "in every extension, every argument for it is defeated",
            "UNDECIDED": (
                "no extension contains an argument for it, and in at least one extension some "
                "argument for it is not defeated"
            ),
            "UNSUPPORTED": "no argument concludes it",
            "NO_EXTENSIONS": "the selected semantics has no extension",
        }
        out = localize({"claim": c.to_dict(), "reason": reasons[c.status]}, language)
        out["text"] = claim_text(self, literal, extension=extension, language=language)
        out["arguments"] = [self.explain(b, language=language, extension=extension) for b in c.bearers]
        return out

    def grounded_proof(self, ref):
        i = self._id(ref)
        if self.grounded[i]["label"] != "IN":
            return None
        steps, todo = {}, [i]
        while todo:
            a = todo.pop()
            if a in steps:
                continue
            replies = {}
            for b in sorted(self._defeaters[a]):
                counters = [
                    c
                    for c in self._defeaters[b]
                    if self.grounded[c]["label"] == "IN"
                    and self.grounded[c]["round"] < self.grounded[a]["round"]
                ]
                counter = min(counters, key=lambda c: (self.grounded[c]["round"], c))
                replies[b] = counter
                todo.append(counter)
            steps[a] = {"round": self.grounded[a]["round"], "replies": replies}
        return {"root": i, "steps": steps}

    def verify_grounded_proof(self, proof):
        try:
            if not isinstance(proof, (dict, MappingProxyType)):
                return False
            root, steps = proof.get("root"), proof.get("steps")
            if not isinstance(steps, (dict, MappingProxyType)) or root not in steps:
                return False
            known = self._objects
            for a, step in steps.items():
                if a not in known or not isinstance(step, (dict, MappingProxyType)):
                    return False
                rnd, replies = step.get("round"), step.get("replies")
                if (
                    type(rnd) is not int
                    or rnd < 0
                    or not isinstance(replies, (dict, MappingProxyType))
                ):
                    return False
                if set(replies) != self._defeaters[a]:
                    return False
                for b, c in replies.items():
                    if c not in steps or (c, b) not in self.defeats:
                        return False
                    other = (
                        steps[c].get("round")
                        if isinstance(steps[c], (dict, MappingProxyType))
                        else None
                    )
                    if type(other) is not int or other >= rnd:
                        return False
            state = {}

            def acyclic(node):
                if state.get(node) == 1:
                    return False
                if state.get(node) == 2:
                    return True
                state[node] = 1
                for c in steps[node]["replies"].values():
                    if not acyclic(c):
                        return False
                state[node] = 2
                return True

            return all(acyclic(a) for a in steps)
        except (TypeError, AttributeError, KeyError, RecursionError):
            return False

    def dialectical_tree(self, ref, max_depth=4, max_nodes=500):
        root = self._id(ref)
        count = [0]

        def build(node, path, depth):
            count[0] += 1
            item = {"argument": node, "alias": self.arguments[node].alias, "children": []}
            if depth >= max_depth or count[0] >= max_nodes:
                item["truncated"] = bool(self._defeaters[node] - path)
                return item
            for b in sorted(self._defeaters[node] - path):
                if count[0] >= max_nodes:
                    item["truncated"] = True
                    break
                item["children"].append(build(b, path | {b}, depth + 1))
            return item

        return build(root, {root}, 0)

    def graph(self, kind="defeat"):
        if kind not in GRAPH_KINDS:
            raise ValueError("graph kind must be one of %s" % (GRAPH_KINDS,))
        cache = self.__dict__.setdefault("_graph_cache", {})
        if kind not in cache:
            cache[kind] = getattr(self, "_graph_" + kind)()
        return cache[kind]

    def _argument_nodes(self):
        hc = self.strengths()
        nodes = []
        for i, info in self.arguments.items():
            st = self.argument_statuses[i]
            nodes.append(
                {
                    "id": i,
                    "label": "%s: %s" % (info.alias, info.conclusion),
                    "alias": info.alias,
                    "conclusion": info.conclusion,
                    "kind": info.kind,
                    "text": info.text,
                    "depth": info.depth,
                    "label_status": st.grounded_label,
                    "sceptical": st.sceptical,
                    "credulous": st.credulous,
                    "acceptance": st.acceptance,
                    "strength": hc[i],
                }
            )
        return tuple(nodes)

    def _graph_defeat(self):
        types = {}
        for a in self.attacks:
            if a.succeeds:
                types.setdefault((a.attacker, a.target), set()).add(a.type)
        edges = tuple(
            {"source": x, "target": y, "types": sorted(types.get((x, y), ()))}
            for x, y in sorted(self.defeats)
        )
        return Graph(
            "defeat", self._argument_nodes(), edges, description="successful attacks (defeats)"
        )

    def _graph_attack(self):
        edges = tuple(
            {
                "source": a.attacker,
                "target": a.target,
                "type": a.type,
                "on": a.on,
                "succeeds": a.succeeds,
                "preference_independent": a.preference_independent,
            }
            for a in self.attacks
        )
        return Graph("attack", self._argument_nodes(), edges, description="all attack witnesses")

    def _graph_support(self):
        edges = []
        for i, info in self.arguments.items():
            for child in info.direct_subarguments:
                if child in self.arguments:
                    edges.append({"source": child, "target": i, "rule": info.top_rule})
        return Graph(
            "support", self._argument_nodes(), tuple(edges), description="subargument -> argument"
        )

    def _graph_claim(self):
        nodes = tuple(
            {
                "id": c,
                "label": c,
                "status": info.status,
                "strength": info.strength,
                "bearers": len(info.bearers),
            }
            for c, info in self.claims.items()
        )
        conc = {i: info.conclusion for i, info in self.arguments.items()}
        weight = {}
        for x, y in self.defeats:
            weight[(conc[x], conc[y])] = weight.get((conc[x], conc[y]), 0) + 1
        edges = tuple(
            {"source": a, "target": b, "defeats": n} for (a, b), n in sorted(weight.items())
        )
        return Graph("claim", nodes, edges, description="claim-level defeat (aggregated)")

    def _graph_rule_dependency(self):
        theory = self.evaluation.theory
        literals = sorted(
            {str(l) for r in theory.rules for l in (*r.antecedents, r.consequent)}
            | {str(f.literal) for f in theory.facts}
        )
        nodes = tuple(
            {"id": l, "label": l, "fact": any(str(f.literal) == l for f in theory.facts)}
            for l in literals
        )
        edges = tuple(
            {"source": str(a), "target": str(r.consequent), "rule": r.name, "kind": r.kind}
            for r in theory.rules
            for a in r.antecedents
        )
        return Graph("rule_dependency", nodes, edges, description="antecedent -> consequent")

    def _graph_conflict(self):
        theory = self.evaluation.theory
        used = {str(l) for l in theory.object_literals} | {
            r.name for r in theory.rules if r.kind == "defeasible"
        }
        pairs = sorted(
            (str(x), str(y)) for x, y in theory.conflicts if str(x) in used and str(y) in used
        )
        nodes = tuple({"id": l, "label": l} for l in sorted({l for p in pairs for l in p}))
        edges = tuple(
            {"source": x, "target": y, "symmetric": (y, x) in set(pairs)} for x, y in pairs
        )
        return Graph(
            "conflict", nodes, edges, description="x -> y: x is a contrary or contradictory of y"
        )

    def features(self, invariant_only=False):
        self._require()
        n = len(self._objects)
        exts = self.extensions
        types = {"rebut": 0, "undermine": 0, "undercut": 0}
        for a in self.attacks:
            types[a.type] += 1
        g = [v["label"] for v in self.grounded.values()]
        hc = list(self.strengths().values())
        claims = [c.status for c in self.claims.values()]
        metrics = self.graph("defeat").metrics()
        st = self.argument_statuses.values()
        f = {
            "arguments": n,
            "claims": len(claims),
            "attacks": len(self.attacks),
            "rebuts": types["rebut"],
            "undermines": types["undermine"],
            "undercuts": types["undercut"],
            "defeats": len(self.defeats),
            "attack_success_rate": (
                (sum(a.succeeds for a in self.attacks) / len(self.attacks)) if self.attacks else 0.0
            ),
            "extensions": len(exts),
            "empty_family": float(not exts),
            "mean_extension_size": (sum(map(len, exts)) / len(exts) / n) if exts and n else 0.0,
            "sceptical_fraction": (sum(bool(s.sceptical) for s in st) / n) if n else 0.0,
            "credulous_fraction": (sum(s.credulous for s in st) / n) if n else 0.0,
            "grounded_in": g.count("IN") / n if n else 0.0,
            "grounded_out": g.count("OUT") / n if n else 0.0,
            "grounded_undec": g.count("UNDEC") / n if n else 0.0,
            "strength_mean": sum(hc) / n if n else 0.0,
            "strength_min": min(hc, default=0.0),
            "strength_max": max(hc, default=0.0),
            "max_depth": max((a.depth for a in self._objects.values()), default=0),
            "defeat_density": metrics["density"],
            "cyclic_components": metrics["cyclic_components"],
            "odd_cycle_components": metrics["odd_cycle_components"],
            "well_defined": float(bool(self.well_definedness["evaluated"].get("well_defined"))),
            "postulates_satisfied": float(self.postulates["satisfied"]),
        }
        for s in CLAIM_STATUSES[:4]:
            f["claims_" + s.lower()] = claims.count(s) / len(claims) if claims else 0.0
        f["roles"] = len(self.argument_classes)
        cs = [c.strength for c in self.claims.values()]
        f["claim_strength_mean"] = sum(cs) / len(cs) if cs else 0.0
        if invariant_only:
            keep = {"invariant"}
            if self.config.semantics not in ("conflict_free", "admissible"):
                keep.add("invariant_except_cf_adm")
            f = {k: v for k, v in f.items() if FEATURE_BASIS[k] in keep}
        return {k: float(v) for k, v in f.items()}

    @staticmethod
    def feature_basis():
        return dict(FEATURE_BASIS)

    def diff(self, other):
        a, b = set(self._objects), set(other._objects)
        claims = sorted(set(self._bearers) | set(other._bearers))
        changed = {}
        for c in claims:
            x, y = self.claim(c).status, other.claim(c).status
            if x != y:
                changed[c] = {"before": x, "after": y}
        return {
            "arguments_added": sorted(b - a),
            "arguments_removed": sorted(a - b),
            "defeats_added": sorted(other.defeats - self.defeats),
            "defeats_removed": sorted(self.defeats - other.defeats),
            "extensions_before": len(self.extensions),
            "extensions_after": len(other.extensions),
            "claims_changed": changed,
        }

    def to_dict(
        self,
        include=("arguments", "attacks", "extensions", "claims", "statuses", "strengths"),
        include_timings=False,
    ):
        out = {
            "status": self.status,
            "error": self.error,
            "config": self.config.to_dict(),
            "warnings": list(self.warnings) if self.evaluation.theory is not None else [],
            "resource": (
                {
                    k: plain(v)
                    for k, v in dict(self.evaluation.resource).items()
                    if include_timings or "elapsed" not in k
                }
                if self.evaluation.resource
                else None
            ),
        }
        if include_timings:
            out["timings"] = plain(dict(self.evaluation.timings)) if self.evaluation.timings else {}
        if not self.ok:
            return out
        out["theory"] = self.evaluation.theory.to_source()
        out["well_definedness"] = plain(self.well_definedness)
        out["postulates_satisfied"] = self.postulates["satisfied"]
        if "arguments" in include:
            out["arguments"] = [a.to_dict() for a in self.arguments.values()]
        if "attacks" in include:
            out["attacks"] = [a.to_dict() for a in self.attacks]
            out["defeats"] = [list(d) for d in sorted(self.defeats)]
        if "extensions" in include:
            out["extensions"] = [sorted(e) for e in self.extensions]
        if "claims" in include:
            out["claims"] = {c: info.to_dict() for c, info in self.claims.items()}
        if "statuses" in include:
            out["argument_statuses"] = {i: s.to_dict() for i, s in self.argument_statuses.items()}
        if "strengths" in include:
            out["strengths"] = dict(self.strengths())
        return out

    def to_json(self, include_timings=False, **kwargs):
        return json.dumps(self.to_dict(include_timings=include_timings), ensure_ascii=False, **kwargs)

    def summary(self):
        if not self.ok:
            return "%s: %s" % (self.status, self.error)
        lines = [
            "%s semantics, %s/%s ordering: %d arguments, %d defeats, %d extension(s)"
            % (
                self.config.semantics,
                self.config.ordering,
                self.config.set_ordering,
                len(self._objects),
                len(self.defeats),
                len(self.extensions),
            )
        ]
        for c, info in self.claims.items():
            lines.append("  %-12s %s" % (info.status, c))
        lines.extend("  warning: " + w for w in self.warnings)
        return "\n".join(lines)

    def __repr__(self):
        return "<Result %s %s args=%s>" % (
            self.status,
            self.config.semantics,
            len(self.evaluation.arguments),
        )
