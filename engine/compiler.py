from clingo import String


def compile_theory(theory, ordering):
    mode, comparison = ordering.rsplit("_", 1)
    lines = [f"ordering({mode}).", f"comparison({comparison})."]
    for r in theory.rules:
        lines.append(f"rule_kind({String(r.name)},{r.kind}).")
        if r.kind == "defeasible":
            lines.append(f"rule_literal({String(r.name)},{String(r.name)}).")
    for a, b in sorted(theory.conflicts):
        lines.append(f"conflict({String(a)},{String(b)}).")
        if (b, a) not in theory.conflicts:
            lines.append(f"contrary_only({String(a)},{String(b)}).")
    for name, order in (
        ("rule_pref", theory.rule_order),
        ("prem_pref", theory.premise_order),
    ):
        lines.extend(f"{name}({String(a)},{String(b)})." for a, b in sorted(order))
    return "\n".join(sorted(lines))


def compile_arguments(arguments):
    ordered = sorted(arguments, key=lambda a: repr(a.structure))
    ids = {a: a.id for a in ordered}
    lines = []
    for a, i in ids.items():
        lines.extend((f"arg({i}).", f"conc({i},{String(a.conclusion)})."))
        if a.premise:
            lines.append(f"observation_based({i}).")
        else:
            lines.extend(
                (
                    f"top_kind({i},{a.top_rule.kind}).",
                    f"top_rule({i},{String(a.top_rule.name)}).",
                )
            )
        for s in a.subarguments:
            if s in ids:
                lines.append(f"subarg({i},{ids[s]}).")
        for predicate, values in (
            ("def_rule", a.defeasible_rules),
            ("last_def_rule", a.last_defeasible_rules),
            ("ord_premise", a.ordinary_premises),
        ):
            lines.extend(f"{predicate}({i},{String(v)})." for v in sorted(values))
    return "\n".join(sorted(lines)), ids
