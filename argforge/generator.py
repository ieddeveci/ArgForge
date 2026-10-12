from __future__ import annotations

from dataclasses import asdict, dataclass

MASK = 0xFFFFFFFF


class Mulberry32:

    def __init__(self, seed):
        self.state = int(seed) & MASK

    def next(self):
        self.state = (self.state + 0x6D2B79F5) & MASK
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK)) & MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296.0

    def below(self, n):
        return int(self.next() * n)

    def chance(self, p):
        return self.next() < p

    def pick(self, items):
        return items[self.below(len(items))]

    def sample(self, items, k):
        pool = list(items)
        out = []
        for _ in range(min(k, len(pool))):
            out.append(pool.pop(self.below(len(pool))))
        return out


@dataclass(frozen=True)
class GeneratorParams:
    atoms: int = 6
    premises: int = 4
    axioms: int = 1
    rules: int = 8
    strict_ratio: float = 0.25
    max_antecedents: int = 2
    conflict: float = 0.4
    undercuts: float = 0.15
    rule_preferences: float = 0.3
    premise_preferences: float = 0.2
    contraries: float = 0.1
    contradictories: float = 0.1
    negation: float = 0.3
    premise_conflicts: float = 0.15
    acyclic: bool = True
    transposition: bool = False

    def __post_init__(self):
        for name in ("acyclic", "transposition"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("%s must be True or False" % name)
        for name in ("atoms", "premises", "axioms", "rules", "max_antecedents"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("%s must be a non-negative integer" % name)
        if self.atoms < 1 or self.atoms > 200:
            raise ValueError("atoms must be between 1 and 200")
        if self.premises + self.axioms < 1:
            raise ValueError("at least one premise or axiom is required")
        if self.premises + self.axioms > 2 * self.atoms:
            raise ValueError("more facts than literals")
        if self.axioms > self.atoms:
            raise ValueError(
                "axioms must not exceed atoms (axioms use distinct atoms, so they stay consistent)"
            )
        if self.rules > 0 and self.acyclic and self.atoms < 2:
            raise ValueError(
                "acyclic rules need at least 2 atoms (a rule's conclusion must come after its antecedents)"
            )
        if self.rules > 400 or self.max_antecedents < 1 or self.max_antecedents > 6:
            raise ValueError("rules must be <= 400 and max_antecedents in 1..6")
        for name in (
            "strict_ratio",
            "conflict",
            "undercuts",
            "rule_preferences",
            "premise_preferences",
            "contraries",
            "contradictories",
            "negation",
            "premise_conflicts",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise ValueError("%s must be a probability in [0, 1]" % name)

    def to_dict(self):
        return asdict(self)


def _neg(literal):
    return literal[1:] if literal.startswith("-") else "-" + literal


def generate_source(seed, params=None):
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    p = params if isinstance(params, GeneratorParams) else GeneratorParams(**(params or {}))
    rng = Mulberry32(seed)
    atoms = ["a%d" % (i + 1) for i in range(p.atoms)]
    order = rng.sample(atoms, len(atoms))
    rank = {a: i for i, a in enumerate(order)}

    def signed(atom):
        return "-" + atom if rng.chance(p.negation) else atom

    facts, fact_atoms = [], set()
    for _ in range(p.axioms):
        free = [a for a in order if a not in fact_atoms]
        if not free:
            break
        atom = rng.pick(free)
        fact_atoms.add(atom)
        facts.append(("axiom", signed(atom)))
    taken = {lit for _, lit in facts}
    for _ in range(p.premises):
        opposable = [_neg(l) for _, l in facts if _neg(l) not in taken]
        fresh = [a for a in order if a not in fact_atoms]
        if opposable and (not fresh or rng.chance(p.premise_conflicts)):
            literal = rng.pick(opposable)
        elif fresh:
            literal = signed(rng.pick(fresh))
        else:
            break
        taken.add(literal)
        fact_atoms.add(literal.lstrip("-"))
        facts.append(("premise", literal))
    axioms = {l for k, l in facts if k == "axiom"}
    derivable = [l for _, l in facts]

    rules = []
    strict_heads = set()
    n_strict = int(p.rules * p.strict_ratio + 0.5)
    kinds = ["strict"] * n_strict + ["defeasible"] * (p.rules - n_strict)
    kinds = rng.sample(kinds, len(kinds))
    counters = {"strict": 0, "defeasible": 0}
    for kind in kinds:
        if not derivable:
            break
        count = 1 + rng.below(min(p.max_antecedents, len(derivable)))
        antecedents = []
        for _ in range(count):
            choice = rng.pick(derivable)
            if choice not in antecedents and _neg(choice) not in antecedents:
                antecedents.append(choice)
        used = {a.lstrip("-") for a in antecedents}
        if p.acyclic:
            top = max(rank[a] for a in used)
            heads = [a for a in order if rank[a] > top]
        else:
            heads = [a for a in order if a not in used]
        if not heads:
            continue
        head_atom = rng.pick(heads)
        positive = head_atom
        if rng.chance(p.conflict) and (positive in derivable or "-" + positive in derivable):
            consequent = "-" + positive if positive in derivable else positive
        else:
            consequent = signed(positive)
        if kind == "strict" and (
            consequent in axioms or _neg(consequent) in axioms or _neg(consequent) in strict_heads
        ):
            kind = "defeasible"
        counters[kind] += 1
        name = ("s%d" if kind == "strict" else "r%d") % counters[kind]
        body = set(antecedents)
        if any(
            (r[3] == consequent and (body >= set(r[2]) or body <= set(r[2])))
            or (r[3] == _neg(consequent) and body == set(r[2]))
            for r in rules
        ):
            counters[kind] -= 1
            continue
        rules.append((kind, name, tuple(sorted(set(antecedents))), consequent))
        if kind == "strict":
            strict_heads.add(consequent)
        if consequent not in derivable:
            derivable.append(consequent)

    defeasible = [r[1] for r in rules if r[0] == "defeasible"]
    for name in list(defeasible):
        if rng.chance(p.undercuts):
            counters["defeasible"] += 1
            uname = "r%d" % counters["defeasible"]
            ante = (rng.pick(derivable),)
            rules.append(("defeasible", uname, ante, "-" + name))

    defeasible = [r[1] for r in rules if r[0] == "defeasible"]
    ranking = rng.sample(defeasible, len(defeasible))
    rule_prefs = []
    for i in range(len(ranking)):
        for j in range(i + 1, len(ranking)):
            if rng.chance(min(1.0, p.rule_preferences / max(1, len(ranking) - 1) * 2)):
                rule_prefs.append((ranking[i], ranking[j]))
    premises = [l for k, l in facts if k == "premise"]
    pranking = rng.sample(premises, len(premises))
    premise_prefs = []
    for i in range(len(pranking)):
        for j in range(i + 1, len(pranking)):
            if rng.chance(p.premise_preferences):
                premise_prefs.append((pranking[i], pranking[j]))
    contraries = []
    blocked = set(strict_heads) | {_neg(a) for r in rules if r[0] == "strict" for a in r[2]}
    for target in premises:
        if target in blocked:
            continue
        if rng.chance(p.contraries):
            source = rng.pick(
                [l for l in derivable if l != target and l != _neg(target)] or [_neg(target)]
            )
            if source != _neg(target) and (target, source) not in contraries:
                contraries.append((source, target))

    lines = ["[%s: %s]" % (k, l) for k, l in facts]
    for kind, name, ante, cons in rules:
        arrow = "->" if kind == "strict" else "=>"
        lines.append("[%s %s: %s %s %s]" % (kind, name, " & ".join(ante), arrow, cons))
    lines += ["[prefer_rule: %s > %s]" % x for x in rule_prefs]
    lines += ["[prefer_premise: %s > %s]" % x for x in premise_prefs]

    from engine import Theory
    from engine.wellformed import close_under_transposition, diagnose

    def closed(extra):
        return close_under_transposition(Theory.parse("\n".join(lines + extra) + "\n"))

    tail, paired = [], set()
    fixed = set(axioms) | set(strict_heads)
    for literal in list(derivable):
        if literal in fixed or literal in paired:
            continue
        if rng.chance(p.contradictories):
            options = [
                m
                for m in derivable
                if m.lstrip("-") != literal.lstrip("-") and m not in fixed and m not in paired
            ]
            if options:
                partner = rng.pick(options)
                candidate = tail + ["[contradictory: %s ^ %s]" % (literal, partner)]
                if diagnose(closed(candidate)).axiom_consistent:
                    tail = candidate
                    paired.update((literal, partner))
    heads = {str(r.consequent) for r in closed(tail).rules if r.kind == "strict"}
    lines += ["[contrary: %s ^ %s]" % x for x in contraries if x[1] not in heads]
    lines += tail
    return "\n".join(lines) + "\n"


VARIED_SIZES = {"small": (3, 4), "medium": (5, 7), "large": (8, 11), "any": (3, 8)}


def varied_params(seed, size="medium"):
    lo, hi = VARIED_SIZES[size]
    r = Mulberry32((seed + 1540483477) & 0xFFFFFFFF)
    atoms = lo + r.below(hi - lo + 1)
    axioms = r.below(min(2, atoms) + 1)
    premises = r.below(atoms - axioms + 1)
    return GeneratorParams(
        atoms=atoms,
        axioms=axioms,
        premises=premises if premises + axioms > 0 else 1,
        rules=r.below(2 * atoms + 1),
        strict_ratio=r.pick([0.0, 0.0, 0.25, 0.5, 1.0]),
        max_antecedents=1 + r.below(3),
        negation=r.pick([0.0, 0.2, 0.5]),
        premise_conflicts=r.pick([0.0, 0.0, 0.2, 0.5]),
        conflict=r.pick([0.0, 0.3, 0.6]),
        undercuts=r.pick([0.0, 0.0, 0.2, 0.4]),
        rule_preferences=r.pick([0.0, 0.3, 0.7]),
        premise_preferences=r.pick([0.0, 0.3]),
        contraries=r.pick([0.0, 0.0, 0.2]),
        contradictories=r.pick([0.0, 0.0, 0.2]),
        acyclic=r.chance(0.8),
    )


@dataclass(frozen=True)
class GeneratedTheory:

    seed: int
    source: str
    theory: object
    requested: dict
    actual: dict


def generate(seed, params=None):
    from engine import Theory
    from engine.wellformed import close_under_transposition

    p = params if isinstance(params, GeneratorParams) else GeneratorParams(**(params or {}))
    source = generate_source(seed, p)
    base = Theory.parse(source)
    theory = close_under_transposition(base) if p.transposition else base
    names = {r.name for r in base.rules}
    undercutters = [r for r in base.rules if str(r.consequent).lstrip("-") in names]
    actual = {
        "axioms": sum(f.kind == "axiom" for f in base.facts),
        "premises": sum(f.kind == "premise" for f in base.facts),
        "base_rules": len(base.rules) - len(undercutters),
        "strict_rules": sum(r.kind == "strict" for r in base.rules),
        "defeasible_rules": sum(r.kind == "defeasible" for r in base.rules),
        "undercutters": len(undercutters),
        "rule_preferences": len(base.rule_preferences),
        "premise_preferences": len(base.premise_preferences),
        "contraries": sum(not c.symmetric for c in base.contraries),
        "contradictories": sum(c.symmetric for c in base.contraries),
        "transposed_rules": len(theory.rules) - len(base.rules),
        "rules_total": len(theory.rules),
        "cyclic": theory.topological_literals is None,
        "complementary_fact_pairs": sum(
            1
            for f in base.facts
            if not str(f.literal).startswith("-")
            and any(str(g.literal) == "-" + str(f.literal) for g in base.facts)
        ),
    }
    return GeneratedTheory(seed, source, theory, p.to_dict(), actual)


def generate_theory(seed, params=None):
    from engine import Theory
    from engine.wellformed import close_under_transposition

    p = params if isinstance(params, GeneratorParams) else GeneratorParams(**(params or {}))
    theory = Theory.parse(generate_source(seed, p))
    return close_under_transposition(theory) if p.transposition else theory


def sample(
    count,
    params=None,
    *,
    start=0,
    max_arguments=200,
    min_arguments=0,
    timeout=10,
    max_attempts=None,
):
    from .api import solve

    for name, value in (("count", count), ("start", start), ("max_arguments", max_arguments), ("min_arguments", min_arguments)):
        if type(value) is not int or value < 0:
            raise ValueError("%s must be a non-negative integer" % name)
    if max_attempts is not None and (type(max_attempts) is not int or max_attempts < 0):
        raise ValueError("max_attempts must be None or a non-negative integer")

    def params_for(seed):
        if callable(params):
            return params(seed)
        return params if isinstance(params, GeneratorParams) else GeneratorParams(**(params or {}))

    accepted, skipped = [], []
    seed = start
    limit = max_attempts if max_attempts is not None else 20 * count + 100
    while len(accepted) < count and seed - start < limit:
        p = params_for(seed)
        source = generate_source(seed, p)
        r = solve(source, transposition=p.transposition, timeout=timeout)
        if r.ok and min_arguments <= len(r.arguments) <= max_arguments:
            accepted.append((seed, source))
        else:
            skipped.append(seed)
        seed += 1
    return accepted, skipped
