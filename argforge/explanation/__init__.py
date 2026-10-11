from explanation_and_analysis.explanation import *
from explanation_and_analysis.common import plain
from explanation_and_analysis.experiments import public_record
from functools import wraps

from ..language import DIVERGENCE, KIND, SEMANTICS, STATUS, check, localize, phrase


def public_explanation(f):
    @wraps(f)
    def wrapped(*args, language="ENG", **kwargs):
        check(language)
        return public_record(localize(f(*args, language=language, **kwargs), language))

    return wrapped


@public_explanation
def claim_explanation(result, claim, language="ENG"):
    record = explain_claim(result, claim)
    if result.status != "OK":
        return record
    c = record["acceptance"]
    n = len(result.evaluation.extensions)
    tr = language == "TUR"
    sem = SEMANTICS.get(result.config.semantics, (result.config.semantics,) * 2)[1 if tr else 0]
    if c["extension_family_empty"]:
        summary = (f"Hiç {sem} kapsam yok. İddia hiçbir kapsamda kabul edilmiyor; boş bir kapsam ailesi için her kapsamda kabul ve geleneksel durum atanmaz."
                   if tr else
                   f"No {sem} extension exists. Credulous acceptance is false; skeptical claim acceptance and legacy projection are not assigned for the empty family.")
    elif c["skeptical_acceptance"]:
        summary = (f"“{claim}” iddiası {n} kapsamın her birinde temsil ediliyor, yani her kapsamda kabul ediliyor. Onu destekleyen argümanın her kapsamda aynı olması gerekmez."
                   if tr else
                   f"{claim} is represented in every one of the {n} extensions. This is skeptical claim acceptance; the supporting argument need not be the same in every extension.")
    elif c["credulous_acceptance"]:
        summary = (f"“{claim}” iddiası {n} kapsamın hepsinde değil ama bazılarında temsil ediliyor: en az bir kapsamda kabul ediliyor, ama her kapsamda kabul edilmiyor."
                   if tr else
                   f"{claim} is represented in some, but not all, of the {n} extensions. It is credulously accepted and is not skeptically accepted.")
    else:
        summary = (f"“{claim}” iddiasına varan hiçbir argüman {n} kapsamın hiçbirinde yer almıyor; iddia hiçbir kapsamda kabul edilmiyor."
                   if tr else
                   f"No argument concluding {claim} belongs to any of the {n} extensions. The claim is not credulously accepted.")
    legacy = c["legacy_status"]
    if tr:
        summary += " Geleneksel durum: %s." % (STATUS[legacy][1] if legacy in STATUS else "atanmadı")
    else:
        summary += f" Legacy projection: {legacy if legacy is not None else 'not assigned'}."
    supports = set(c["supporting_arguments"])
    return {
        "type": "ClaimExplanation",
        "claim": claim,
        "status": "OK",
        "summary": summary,
        "semantic_condition": {
            "semantics": result.config.semantics,
            "extension_count": n,
            "credulous": c["credulous_acceptance"],
            "skeptical_claim": c["skeptical_acceptance"],
            "legacy": c["legacy_status"],
            "extension_family_empty": c["extension_family_empty"],
        },
        "supporting_arguments": c["supporting_arguments"],
        "accepted_support_by_extension": c["accepted_arguments_per_extension"],
        "accepted_opposition_by_extension": c["accepted_opposing_arguments_per_extension"],
        "opposing_arguments": c["counterclaim_arguments"],
        "declared_opponents": sorted(
            str(a) for a, b in result.evaluation.theory.conflicts if str(b) == claim
        ),
        "single_skeptical_bearers": c["single_skeptical_bearers"],
        "local_defense_witnesses": [d for d in result.defense if d["defended"] in supports],
        "relevant_attacks": [
            a for a in result.attacks if a["target"] in supports or a["attacker"] in supports
        ],
        "provenance": {
            "theory_hash": result.metadata["theory_hash"],
            "configuration": plain(result.config),
            "claim_projection": c,
            "extensions": [list(x) for x in result.evaluation.extensions],
        },
        "scope": ("Kabul, kapsam ailesinin tamamıyla belirlenir. Yerel saldırı ve savunma tanıkları etkileşimleri açıklar; tek belirleyici bir kenar, zorunluluk ya da küresel nedensel en küçüklük ileri sürülmez."
                  if tr else
                  "Acceptance is established by the complete extension family. Local attack and defense witnesses explain interactions; no uniquely decisive edge, necessity, or global causal minimality is asserted."),
    }


@public_explanation
def attack_explanation(a, language="ENG"):
    tr = language == "TUR"
    basis = "preference independent" if not a["preference_relevant"] else a["reason"]
    if tr:
        summary = (f"{a['attacker']}, {a['target']} argümanına {a['witness']} tanığı üzerinden {KIND[a['kind']][1]} yapıyor. "
                   f"{'Bu saldırı bir yenilgidir' if a['succeeds_as_defeat'] else 'Bu saldırı yenilgi değildir'}: {phrase(basis)}.")
    else:
        summary = f"{a['attacker']} attacks {a['target']} by {a['kind']} at witness {a['witness']}. {'It succeeds as a defeat' if a['succeeds_as_defeat'] else 'It does not succeed as a defeat'}: {basis}."
    return {
        "type": "AttackExplanation",
        "id": a["id"],
        "summary": summary,
        "target_description": {
            "rebut": ("defeasible subargument conclusion", "feshedilebilir alt argümanın sonucu"),
            "undermine": ("ordinary premise", "sıradan öncül"),
            "undercut": ("defeasible rule-name literal", "feshedilebilir kuralın adı"),
        }[a["kind"]][1 if tr else 0],
        "conflicting_literals": [a["attacker_conclusion"], a["attacked_element"]],
        "formal": a,
    }


@public_explanation
def argument_explanation(result, argument, language="ENG"):
    tr = language == "TUR"
    a = result.arguments[argument]
    members = [i for i, e in enumerate(result.evaluation.extensions) if argument in e]
    step = (
        f"the {a.get('top_kind','inference')} rule {a['top_rule']}"
        if a.get("top_rule")
        else "a declared axiom" if a["axioms"] else "a declared ordinary premise"
    )
    if tr:
        kind = {"strict": "katı", "defeasible": "feshedilebilir"}.get(a.get("top_kind"), a.get("top_kind"))
        summary = (
            f"{argument}, {kind} {a['top_rule']} kuralını uygulayarak “{a['conclusion']}” sonucuna varıyor."
            if a.get("top_rule")
            else (
                f"{argument}, bildirilen “{a['conclusion']}” aksiyomuna dayanan bir aksiyom argümanıdır."
                if a["axioms"]
                else f"{argument}, bildirilen “{a['conclusion']}” öncülüne dayanan bir öncül argümanıdır."
            )
        )
        summary += f" {len(result.evaluation.extensions)} kapsamın {len(members)} tanesinde yer alıyor."
    else:
        summary = (
            f"{argument} concludes {a['conclusion']} by applying {a['top_kind']} rule {a['top_rule']}."
            if a.get("top_rule")
            else (
                f"{argument} is an axiom argument based on the declared axiom {a['conclusion']}."
                if a["axioms"]
                else f"{argument} is a premise argument based on the declared premise {a['conclusion']}."
            )
        )
        summary += f" It belongs to {len(members)} of {len(result.evaluation.extensions)} extensions."
    return {
        "type": "ArgumentExplanation",
        "argument": argument,
        "summary": summary,
        "record": a,
        "extension_indices": members,
        "defense_witnesses": [d for d in result.defense if d["defended"] == argument],
        "attacks": [x for x in result.attacks if argument in (x["attacker"], x["target"])],
        "scope": (
            ("Gösterilen döngüsel temsilci tek bir sonlu ağaçtır, sınıfının tamamı değildir." if tr
             else "A displayed recursive representative is one finite tree, not its entire class population.")
            if str(result.evaluation.policy).startswith("QUOTIENT")
            else ("Somut yapılandırılmış argüman." if tr else "Concrete structured argument.")
        ),
    }


@public_explanation
def difference_explanation(left, right, language="ENG"):
    from explanation_and_analysis.comparison import compare_results

    tr = language == "TUR"
    d = compare_results(left, right)
    if d["status"] != "OK":
        return {
            "type": "ConfigurationDifferenceExplanation",
            **d,
            "summary": ("Karşılaştırma tamamlanamadı; sağlamlık ya da nedensellik hakkında bir sonuç çıkarılmaz." if tr
                        else "Comparison is incomplete. No robustness or causal conclusion is assigned."),
        }
    first = d["earliest_divergence"]
    if first is None:
        summary = ("Karşılaştırılan yapılarda, kapsam ailesinde ve bildirilen iddia sonuçlarında fark yok." if tr
                   else "No difference in the compared structures, extension family or declared claim results.")
    elif tr:
        summary = (f"Kayıtlı ilk ayrışma: {DIVERGENCE.get(first, (first, first))[1]}. {len(d['claims'])} iddianın sonucu değişiyor; "
                   f"{len(d['defeats']['added'])} yenilgi ekleniyor ve {len(d['defeats']['removed'])} yenilgi kaldırılıyor.")
    else:
        summary = f"The first recorded divergence is {first.replace('_',' ')}. {len(d['claims'])} claim results change; {len(d['defeats']['added'])} defeat edges are added and {len(d['defeats']['removed'])} are removed."
    return {
        "type": "ConfigurationDifferenceExplanation",
        "status": "OK",
        "summary": summary,
        "difference": d,
        "scope": phrase(d["compact_difference_witness"]["causal_status"]) if tr else d["compact_difference_witness"]["causal_status"],
    }


@public_explanation
def defeat_explanation(result, attacker, target, language="ENG"):
    tr = language == "TUR"
    if (attacker, target) not in result.evaluation.defeats:
        raise ValueError("The selected pair is not a defeat")
    witnesses = [
        a
        for a in result.attacks
        if a["attacker"] == attacker and a["target"] == target and a["succeeds_as_defeat"]
    ]
    return {
        "type": "DefeatExplanation",
        "attacker": attacker,
        "target": target,
        "summary": (f"{attacker}, {target} argümanını yeniyor: kayıtlı {len(witnesses)} saldırı tanığı seçilen tercih ayarlarında başarılı." if tr
                    else f"{attacker} defeats {target}: {len(witnesses)} recorded attack witness(es) succeed under the selected preference configuration."),
        "witnesses": witnesses,
        "provenance": {
            "theory_hash": result.metadata["theory_hash"],
            "configuration": plain(result.config),
            "defeat_edge": [attacker, target],
        },
        "scope": ("Başarılı her tanık saklanır; karşılaştırmanın tam dayanağını görmek için bir tanık seçin." if tr
                  else "Every successful witness is retained. Select a witness to inspect its exact comparison basis."),
    }
