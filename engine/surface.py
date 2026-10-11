import json, re

ALIASES = {
    "premise": "premise",
    "öncül": "premise",
    "axiom": "axiom",
    "aksiyom": "axiom",
    "strict": "strict",
    "katı": "strict",
    "defeasible": "defeasible",
    "feshedilebilir": "defeasible",
    "prefer_rule": "prefer_rule",
    "kural_tercihi": "prefer_rule",
    "prefer_premise": "prefer_premise",
    "öncül_tercihi": "prefer_premise",
    "contrary": "contrary",
    "karşıt": "contrary",
    "contradictory": "contradictory",
    "çelişik": "contradictory",
}
MESSAGES = {
    "SOURCE_TEXT": ("Theory source must be text.", "Kuram kaynağı metin olmalıdır."),
    "EXPECTED_BLOCK": (
        "Expected a bracketed declaration.",
        "Köşeli parantezli bir bildirim bekleniyor.",
    ),
    "UNCLOSED_BLOCK": (
        "Declaration is missing its closing bracket.",
        "Bildirimin kapanış köşeli parantezi eksik.",
    ),
    "NESTED_BLOCK": (
        "Quote a literal containing brackets.",
        "Köşeli parantez içeren atomik ifadeyi çift tırnak içine alın.",
    ),
    "UNCLOSED_QUOTE": (
        "Quoted literal is not closed.",
        "Çift tırnaklı atomik ifade kapatılmamış.",
    ),
    "HEADER": (
        "Expected a valid declaration keyword and colon.",
        "Geçerli bir bildirim anahtar sözcüğü ve iki nokta bekleniyor.",
    ),
    "UNKNOWN_KEYWORD": (
        "Unknown declaration keyword.",
        "Bilinmeyen bildirim anahtar sözcüğü.",
    ),
    "RULE_NAME": (
        "A rule requires a name containing ASCII letters, digits or underscores.",
        "Kural adı ASCII harfleri, rakamlar veya alt çizgilerden oluşmalıdır.",
    ),
    "UNNAMED": (
        "Only strict and defeasible rules have names; this declaration must be unnamed.",
        "Yalnızca katı ve feshedilebilir kurallar adlandırılır; bu bildirim adsız olmalıdır.",
    ),
    "SEPARATOR": (
        "Expected exactly one structural separator for this declaration.",
        "Bu bildirimde tam olarak bir yapısal ayırıcı bekleniyor.",
    ),
    "EMPTY_LITERAL": (
        "A literal or antecedent slot is empty.",
        "Atomik ifade veya kural öncülü alanı boş.",
    ),
    "QUOTED_LITERAL": (
        "Use a complete JSON-style double-quoted literal with valid escapes.",
        "Geçerli kaçışlarla JSON biçiminde tam bir çift tırnaklı atomik ifade kullanın.",
    ),
    "RESERVED": (
        "Quote literals containing structural punctuation: &, >, ^, [, ], or a double quote.",
        "&, >, ^, [, ] veya çift tırnak içeren atomik ifadeleri çift tırnak içine alın.",
    ),
    "LITERAL": (
        "Literal must be trimmed, nonempty, and use at most one leading minus.",
        "Atomik ifade boş olamaz; başında ve sonunda boşluk bulunamaz ve en fazla bir ön eksi işareti kullanılabilir.",
    ),
}


class ParseError(ValueError):
    def __init__(self, code, source="", offset=0):
        self.code = code
        self.line = source.count("\n", 0, offset) + 1
        self.column = offset - source.rfind("\n", 0, offset)
        super().__init__(self.render("ENG"))

    def render(self, language="ENG"):
        return MESSAGES[self.code][1 if language == "TUR" else 0]

    def to_dict(self):
        return dict(
            code=self.code,
            line=self.line,
            column=self.column,
            messages={"ENG": self.render(), "TUR": self.render("TUR")},
        )


def blocks(source):
    if not isinstance(source, str):
        raise ParseError("SOURCE_TEXT")
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
            continue
        if source[i] == "#" and not source[source.rfind("\n", 0, i) + 1 : i].strip():
            end = source.find("\n", i)
            i = len(source) if end < 0 else end + 1
            continue
        if source[i] != "[":
            raise ParseError("EXPECTED_BLOCK", source, i)
        start = i
        i += 1
        quoted = False
        escape = False
        while i < len(source):
            c = source[i]
            if quoted:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    quoted = False
            elif c == '"':
                quoted = True
            elif c == "[":
                raise ParseError("NESTED_BLOCK", source, i)
            elif c == "]":
                break
            i += 1
        if i == len(source):
            raise ParseError("UNCLOSED_QUOTE" if quoted else "UNCLOSED_BLOCK", source, start)
        content = source[start + 1 : i]
        m = re.match(r"\s*([^\s:]+)(?:\s+([^:]*?))?\s*:", content)
        if not m:
            raise ParseError("HEADER", source, start + 1)
        keyword, label = m.groups()
        kind = ALIASES.get(keyword)
        if kind is None:
            raise ParseError("UNKNOWN_KEYWORD", source, start + 1)
        label = (label or "").strip()
        if kind in ("strict", "defeasible"):
            if not re.fullmatch(r"[A-Za-z0-9_]+", label):
                raise ParseError("RULE_NAME", source, start + 1)
        elif label:
            raise ParseError("UNNAMED", source, start + 1)
        yield dict(
            kind=kind,
            name=label or None,
            body=content[m.end() :],
            offset=start + 1 + m.end(),
            line=source.count("\n", 0, start) + 1,
            text=source[start : i + 1],
        )
        i += 1


def split_unquoted(text, separator, source="", offset=0):
    parts = []
    start = 0
    i = 0
    quoted = False
    escape = False
    while i < len(text):
        c = text[i]
        if quoted:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif text.startswith(separator, i):
            parts.append((text[start:i], offset + start))
            i += len(separator)
            start = i
            continue
        i += 1
    if quoted:
        raise ParseError("UNCLOSED_QUOTE", source, offset)
    parts.append((text[start:], offset + start))
    return parts


def literal(text, source, offset):
    from .model import Literal

    raw = text.strip()
    if not raw:
        raise ParseError("EMPTY_LITERAL", source, offset)
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise ParseError("QUOTED_LITERAL", source, offset) from None
        if not isinstance(value, str):
            raise ParseError("QUOTED_LITERAL", source, offset)
    else:
        if any(c in raw for c in '&>^[]"') or "->" in raw or "=>" in raw:
            raise ParseError("RESERVED", source, offset)
        value = raw
    try:
        return Literal(value)
    except ValueError:
        raise ParseError("LITERAL", source, offset) from None


def parse_theory(source, cls=None):
    from .model import Theory

    return (cls or Theory)(*parse_declarations(source))


def parse_declarations(source):
    from .model import (
        Theory,
        Fact,
        Rule,
        RulePreference,
        PremisePreference,
        ContraryRelation,
    )

    facts = []
    rules = []
    rp = []
    pp = []
    cs = []
    for d in blocks(source):
        kind, name, body, off = d["kind"], d["name"], d["body"], d["offset"]
        if kind in ("premise", "axiom"):
            facts.append(Fact(literal(body, source, off), kind))
            continue
        sep = (
            ("->" if kind == "strict" else "=>")
            if kind in ("strict", "defeasible")
            else ">" if kind.startswith("prefer_") else "^"
        )
        parts = split_unquoted(body, sep, source, off)
        if len(parts) != 2:
            raise ParseError("SEPARATOR", source, off)
        (a, ao), (b, bo) = parts
        if kind in ("strict", "defeasible"):
            ant = (
                []
                if not a.strip()
                else [literal(x, source, o) for x, o in split_unquoted(a, "&", source, ao)]
            )
            rules.append(Rule(name, tuple(ant), literal(b, source, bo), kind))
        elif kind == "prefer_rule":
            names = [a.strip(), b.strip()]
            if not all(re.fullmatch(r"[A-Za-z0-9_]+", x) for x in names):
                raise ParseError("RULE_NAME", source, off)
            rp.append(RulePreference(*names))
        elif kind == "prefer_premise":
            pp.append(PremisePreference(literal(a, source, ao), literal(b, source, bo)))
        else:
            cs.append(
                ContraryRelation(
                    literal(a, source, ao),
                    literal(b, source, bo),
                    kind == "contradictory",
                )
            )
    return tuple(facts), tuple(rules), tuple(rp), tuple(pp), tuple(cs)


def quote_literal(value):
    return (
        json.dumps(str(value), ensure_ascii=False)
        if any(c in value for c in '&>^[]"\\\n\r\t') or "->" in value or "=>" in value
        else str(value)
    )


def serialize_theory(theory):
    q = quote_literal
    lines = []
    for f in sorted(theory.facts, key=lambda x: (x.kind, str(x.literal))):
        lines.append(f"[{f.kind}: {q(f.literal)}]")
    for r in sorted(theory.rules, key=lambda x: x.name):
        lines.append(
            f"[{r.kind} {r.name}: "
            + " & ".join(q(a) for a in r.antecedents)
            + (" -> " if r.kind == "strict" else " => ")
            + q(r.consequent)
            + "]"
        )
    for p in sorted(theory.rule_preferences, key=lambda x: (x.stronger, x.weaker)):
        lines.append(f"[prefer_rule: {p.stronger} > {p.weaker}]")
    for p in sorted(theory.premise_preferences, key=lambda x: (x.stronger, x.weaker)):
        lines.append(f"[prefer_premise: {q(p.stronger)} > {q(p.weaker)}]")
    for c in sorted(theory.contraries, key=lambda x: (x.symmetric, str(x.source), str(x.target))):
        lines.append(
            f'[{"contradictory" if c.symmetric else "contrary"}: {q(c.source)} ^ {q(c.target)}]'
        )
    return "\n".join(lines) + "\n"
