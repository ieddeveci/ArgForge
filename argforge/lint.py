from __future__ import annotations

import re

from engine.wellformed import diagnose

from .api import as_theory


def _norm(literal):
    neg = literal.startswith("-")
    core = literal[1:] if neg else literal
    core = re.sub(r"[\s\-]+", "_", core.strip().lower())
    return ("-" if neg else "") + core


def lint(theory):
    t = as_theory(theory)
    findings = []
    add = lambda code, sev, msg, items: findings.append(
        {"code": code, "severity": sev, "message": msg, "items": sorted(items)}
    )
    literals = {str(l) for l in t.object_literals}
    facts = {str(f.literal) for f in t.facts}
    heads = {str(r.consequent) for r in t.rules}
    names = {r.name for r in t.rules}

    groups = {}
    for l in literals | names:
        core = l[1:] if l.startswith("-") else l
        groups.setdefault(_norm(core), set()).add(core)
    for key, members in sorted(groups.items()):
        if len(members) > 1:
            add(
                "NEAR_DUPLICATE_LITERALS",
                "error",
                "These literals differ only in case, spaces or hyphens and are treated as unrelated: "
                + ", ".join(sorted(members)),
                members,
            )

    underivable = {str(a) for r in t.rules for a in r.antecedents} - facts - heads
    if underivable:
        add(
            "UNDERIVABLE_ANTECEDENT",
            "error",
            "Nothing derives these antecedents, so the rules using them never fire: "
            + ", ".join(sorted(underivable)),
            underivable,
        )

    derivable = set(facts)
    changed = True
    while changed:
        changed = False
        for r in t.rules:
            if str(r.consequent) not in derivable and all(
                str(a) in derivable for a in r.antecedents
            ):
                derivable.add(str(r.consequent))
                changed = True
    dead = {r.name for r in t.rules if not all(str(a) in derivable for a in r.antecedents)}
    if dead:
        add("DEAD_RULE", "warning", "These rules can never fire: " + ", ".join(sorted(dead)), dead)

    declared = {str(c.source) for c in t.contraries} | {str(c.target) for c in t.contraries}
    isolated = set()
    for h in heads:
        if h.startswith("-"):
            positive = h[1:]
            if positive not in literals and positive not in names and h not in declared:
                isolated.add(h)
    if isolated:
        add(
            "ISOLATED_CONCLUSION",
            "warning",
            "These conclusions conflict with nothing (no such literal or rule name): "
            + ", ".join(sorted(isolated)),
            isolated,
        )

    spaced = {l for l in literals if " " in l}
    if spaced:
        add(
            "SPACE_IN_LITERAL", "info", "Literals with spaces: " + ", ".join(sorted(spaced)), spaced
        )

    used = {str(a) for r in t.rules for a in r.antecedents}
    unused = {
        f
        for f in facts
        if f not in used
        and not any(
            (f, x) in t.conflicts or (x, f) in t.conflicts for x in literals | names if x != f
        )
    }
    if unused:
        add(
            "UNUSED_FACT",
            "info",
            "Facts that no rule uses and that conflict with nothing: " + ", ".join(sorted(unused)),
            unused,
        )

    report = diagnose(t)
    if not report.well_defined:
        add("NOT_WELL_DEFINED", "warning", " ".join(report.warnings()), [])
    return findings
