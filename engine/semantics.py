import os

import clingo

from .resources import check_time, semantic_phase

ASP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "asp")
ATTACKS_LP = os.path.join(ASP_DIR, "attacks.lp")
SEMANTICS_LP = os.path.join(ASP_DIR, "semantics.lp")

with open(SEMANTICS_LP, encoding="utf-8") as _handle:
    _SEMANTICS_PROGRAM = _handle.read()
with open(ATTACKS_LP, encoding="utf-8") as _handle:
    _ATTACKS_PROGRAM = _handle.read()

DIRECT = {"conflict_free", "admissible", "complete", "stable"}
MAXIMAL = {"preferred", "naive"}
MINIMAL = {"grounded"}
DERIVED = {"ideal", "semistable", "eager"}
SEMANTICS = DIRECT | MAXIMAL | MINIMAL | DERIVED

ADMISSIBLE_PROGRAM = """
{ in(X) } :- arg(X).
out(X)    :- att(Y,X), in(Y).
:- in(X), in(Y), conf(X,Y).
:- in(X), att(Y,X), not out(Y).
hit(X)    :- in(Y), att(Y,X).
#show hit/1.
"""

COMPLETE_PROGRAM = """
{ in(X) } :- arg(X).
out(X)        :- att(Y,X), in(Y).
:- in(X), in(Y), conf(X,Y).
:- in(X), att(Y,X), not out(Y).
undefended(X) :- arg(X), att(Y,X), not out(Y).
:- arg(X), not in(X), not undefended(X).
range(X) :- in(X).
range(X) :- out(X).
#show in/1.
#show range/1.
"""


def _control(args=()):
    from .resources import ControlledSolver

    return ControlledSolver(
        clingo.Control(list(args), logger=lambda code, message: None, message_limit=0)
    )


def compute_attacks_and_defeats(facts):
    control = _control(["0"])
    control.add("base", [], facts)
    control.add("base", [], _ATTACKS_PROGRAM)
    control.ground([("base", [])])
    raw, defeats = set(), set()

    def on_model(model):
        raw.clear()
        defeats.clear()
        for symbol in model.symbols(shown=True):
            if symbol.name == "raw_attack":
                raw.add(tuple(str(x) for x in symbol.arguments))
            elif symbol.name == "defeat":
                defeats.add((str(symbol.arguments[0]), str(symbol.arguments[1])))

    control.solve(on_model=on_model)
    return raw, defeats


def _af_facts(arguments, defeats, conflicts):
    lines = [f"arg({clingo.String(a)})." for a in sorted(arguments)]
    lines += [f"att({clingo.String(x)},{clingo.String(y)})." for x, y in sorted(defeats)]
    lines += [f"conf({clingo.String(x)},{clingo.String(y)})." for x, y in sorted(conflicts)]
    return "\n".join(lines)


def _models(program, arguments, defeats, conflicts, args=(), extra=(), shown="in"):
    control = _control(["0", *args])
    control.add("base", [], _af_facts(arguments, defeats, conflicts))
    control.add("base", [], program)
    for text in extra:
        control.add("base", [], text)
    control.ground([("base", [])])
    found = []
    control.solve(
        on_model=lambda m: found.append(
            frozenset(s.arguments[0].string for s in m.symbols(shown=True) if s.name == shown)
        )
    )
    return found


def _solve(arguments, defeats, conflicts, semantics, subset_opt=None):
    semantic_phase("final_direct" if subset_opt is None else "subset_candidates")
    args = ["--enum-mode=domRec", "--heuristic=Domain"] if subset_opt else []
    extra = [f"semantics({semantics})."]
    if subset_opt == "max":
        extra.append("maximise.")
    elif subset_opt == "min":
        extra.append("minimise.")
    return _models(_SEMANTICS_PROGRAM, arguments, defeats, conflicts, args, extra)


def _extremal(sets, keep_larger):
    items = sorted(set(sets), key=len, reverse=keep_larger)
    universe = sorted(set().union(*items), key=str) if items else []
    bit = {a: 1 << i for i, a in enumerate(universe)}
    masks = {}
    for item in items:
        m = 0
        for a in item:
            m |= bit[a]
        masks[item] = m
    kept, by_element = [], {}
    for n, item in enumerate(items):
        if n % 512 == 0:
            check_time()
        m = masks[item]
        if keep_larger:
            if item:
                rarest = min(item, key=lambda a: len(by_element.get(a, ())))
                candidates = by_element.get(rarest, ())
            else:
                candidates = [masks[k] for k in kept]
            dominated = any(k != m and k & m == m for k in candidates)
        else:
            dominated = any(masks[k] != m and masks[k] & m == masks[k] for k in kept)
        if not dominated:
            kept.append(item)
            for a in item:
                by_element.setdefault(a, []).append(m)
    return kept


def _maximal(sets):
    return _extremal(sets, True)


def _minimal(sets):
    return _extremal(sets, False)


def grounded_labelling(arguments, defeats):
    attackers = {a: set() for a in arguments}
    targets = {a: set() for a in arguments}
    for x, y in defeats:
        attackers[y].add(x)
        targets[x].add(y)
    label, round_of = {}, {}
    remaining = {a: len(attackers[a]) for a in arguments}
    frontier = sorted(a for a in arguments if remaining[a] == 0)
    step = 0
    while frontier:
        newly_out = []
        for a in frontier:
            label[a] = "IN"
            round_of[a] = step
        for a in frontier:
            for b in targets[a]:
                if b not in label:
                    label[b] = "OUT"
                    round_of[b] = step
                    newly_out.append(b)
        step += 1
        nxt = set()
        for b in newly_out:
            for c in targets[b]:
                if c not in label:
                    remaining[c] -= 1
                    if remaining[c] == 0:
                        nxt.add(c)
        frontier = sorted(nxt)
    for a in arguments:
        label.setdefault(a, "UNDEC")
    return label, round_of


def _ideal_defeat(arguments, defeats):
    if not arguments:
        return [frozenset()]
    semantic_phase("ideal_brave_admissible")
    control = _control(["0", "--enum-mode=brave"])
    control.add("base", [], _af_facts(arguments, defeats, defeats))
    control.add("base", [], ADMISSIBLE_PROGRAM)
    control.ground([("base", [])])
    hits = set()

    def on_model(model):
        hits.clear()
        hits.update(s.arguments[0].string for s in model.symbols(shown=True) if s.name == "hit")

    control.solve(on_model=on_model)
    return _maximal_admissible_within(arguments, defeats, defeats, set(arguments) - hits)


def _maximal_admissible_within(arguments, defeats, conflicts, allowed):
    semantic_phase("maximal_admissible_candidates")
    forbid = [f":- in({clingo.String(a)})." for a in sorted(set(arguments) - set(allowed))]
    found = _models(
        ADMISSIBLE_PROGRAM + "#show in/1.\n#heuristic in(X) : arg(X). [1,true]\n",
        arguments,
        defeats,
        conflicts,
        ["--enum-mode=domRec", "--heuristic=Domain"],
        forbid,
    )
    return _maximal(found) or [frozenset()]


def _maximal_ranges(arguments, defeats, conflicts):
    semantic_phase("maximal_range_candidates")
    ranges = _models(
        COMPLETE_PROGRAM + "#heuristic range(X) : arg(X). [1,true]\n",
        arguments,
        defeats,
        conflicts,
        ["--enum-mode=domRec", "--heuristic=Domain"],
        shown="range",
    )
    return _maximal(ranges)


def _complete_with_exact_range(arguments, defeats, conflicts, target):
    semantic_phase("final_exact_range")
    constraints = [
        (f":- not range({clingo.String(a)})." if a in target else f":- range({clingo.String(a)}).")
        for a in sorted(arguments)
    ]
    return _models(COMPLETE_PROGRAM, arguments, defeats, conflicts, (), constraints)


def _semistable(arguments, defeats, conflicts):
    result = set()
    for target in _maximal_ranges(arguments, defeats, conflicts):
        result.update(_complete_with_exact_range(arguments, defeats, conflicts, target))
    return sorted(result, key=sorted)


def extensions(arguments, defeats, semantics, conflicts=None):
    if semantics not in SEMANTICS:
        raise ValueError(semantics)
    arguments, defeats = set(arguments), set(defeats)
    if any(not isinstance(a, str) for a in arguments):
        raise TypeError("argument ids must be strings")
    attack_cf = conflicts is not None
    conflicts = set(conflicts) if attack_cf else defeats
    if any(x not in arguments or y not in arguments for x, y in defeats | conflicts):
        raise ValueError("relation endpoint outside the argument set")

    if semantics == "grounded":
        if not attack_cf:
            semantic_phase("final_direct")
            label, _ = grounded_labelling(arguments, defeats)
            return [frozenset(a for a, v in label.items() if v == "IN")]
        found = _solve(arguments, defeats, conflicts, "complete", subset_opt="min")
        return sorted(_minimal(found), key=sorted)
    if semantics in DIRECT:
        return _solve(arguments, defeats, conflicts, semantics)
    if semantics in MAXIMAL:
        base = "complete" if semantics == "preferred" else "conflict_free"
        return sorted(_maximal(_solve(arguments, defeats, conflicts, base, "max")), key=sorted)
    if semantics == "semistable":
        return _semistable(arguments, defeats, conflicts)
    if semantics == "ideal" and not attack_cf:
        return _ideal_defeat(arguments, defeats)
    family = (
        extensions(arguments, defeats, "preferred", conflicts if attack_cf else None)
        if semantics == "ideal"
        else _semistable(arguments, defeats, conflicts)
    )
    if not family:
        return []
    common = frozenset.intersection(*map(frozenset, family))
    return sorted(_maximal_admissible_within(arguments, defeats, conflicts, common), key=sorted)
