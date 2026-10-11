import re

LANGUAGES = ("ENG", "TUR")

SEMANTICS = {
    "grounded": ("grounded", "temelli"),
    "complete": ("complete", "tam"),
    "preferred": ("preferred", "tercih edilen"),
    "stable": ("stable", "kararlı"),
    "semistable": ("semi-stable", "yarı kararlı"),
    "ideal": ("ideal", "ideal"),
    "eager": ("eager", "istekli"),
    "naive": ("naive", "naif"),
    "admissible": ("admissible", "kabul edilebilir"),
    "conflict_free": ("conflict-free", "çatışmasız"),
}

STATUS = {
    "JUSTIFIED": ("justified", "gerekçelendirilmiş"),
    "DEFENSIBLE": ("defensible", "savunulabilir"),
    "OVERRULED": ("overruled", "reddedilmiş"),
    "UNDECIDED": ("undecided", "kararsız"),
    "UNSUPPORTED": ("unsupported", "desteklenmemiş"),
    "NO_EXTENSIONS": ("without a status", "durumsuz"),
}

PHRASES = {
    "in the extension; it has no defeaters": "kapsamda; onu yenen hiçbir argüman yok",
    "in the extension; every defeater is defeated by a member": "kapsamda; onu yenen her argüman kapsamın bir üyesi tarafından yeniliyor",
    "in the extension without being defended; this semantics does not require defence": "kapsamda, ama savunulmuyor; bu semantik savunma gerektirmez",
    "defeated by a member of the extension": "kapsamın bir üyesi tarafından yeniliyor",
    "neither accepted nor defeated by the extension": "kapsam onu ne kabul ediyor ne de yeniyor",
    "grounded extension under defeat conflict-freeness (Def. 13)": "yenilgilere göre çatışmasızlık altında temelli kapsam (Tanım 13)",
    "grounded extension under defeat conflict-freeness (Def. 13), not the selected attack-based semantics; they agree when the theory is well defined (Prop. 16)": "yenilgilere göre çatışmasızlık altında temelli kapsam (Tanım 13); seçilen saldırıya dayalı semantik değil. Kuram iyi tanımlıysa ikisi aynı sonucu verir (Önerme 16)",
    "every extension contains an argument for it (not necessarily the same one)": "her kapsam onun için bir argüman içeriyor (her seferinde aynısı olmak zorunda değil)",
    "some, but not all, extensions contain an argument for it": "kapsamların hepsi değil ama bazıları onun için bir argüman içeriyor",
    "in every extension, every argument for it is defeated": "her kapsamda, onun için olan her argüman yeniliyor",
    "no extension contains an argument for it, and in at least one extension some argument for it is not defeated": "hiçbir kapsam onun için bir argüman içermiyor ve en az bir kapsamda onun için olan bir argüman yenilmiyor",
    "no argument concludes it": "hiçbir argüman ona varmıyor",
    "the selected semantics has no extension": "seçilen semantiğin kapsamı yok",
    "last defeasible rules": "son feshedilebilir kurallar",
    "both premise and rule sets must be strictly worse": "hem öncül hem de kural kümelerinin kesin olarak daha zayıf olması gerekir",
    "undercut is preference-independent": "kurala saldırı tercihlerden bağımsızdır",
    "contrary attack is preference-independent": "karşıtlık üzerinden saldırı tercihlerden bağımsızdır",
    "ordinary premises: both arguments strict": "sıradan öncüller: iki argüman da katı",
    "ordinary premises: both strict": "sıradan öncüller: iki argüman da katı",
    "defeasible rules: both firm": "feshedilebilir kurallar: iki argüman da sağlam",
    "preference-independent attack": "tercihlerden bağımsız saldırı",
    "preference independent": "tercihlerden bağımsız",
    "attacker strictly weaker than attacked witness": "saldıran, saldırılan tanıktan kesin olarak daha zayıf",
    "attacker not strictly weaker than attacked witness": "saldıran, saldırılan tanıktan kesin olarak daha zayıf değil",
    "Exact membership and local defeat/defense witnesses; no unique global causal proof claimed.": "Kesin kapsam üyeliği ile yerel yenilgi ve savunma tanıkları; tek ve küresel bir nedensel kanıt ileri sürülmez.",
    "Observed first differences; no single-edge counterfactual necessity or globally minimal theory edit is asserted.": "Gözlenen ilk farklar; tek bir kenarın karşı-olgusal zorunluluğu ya da küresel olarak en küçük bir kuram değişikliği ileri sürülmez.",
}

DIVERGENCE = {
    "arguments": ("arguments", "argümanlar"),
    "attacks": ("attacks", "saldırılar"),
    "preference_comparison": ("preference comparison", "tercih karşılaştırması"),
    "defeat": ("defeat", "yenilgi"),
    "extension_family": ("extension family", "kapsam ailesi"),
    "claim_projection": ("claim projection", "iddia izdüşümü"),
}

KIND = {
    "rebut": ("rebut", "sonuca saldırı"),
    "undermine": ("undermine", "öncüle saldırı"),
    "undercut": ("undercut", "kurala saldırı"),
}

TEMPLATES = [
    (re.compile(r"^attacker strictly weaker \((.*)\)$"), "saldıran kesin olarak daha zayıf ({0})"),
    (re.compile(r"^attacker not strictly weaker \((.*)\)$"), "saldıran kesin olarak daha zayıf değil ({0})"),
]

TERMS = {
    "premises": "öncüller",
    "ordinary premises": "sıradan öncüller",
    "defeasible rules": "feshedilebilir kurallar",
    "last defeasible rules": "son feshedilebilir kurallar",
}

STATUS_PREDICATE = {
    "JUSTIFIED": ("is justified", "gerekçelendirilmiştir"),
    "DEFENSIBLE": ("is defensible", "savunulabilirdir"),
    "OVERRULED": ("is overruled", "reddedilmiştir"),
    "UNDECIDED": ("is undecided", "kararsızdır"),
    "UNSUPPORTED": ("is unsupported", "desteklenmemiştir"),
    "NO_EXTENSIONS": ("has no status", "durumsuzdur"),
}

STATUS_HEAD_NONE = {
    "ENG": "The claim “%s” has no status.",
    "TUR": "“%s” iddiasının bir durumu yok.",
}

TRANSLATED_KEYS = ("reason", "grounded_scope", "basis", "rationale", "explanation_scope", "causal_status")


def check(language):
    if language not in LANGUAGES:
        raise ValueError("language must be 'ENG' or 'TUR'")
    return language


def phrase(text):
    if text in PHRASES:
        return PHRASES[text]
    for pattern, out in TEMPLATES:
        m = pattern.match(text)
        if m:
            return out.format(*(phrase(g) for g in m.groups()))
    return TERMS.get(text, text)


def localize(value, language):
    if language == "ENG":
        return value
    if isinstance(value, dict):
        return {k: (phrase(v) if k in TRANSLATED_KEYS and isinstance(v, str) else localize(v, language))
                for k, v in value.items()}
    if isinstance(value, list):
        return [localize(v, language) for v in value]
    return value


def semantics_name(semantics, language):
    pair = SEMANTICS.get(semantics, (semantics, semantics))
    return pair[1 if language == "TUR" else 0]


def status_name(status, language):
    pair = STATUS.get(status, (status.lower(), status.lower()))
    return pair[1 if language == "TUR" else 0]


def names(result, ids):
    return [result.argument(i).alias for i in ids]


def joined(items, language, final=None):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    last = (" ve " if language == "TUR" else " and ") if final is None else final
    return ", ".join(items[:-1]) + last + items[-1]


def capital(text):
    return text[:1].upper() + text[1:]


def argument_text(result, ref, extension=0, language="ENG"):
    check(language)
    tr = language == "TUR"
    i = result.argument(ref).id
    alias = result.argument(i).alias
    semantics = result.config.semantics
    extensions = result.extensions
    if extensions:
        if not 0 <= extension < len(extensions):
            raise ValueError("extension index out of range")
        labels = result.labellings[extension]
        members = extensions[extension]
        if semantics == "grounded":
            context = "Temelli kapsamda:" if tr else "In the grounded extension:"
        elif len(extensions) == 1:
            context = ("Tek %s kapsamda:" if tr else "In the only %s extension:") % semantics_name(semantics, language)
        else:
            context = ("%d kapsamın %d. kapsamında:" % (len(extensions), extension + 1) if tr
                       else "In extension %d of %d:" % (extension + 1, len(extensions)))
    else:
        labels = {k: v["label"] for k, v in result.grounded.items()}
        members = frozenset(k for k, v in labels.items() if v == "IN")
        context = capital("bu kuram için %s kapsam yok; aşağıdaki etiketler temelli olanlardır." % semantics_name(semantics, language)
                          if tr else
                          "there is no %s extension for this theory; the labels below are the grounded ones." % semantics_name(semantics, language))
    defeaters = sorted(result._defeaters[i], key=lambda b: result.argument(b).alias)
    label = labels[i]
    if not defeaters and label == "IN":
        reason = ("%s argümanını hiçbir şey yenmiyor, bu yüzden kabul edildi." % alias if tr
                  else "Nothing defeats %s, so it is accepted." % alias)
    elif label == "IN":
        answers = []
        undefended = []
        for b in defeaters:
            by = sorted((c for c in result._defeaters[b] if c in members), key=lambda c: result.argument(c).alias)
            if by:
                answers.append(("%s, %s tarafından yeniliyor" % (result.argument(b).alias, joined(names(result, by), language))) if tr
                               else "%s is defeated by %s" % (result.argument(b).alias, joined(names(result, by), language)))
            else:
                undefended.append(result.argument(b).alias)
        if undefended:
            reason = ("%s kabul edildi, ama onu yenen %s yanıtsız kalıyor; bu semantik savunma gerektirmez." % (alias, joined(undefended, language))
                      if tr else
                      "%s is accepted, although %s, which %s it, %s unanswered; this semantics does not require defence."
                      % (alias, joined(undefended, language), "defeat" if len(undefended) > 1 else "defeats",
                         "remain" if len(undefended) > 1 else "remains"))
        else:
            reason = ("%s kabul edildi, çünkü onu yenen her argüman da kabul edilmiş bir argüman tarafından yeniliyor: %s." % (alias, "; ".join(answers))
                      if tr else
                      "%s is accepted because every argument that defeats it is itself defeated by an accepted argument: %s." % (alias, "; ".join(answers)))
    elif label == "OUT" and [b for b in defeaters if labels[b] == "IN"]:
        by = [b for b in defeaters if labels[b] == "IN"]
        reason = ("%s, kabul edilmiş %s tarafından yeniliyor." % (alias, joined(names(result, by), language)) if tr
                  else "%s is defeated by the accepted %s %s." % (alias, "arguments" if len(by) > 1 else "argument", joined(names(result, by), language)))
    elif not [b for b in defeaters if labels[b] == "UNDEC"]:
        reason = ("%s bu kapsamda yer almıyor, ama kapsamın hiçbir üyesi onu yenmiyor." % alias if tr
                  else "%s is not in this extension, although no member of the extension defeats it." % alias)
    else:
        by = [b for b in defeaters if labels[b] == "UNDEC"]
        reason = ("%s kararsız; onu kabul edilmiş hiçbir argüman yenmiyor, ama onu yenen %s da kararsız: %s."
                  % (alias, "argümanlar" if len(by) > 1 else "argüman", joined(names(result, by), language))
                  if tr else
                  "%s is undecided; no accepted argument defeats it, but %s, which %s it, %s undecided too."
                  % (alias, joined(names(result, by), language), "defeat" if len(by) > 1 else "defeats", "are" if len(by) > 1 else "is"))
    failed, seen = [], set()
    for a in result.attacks:
        if a.target != i or a.succeeds or a.attacker in result._defeaters[i]:
            continue
        key = (a.attacker, a.on)
        if key in seen:
            continue
        seen.add(key)
        on = "" if a.on == i else (" (%s üzerinden)" % result.argument(a.on).alias if tr else " (on %s)" % result.argument(a.on).alias)
        failed.append(result.argument(a.attacker).alias + on)
    parts = [context, reason]
    if failed:
        shown = failed[:8]
        more = len(failed) - len(shown)
        tail = ("; ve %d tane daha" % more if tr else "; and %d more" % more) if more else ""
        parts.append(("Saldıran seçilen tercihlere göre daha zayıf olduğu için başarısız olan saldırılar: %s%s." if tr
                      else "Attacks that fail because the attacker is weaker under the chosen preferences: %s%s.")
                     % ("; ".join(shown), tail))
    return " ".join(parts)


def claim_text(result, literal, extension=0, language="ENG"):
    check(language)
    tr = language == "TUR"
    info = result.claim(literal)
    status = info.status
    semantics = result.config.semantics
    if status == "NO_EXTENSIONS":
        head = STATUS_HEAD_NONE[language] % literal
    else:
        head = ("“%s” iddiası %s." % (literal, STATUS_PREDICATE[status][1]) if tr
                else "The claim “%s” %s." % (literal, STATUS_PREDICATE[status][0]))
    if status == "NO_EXTENSIONS":
        body = capital("%s semantiğin bu kuram için kapsamı yok, bu yüzden hiçbir iddianın durumu yok." % semantics_name(semantics, language)
                       if tr else
                       "the %s semantics has no extension for this theory, so no claim has a status." % semantics_name(semantics, language))
        return head + " " + body
    if status == "UNSUPPORTED":
        return head + " " + ("Hiçbir argüman ona varmıyor." if tr else "No argument concludes it.")
    extensions = result.extensions
    bearers = list(info.bearers)
    count = len(extensions)
    single = semantics == "grounded" or count == 1
    where = ("Temelli kapsamda" if semantics == "grounded" else "Tek kapsamda") if tr else (
        "In the grounded extension" if semantics == "grounded" else "In the only extension")
    k = extension if 0 <= extension < count else 0
    labels = result.labellings[k]
    accepted = [b for b in bearers if labels[b] == "IN"]
    defeated = [b for b in bearers if labels[b] == "OUT"]
    undecided = [b for b in bearers if labels[b] == "UNDEC"]

    def by(b):
        who = [c for c in result._defeaters[b] if labels[c] == "IN"]
        return (("%s, %s tarafından" % (result.argument(b).alias, joined(names(result, who), language))) if tr
                else "%s by %s" % (result.argument(b).alias, joined(names(result, who), language)))

    here = "" if single else ((" %d. kapsamda: " % (k + 1)) if tr else (" In extension %d: " % (k + 1)))
    if status == "JUSTIFIED":
        if single:
            body = ("%s onun için bir argüman var: %s." % (where, joined(names(result, accepted), language)) if tr
                    else "%s, there is an argument for it: %s." % (where, joined(names(result, accepted), language)))
        else:
            body = (("%d kapsamın her biri onun için bir argüman içeriyor; her seferinde aynısı olmak zorunda değil." % count) if tr
                    else "Every one of the %d extensions contains an argument for it, not necessarily the same one." % count)
            body += here + joined(names(result, accepted), language) + "."
    elif status == "DEFENSIBLE":
        inside = [str(n + 1) for n, ext in enumerate(extensions) if any(result.labellings[n][b] == "IN" for b in bearers)]
        body = (("%d kapsamın %d tanesinde kabul edildi (%s); diğerlerinde onun için hiçbir argüman kabul edilmedi." % (count, len(inside), joined(inside, language)))
                if tr else
                "Accepted in %d of %d extensions (%s); in the others no argument for it is accepted." % (len(inside), count, joined(inside, language)))
    elif status == "OVERRULED":
        lead = ("%s onun için olan her argüman yeniliyor: " % where if single else "Her kapsamda, onun için olan her argüman yeniliyor." + here) if tr else (
            "%s, every argument for it is defeated: " % where if single else "In every extension, every argument for it is defeated." + here)
        body = lead + "; ".join(by(b) for b in defeated) + "."
    else:
        lead = (("%s onun için kabul edilmiş bir argüman yok, ama onun için olan argümanların hepsi yenilmiş değil. " % where) if single
                else "Hiçbir kapsam onu kabul etmiyor, ama onun için olan argümanların hepsi her zaman yenilmiş değil." + here) if tr else (
            ("%s, no argument for it is accepted, but not every argument for it is defeated. " % where) if single
            else "No extension accepts it, but not every argument for it is always defeated." + here)
        bits = []
        if undecided:
            bits.append(("kararsız: %s" if tr else "undecided: %s") % joined(names(result, undecided), language))
        if defeated:
            bits.append(("yenilmiş: %s" if tr else "defeated: %s") % "; ".join(by(b) for b in defeated))
        if bits and single:
            bits[0] = capital(bits[0])
        body = lead + "; ".join(bits) + "."
    return head + " " + body
