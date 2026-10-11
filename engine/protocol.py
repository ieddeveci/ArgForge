import json, math
from .resources import ResourceLimit

SEMANTICS = frozenset(
    (
        "conflict_free",
        "admissible",
        "complete",
        "grounded",
        "preferred",
        "stable",
        "naive",
        "semistable",
        "ideal",
        "eager",
    )
)
ORDERINGS = frozenset(
    (
        "last_link_elitist",
        "last_link_democratic",
        "weakest_link_elitist",
        "weakest_link_democratic",
    )
)
POLICIES = frozenset(
    (
        "REJECT",
        "P_LITERAL",
        "P_RULE",
        "P_STATE",
        "QUOTIENT",
        "QUOTIENT_ATTACKABLE",
        "UNRESTRICTED_UNROLL",
    )
)


CONFLICT_FREENESS = frozenset(("defeat", "attack"))
CONFIG_DEFAULTS = {
    "semantics": "grounded",
    "ordering": "last_link_elitist",
    "cycle_policy": None,
    "depth": None,
    "conflict_free": "defeat",
    "transposition": False,
}
CONFIG_KEYS = tuple(CONFIG_DEFAULTS)
EXTENDED_KEYS = ("conflict_free", "transposition")


def stored_configuration(c):
    out = {k: c[k] for k in ("semantics", "ordering", "cycle_policy", "depth")}
    out.update({k: c[k] for k in EXTENDED_KEYS if c[k] != CONFIG_DEFAULTS[k]})
    return out


class ConfigurationError(ValueError):
    pass


def object_keys(value, required, optional=()):
    if (
        type(value) is not dict
        or not set(required) <= value.keys()
        or set(value) - set(required) - set(optional)
    ):
        raise ValueError("invalid object keys")
    return value


def text(value):
    if type(value) is not str:
        raise ValueError("expected string")
    value.encode("utf-8", errors="strict")
    return value


def loads(raw):
    if type(raw) is bytes:
        raw = raw.decode("utf-8", errors="strict")
    if type(raw) is not str:
        raise ValueError("JSON must be UTF-8 bytes or text")

    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError("duplicate JSON key")
            out[k] = v
        return out

    def constant(x):
        raise ValueError("nonfinite JSON number")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    stack = [(value, 0)]
    while stack:
        v, d = stack.pop()
        if d > 64:
            raise ValueError("JSON nesting exceeds 64")
        if type(v) is str:
            text(v)
        elif type(v) is float and not math.isfinite(v):
            raise ValueError("nonfinite JSON number")
        elif type(v) is dict:
            stack.extend((x, d + 1) for x in v.values())
        elif type(v) is list:
            stack.extend((x, d + 1) for x in v)
    return value


def configuration(value):
    try:
        object_keys(value, (), CONFIG_KEYS)
        c = {**CONFIG_DEFAULTS, **value}
        if type(c["semantics"]) is not str or c["semantics"] not in SEMANTICS:
            raise ValueError("unknown semantics")
        if type(c["ordering"]) is not str or c["ordering"] not in ORDERINGS:
            raise ValueError("unknown ordering")
        p = c["cycle_policy"]
        d = c["depth"]
        if p is not None and (type(p) is not str or p not in POLICIES):
            raise ValueError("unknown cycle policy")
        if d is not None and (type(d) is not int or d < 0):
            raise ValueError("depth must be a nonnegative integer")
        if p == "UNRESTRICTED_UNROLL" and d is None:
            raise ValueError("unrolling requires depth")
        if c["conflict_free"] not in CONFLICT_FREENESS:
            raise ValueError("conflict_free must be 'defeat' or 'attack'")
        if type(c["transposition"]) is not bool:
            raise ValueError("transposition must be a boolean")
        return c
    except (ValueError, TypeError) as e:
        raise ConfigurationError(str(e)) from e


def validate_theory_data(d):
    object_keys(d, ("facts", "rules", "rule_preferences", "premise_preferences", "contraries"))
    specs = {
        "facts": ("literal", "kind"),
        "rules": ("name", "antecedents", "consequent", "kind"),
        "rule_preferences": ("stronger", "weaker"),
        "premise_preferences": ("stronger", "weaker"),
        "contraries": ("source", "target", "symmetric"),
    }
    for k, keys in specs.items():
        if type(d[k]) is not list:
            raise ValueError("theory collections must be arrays")
        for v in d[k]:
            object_keys(v, keys)
            for field in keys:
                if field == "symmetric":
                    if type(v[field]) is not bool:
                        raise ValueError("symmetric must be boolean")
                elif field == "antecedents":
                    if type(v[field]) is not list:
                        raise ValueError("antecedents must be array")
                    for x in v[field]:
                        text(x)
                else:
                    text(v[field])
    return d
