from __future__ import annotations

from engine import Theory


def verbalize(theory):
    t = theory if isinstance(theory, Theory) else Theory.parse(theory)
    say = lambda l: ("it is not the case that " + l[1:] if l.startswith("-") else l).replace(
        "_", " "
    )
    rule_names = {r.name for r in t.rules}
    out = []
    for f in t.facts:
        out.append(
            f"{'It is certain that' if f.kind == 'axiom' else 'It is assumed that'} {say(str(f.literal))}."
        )
    for r in t.rules:
        cond = " and ".join(say(str(a)) for a in r.antecedents) or "always"
        head = str(r.consequent)
        if head.startswith("-") and head[1:] in rule_names:
            out.append(f"Rule {r.name}: if {cond}, then rule {head[1:]} does not apply.")
        else:
            out.append(
                f"Rule {r.name}: if {cond}, then {'necessarily' if r.kind == 'strict' else 'usually'} {say(head)}."
            )
    out += [f"Rule {p.stronger} takes priority over rule {p.weaker}." for p in t.rule_preferences]
    out += [
        f"'{say(str(p.stronger))}' is more reliable than '{say(str(p.weaker))}'."
        for p in t.premise_preferences
    ]
    for c in t.contraries:
        if c.symmetric:
            out.append(f"'{say(str(c.source))}' and '{say(str(c.target))}' exclude each other.")
        else:
            out.append(f"'{say(str(c.source))}' defeats '{say(str(c.target))}' outright.")
    return out
