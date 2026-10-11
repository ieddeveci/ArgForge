from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json, csv, time, importlib.metadata
from pathlib import Path
from engine import Limits, __version__
from argforge_platform import evaluate
from engine.serialization import theory_to_dict
from engine.protocol import configuration
from ..common import plain, identity
from ..analysis import enrich


@dataclass(frozen=True, init=False)
class Config:
    semantics: str = "grounded"
    ordering: str = "last_link"
    lifting: str = "elitist"
    policy: str = "QUOTIENT"
    conflict_free: str = "defeat"
    transposition: bool = False

    def __init__(
        self,
        semantics="grounded",
        ordering="last_link",
        lifting=None,
        policy="QUOTIENT",
        *,
        set_ordering=None,
        conflict_free="defeat",
        transposition=False,
    ):
        if lifting is not None and set_ordering is not None and lifting != set_ordering:
            raise ValueError("Conflicting set ordering aliases")
        for k, v in dict(
            semantics=semantics,
            ordering=ordering,
            lifting=(
                set_ordering
                if set_ordering is not None
                else lifting if lifting is not None else "elitist"
            ),
            policy=policy,
            conflict_free=conflict_free,
            transposition=transposition,
        ).items():
            object.__setattr__(self, k, v)
        configuration(self.core())

    @property
    def set_ordering(self):
        return self.lifting

    def core(self):
        return dict(
            semantics=self.semantics,
            ordering=self.ordering + "_" + self.lifting,
            cycle_policy=self.policy,
            conflict_free=self.conflict_free,
            transposition=self.transposition,
        )

    @property
    def id(self):
        d = asdict(self)
        for key, default in (("conflict_free", "defeat"), ("transposition", False)):
            if d[key] == default:
                d.pop(key)
        return identity(d)[:20]


def config_from_dict(d):
    return Config(**d)


def public_config(c):
    d = asdict(c)
    d["set_ordering"] = d.pop("lifting")
    return d


def public_record(x):
    if isinstance(x, dict):
        return {
            (
                ("set_ordering" if k == "lifting" else k)
                if ("ordering" in x or "semantics" in x)
                else k
            ): public_record(v)
            for k, v in x.items()
        }
    if isinstance(x, (list, tuple)):
        return [public_record(v) for v in x]
    return x


@dataclass(frozen=True)
class ResearchResult:
    evaluation: object
    config: Config
    metadata: dict
    data: dict

    @property
    def status(self):
        return self.evaluation.status if self.evaluation.status != "OK" else self.data["status"]

    @property
    def arguments(self):
        return self.data["arguments"]

    @property
    def claims(self):
        return self.data["claims"]

    @property
    def graphs(self):
        return self.data["graphs"]

    @property
    def attacks(self):
        return self.data["attacks"]

    @property
    def defense(self):
        return self.data["defense"]

    @property
    def quotient(self):
        return self.data["quotient"]

    def to_dict(self):
        return public_record(
            {
                "schema_version": "research-2",
                "metadata": plain(self.metadata),
                "configuration": asdict(self.config),
                "status": self.status,
                "evaluation": self.evaluation.to_dict(),
                "analysis": plain(self.data),
            }
        )

    def compare_claims(self, left, right):
        from ..comparison import compare_claims

        return compare_claims(self, left, right)

    def explain_claim(self, claim):
        from ..explanation import explain_claim

        return explain_claim(self, claim)


def from_evaluation(e, config=None, provenance=None, limits=None, **analysis_limits):
    if config is None:
        c = e.configuration
        mode, lift = c.get("ordering", "last_link_elitist").rsplit("_", 1)
        config = Config(
            c.get("semantics", "grounded"),
            mode,
            lift,
            c.get("cycle_policy") or "QUOTIENT",
            conflict_free=c.get("conflict_free", "defeat"),
            transposition=c.get("transposition", False),
        )
    from engine.protocol import CONFIG_DEFAULTS

    if e.status == "OK" and any(
        e.configuration.get(k, CONFIG_DEFAULTS[k]) != v for k, v in config.core().items()
    ):
        raise ValueError("Config must match completed evaluation")
    canonical = theory_to_dict(e.theory) if e.theory else None
    metadata = {
        "engine_version": __version__,
        "solver_version": importlib.metadata.version("clingo"),
        "theory_hash": identity(canonical) if canonical is not None else None,
        "canonical_theory": canonical,
        "configuration": asdict(config),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resource_policy": (
            (
                {
                    "time_limit_per_configuration": limits.wall_seconds,
                    "emergency_memory_bytes": limits.memory_bytes,
                    "emergency_output_bytes": limits.output_bytes,
                }
                if limits.time_only
                else asdict(limits)
            )
            if limits
            else None
        ),
        "resource_status": e.status,
        "resource_outcome": dict(e.resource),
        "provenance": provenance or {},
        "source": "completed immutable engine result",
        "timings": dict(e.timings),
    }
    data = (
        enrich(e, **analysis_limits)
        if e.status == "OK"
        else dict(
            status=e.status,
            arguments={},
            claims={},
            graphs={},
            attacks=[],
            defense=[],
            quotient={},
        )
    )
    return ResearchResult(e, config, metadata, data)


def research_evaluate(theory, config=Config(), limits=None, provenance=None, **analysis_limits):
    if limits is not None and not limits.time_only:
        raise ValueError(
            "Count-limited research execution is historical. Use the time-only policy; import old studies without reevaluation."
        )
    from argforge.evaluation_runner.execution import evaluate_research

    return evaluate_research(theory, config, limits.wall_seconds if limits else 60, provenance)


def evaluate_many(theories, configs, limits=None):
    configs = tuple(configs)
    for item in theories:
        if isinstance(item, dict):
            theory = item["theory"]
            provenance = {k: v for k, v in item.items() if k != "theory"}
        else:
            theory = item
            provenance = {}
        for config in configs:
            yield research_evaluate(theory, config, limits, provenance)


def export_json(value, path):
    Path(path).write_text(
        json.dumps(public_record(plain(value)), sort_keys=True, indent=2),
        encoding="utf-8",
    )


def export_csv(records, path):
    records = [public_record(plain(x)) for x in records]
    fields = sorted({k for x in records for k in x})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow(
                {
                    k: (json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v)
                    for k, v in r.items()
                }
            )


def record_workload(result, path, kind="research"):
    if kind not in ("research", "synthetic"):
        raise ValueError("explicit workload kind required")
    t = result.evaluation.theory
    row = {
        "kind": kind,
        "theory_hash": result.metadata["theory_hash"],
        "configuration": asdict(result.config),
        "engine_version": result.metadata["engine_version"],
        "solver_version": result.metadata["solver_version"],
        "timestamp": result.metadata["timestamp"],
        "status": result.status,
        "resource_status": result.evaluation.status,
        "timings": result.metadata["timings"],
        "arguments_or_classes": (
            len(result.evaluation.arguments) if result.evaluation.status == "OK" else None
        ),
        "attacks": (len(result.evaluation.attacks) if result.evaluation.status == "OK" else None),
        "defeats": (len(result.evaluation.defeats) if result.evaluation.status == "OK" else None),
    }
    if t:
        row.update(
            formal_item_count=len(t.facts)
            + len(t.rules)
            + len(t.rule_preferences)
            + len(t.premise_preferences)
            + len(t.contraries),
            facts=len(t.facts),
            axioms=sum(f.kind == "axiom" for f in t.facts),
            ordinary_premises=sum(f.kind == "premise" for f in t.facts),
            rules=len(t.rules),
            preferences=len(t.rule_preferences) + len(t.premise_preferences),
            conflicts=len(t.contraries),
            dependency_sccs=(
                len(result.graphs["rule_dependency"]["sccs"])
                if "rule_dependency" in result.graphs
                else None
            ),
        )
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(public_record(row), sort_keys=True) + "\n")
    return row
