from itertools import product
from time import monotonic
from dataclasses import dataclass
from .model import Argument


class ConstructionLimit(RuntimeError):
    status = "LIMIT_REACHED"


@dataclass
class Budget:
    max_arguments: int | None = None
    max_candidates: int | None = None
    seconds: float | None = None

    def __post_init__(self):
        for value in (self.max_arguments, self.max_candidates, self.seconds):
            if value is not None and value <= 0:
                raise ValueError("budget must be positive")
        self.started = monotonic()
        self.candidates = 0

    def check(self, count, candidate=False):
        self.candidates += int(candidate)
        if (
            (self.max_arguments is not None and count > self.max_arguments)
            or (self.max_candidates is not None and self.candidates > self.max_candidates)
            or (self.seconds is not None and monotonic() - self.started > self.seconds)
        ):
            raise ConstructionLimit("construction budget exhausted; no complete result available")


class NativeExactConstructor:
    name = "NativeExact"

    def construct(self, theory, budget=None):
        if theory.topological_literals is None:
            raise ValueError("NativeExact requires an acyclic dependency graph")
        budget = budget or Budget()
        pools = {l: set() for l in theory.language}
        for f in theory.facts:
            pools[f.literal].add(Argument(f.literal, premise=f))
        count = sum(map(len, pools.values()))
        budget.check(count)
        for conclusion in theory.topological_literals:
            for rule in sorted(
                (r for r in theory.rules if r.consequent == conclusion),
                key=lambda r: r.name,
            ):
                for children in product(*(pools[a] for a in rule.antecedents)):
                    budget.check(count, True)
                    argument = Argument(rule.consequent, rule, children)
                    if argument not in pools[conclusion]:
                        pools[conclusion].add(argument)
                        count += 1
                        budget.check(count)
        return frozenset().union(*pools.values())


class CyclicConstructor:
    def __init__(self, policy="QUOTIENT", depth=None):
        if policy not in (
            "REJECT",
            "P_LITERAL",
            "P_RULE",
            "P_STATE",
            "UNRESTRICTED_UNROLL",
            "QUOTIENT",
            "QUOTIENT_ATTACKABLE",
        ):
            raise ValueError("unknown cycle policy")
        if policy == "UNRESTRICTED_UNROLL" and (not isinstance(depth, int) or depth < 0):
            raise ValueError("unrolling requires a nonnegative depth")
        self.policy = policy
        self.depth = depth
        self.rounds = 0

    def construct(self, theory, budget=None):
        if self.policy == "REJECT":
            raise ValueError("cyclic theory rejected")
        budget = budget or Budget()
        pools = {l: [] for l in theory.language}
        known = {}

        def insert(a):
            key = (
                a.semantic_signature
                if self.policy == "QUOTIENT"
                else a.attack_class_signature if self.policy == "QUOTIENT_ATTACKABLE" else a
            )
            if key in known:
                return False
            known[key] = a
            pools[a.conclusion].append(a)
            budget.check(len(known))
            return True

        for f in theory.facts:
            insert(Argument(f.literal, premise=f))
        while True:
            changed = False
            self.rounds += 1
            for rule in sorted(theory.rules, key=lambda r: r.name):
                choices = [tuple(pools[a]) for a in rule.antecedents]
                for children in product(*choices):
                    budget.check(len(known), True)
                    if self.policy == "P_LITERAL" and any(
                        rule.consequent == s.conclusion for c in children for s in c.subarguments
                    ):
                        continue
                    if self.policy == "P_RULE" and any(
                        s.top_rule == rule for c in children for s in c.subarguments
                    ):
                        continue
                    if self.policy == "P_STATE" and any(
                        (s.conclusion, s.top_rule) == (rule.consequent, rule)
                        for c in children
                        for s in c.subarguments
                    ):
                        continue
                    if (
                        self.policy == "UNRESTRICTED_UNROLL"
                        and 1 + max((c.depth for c in children), default=-1) > self.depth
                    ):
                        continue
                    changed = insert(Argument(rule.consequent, rule, children)) or changed
            if not changed:
                return frozenset(known.values())
