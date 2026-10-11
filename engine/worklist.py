from collections import deque, defaultdict
from itertools import product
from .model import Argument
from .construction import Budget


class QuotientWorklistConstructor:

    name = "QuotientWorklist"

    def __init__(self, signature="semantic_signature"):
        if signature not in ("semantic_signature", "attack_class_signature"):
            raise ValueError("unknown quotient signature")
        self.signature = signature

    def construct(self, theory, budget=None):
        signature = self.signature
        budget = budget or Budget()
        known = {}
        pools = defaultdict(list)
        agenda = deque()
        dependents = defaultdict(list)
        seen = set()
        self.rule_activations = 0
        self.applications = 0
        rules = sorted(theory.rules, key=lambda r: r.name)
        for r in rules:
            for index, literal in enumerate(r.antecedents):
                dependents[literal].append((r, index))

        def insert(a):
            sig = getattr(a, signature)
            if sig in known:
                return
            known[sig] = a
            pools[a.conclusion].append(a)
            agenda.append(a)
            budget.check(len(known))

        def apply(r, children):
            key = (r.name, tuple(getattr(c, signature) for c in children))
            if key in seen:
                return
            budget.check(len(known), True)
            seen.add(key)
            self.applications += 1
            insert(Argument(r.consequent, r, children))

        for f in theory.facts:
            insert(Argument(f.literal, premise=f))
        for r in rules:
            if not r.antecedents:
                apply(r, ())
        while agenda:
            delta = agenda.popleft()
            for r, index in dependents[delta.conclusion]:
                self.rule_activations += 1
                choices = [
                    (delta,) if j == index else tuple(pools[l]) for j, l in enumerate(r.antecedents)
                ]
                for children in product(*choices):
                    apply(r, children)
        return frozenset(known.values())
