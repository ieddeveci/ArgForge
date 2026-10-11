from dataclasses import dataclass
import errno
from time import perf_counter, monotonic
from .model import Theory
from .construction import (
    NativeExactConstructor,
    CyclicConstructor,
    Budget,
    ConstructionLimit,
)
from .relations import all_attacks, explain_defeat, succeeds, ORDERINGS
from .semantics import extensions, SEMANTICS
from .identity import freeze
from .public_types import Extension, Defeat, ArgumentationFramework
from .resources import Limits, Meter, CURRENT, ResourceLimit, enter_stage, consume
from .protocol import configuration, ConfigurationError, stored_configuration
from .wellformed import close_under_transposition


def _rss_bytes():
    try:
        with open("/proc/self/statm") as handle:
            import os

            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return None


class TrackedBudget(Budget):

    memory_bytes = None

    def check(self, count, candidate=False):
        self.observed_arguments = count
        if self.memory_bytes:
            self._memory_ticks = getattr(self, "_memory_ticks", 0) + 1
            if self._memory_ticks % 256 == 0:
                now = _rss_bytes()
                if now is not None:
                    base = getattr(self, "_memory_base", None)
                    if base is None:
                        self._memory_base = base = now
                    if now - base > self.memory_bytes:
                        raise ResourceLimit(
                            "MEMORY_LIMIT",
                            "construction memory containment exceeded; no complete result available",
                            limit_kind="memory_bytes",
                            limit_value=self.memory_bytes,
                            observed_count=count,
                        )
        return super().check(count, candidate)


@dataclass(frozen=True, slots=True)
class Evaluation:
    status: str
    arguments: tuple = ()
    attacks: tuple = ()
    defeats: frozenset = frozenset()
    extensions: tuple = ()
    ids: object = None
    statuses: object = None
    timings: object = None
    error: str | None = None
    policy: str | None = None
    theory: Theory | None = None
    configuration: object = None
    resource: object = None
    defeat_witnesses: object = None
    __hash__ = None

    def __post_init__(self):
        object.__setattr__(self, "arguments", tuple(self.arguments))
        object.__setattr__(self, "attacks", tuple(self.attacks))
        object.__setattr__(self, "defeats", frozenset(self.defeats))
        object.__setattr__(self, "extensions", tuple(Extension(e) for e in self.extensions))
        for name in ("ids", "statuses", "timings", "configuration", "resource"):
            object.__setattr__(self, name, freeze(getattr(self, name) or {}))
        if self.defeat_witnesses is not None:
            object.__setattr__(self, "defeat_witnesses", freeze(dict(self.defeat_witnesses)))

    @property
    def framework(self):
        if self.defeat_witnesses is not None:
            records = tuple(
                Defeat(x, y, tuple(self.defeat_witnesses.get((x, y), ())))
                for x, y in sorted(self.defeats)
            )
            return ArgumentationFramework(self.arguments, self.attacks, records)
        groups = {edge: [] for edge in self.defeats}
        for a in self.attacks:
            edge = (self.ids[a.attacker], self.ids[a.target])
            if (
                edge in groups
                and explain_defeat(self.theory, a, self.configuration["ordering"])["succeeds"]
            ):
                groups[edge].append(a.id)
        records = tuple(Defeat(x, y, tuple(sorted(groups[(x, y)]))) for x, y in sorted(groups))
        return ArgumentationFramework(self.arguments, self.attacks, records)

    def to_dict(self, include_timings=False):
        from .serialization import evaluation_to_dict

        return evaluation_to_dict(self, include_timings)

    def to_json(self, include_timings=False):
        import json

        return json.dumps(
            self.to_dict(include_timings),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )


def project_claim(bearers, extensions, defeaters):
    accepted = [bool(bearers & e) for e in extensions]
    if all(accepted):
        return "JUSTIFIED"
    if any(accepted):
        return "DEFENSIBLE"
    if all(all(defeaters.get(b, set()) & e for b in bearers) for e in extensions):
        return "OVERRULED"
    return "UNDECIDED"


def claim_statuses(exts, arguments, edges, ids):
    if not exts:
        return {}
    byclaim = {}
    for a in arguments:
        byclaim.setdefault(str(a.conclusion), set()).add(ids[a])
    defeaters = {}
    for x, y in edges:
        defeaters.setdefault(y, set()).add(x)
    family = [frozenset(e) for e in exts]
    return {c: project_claim(bearers, family, defeaters) for c, bearers in byclaim.items()}


def _evaluate_core_impl(
    source,
    semantics="grounded",
    ordering="last_link_elitist",
    cycle_policy=None,
    depth=None,
    budget=None,
    limits=None,
    stop_after=None,
    conflict_free="defeat",
    transposition=False,
    deadline_start=None,
):
    started = perf_counter()
    timings = {}
    stage = "validation"
    token = CURRENT.set(Meter(limits)) if limits and CURRENT.get() is None else None
    if limits and CURRENT.get() is not None:
        CURRENT.get().deadline = (deadline_start or monotonic()) + limits.wall_seconds

    def _remaining():
        meter_now = CURRENT.get()
        return (
            (meter_now.deadline - monotonic()) if meter_now and meter_now.deadline else float("inf")
        )

    args = ()
    raw = []
    edges = set()
    ids = {}
    theory = None
    cyclic = False
    framework_complete = False
    successful_events = []
    stored = {
        "semantics": semantics,
        "ordering": ordering,
        "cycle_policy": cycle_policy,
        "depth": depth,
    }

    def resource_record(**extra):
        m = CURRENT.get()
        now = monotonic()
        return {
            **dict(
                complete=False,
                framework_complete=framework_complete,
                semantics=semantics,
                partial_family_available=False,
                final_extension_count=m.final_extensions if m else 0,
                candidate_model_count=m.models if m else 0,
                dependency_phase=m.semantic_phase if m else None,
                elapsed_ms=round((perf_counter() - started) * 1000, 3),
                semantic_elapsed_ms=(
                    round(timings.get("semantics", now - m.semantic_started) * 1000, 3)
                    if m and m.semantic_started
                    else None
                ),
                argument_count=len(args),
                attack_pair_checks=m.pairs if m else 0,
                raw_attack_count=len(raw),
                defeat_count=len(edges),
                construction_candidates=budget.candidates if budget else 0,
            ),
            **extra,
        }

    def snapshot(status, resource):
        return Evaluation(
            status,
            tuple(sorted(args, key=lambda a: a.id)),
            tuple(sorted(raw, key=lambda a: a.id)),
            frozenset(edges),
            (),
            ids,
            {},
            timings,
            policy=cycle_policy if cyclic else "EXACT",
            theory=theory,
            configuration=stored,
            resource=resource,
            defeat_witnesses=_witnesses(),
        )

    def _witnesses():
        groups = {}
        for event in successful_events:
            groups.setdefault((ids[event.attacker], ids[event.target]), []).append(event.id)
        return {edge: tuple(sorted(v)) for edge, v in groups.items()}

    try:
        if stop_after not in (None, "construct", "attack", "defeat"):
            raise ValueError("Unknown construction stop stage")
        stored = stored_configuration(
            configuration(
                {
                    "semantics": semantics,
                    "ordering": ordering,
                    "cycle_policy": cycle_policy,
                    "depth": depth,
                    "conflict_free": conflict_free,
                    "transposition": transposition,
                }
            )
        )
        enter_stage("parse")
        theory = Theory.parse(source) if isinstance(source, str) else source
        if not isinstance(theory, Theory):
            raise ValueError("expected Theory or source text")
        if transposition:
            theory = close_under_transposition(theory)
        if limits and any(len(str(l).encode()) > limits.label_bytes for l in theory.language):
            raise ResourceLimit("VALIDATION_ERROR", "label byte limit exceeded")
        timings["parse_validate"] = perf_counter() - started
        cyclic = theory.topological_literals is None
        if cyclic and cycle_policy is None:
            return Evaluation("CYCLE_POLICY_REQUIRED")
        if cyclic and cycle_policy == "REJECT":
            return Evaluation("CYCLE_REJECTED")
        constructor = CyclicConstructor(cycle_policy, depth) if cyclic else NativeExactConstructor()
        if cyclic and str(cycle_policy).startswith("QUOTIENT"):
            from .worklist import QuotientWorklistConstructor

            constructor = QuotientWorklistConstructor(
                "semantic_signature" if cycle_policy == "QUOTIENT" else "attack_class_signature"
            )
        if limits:
            count = (
                min(limits.arguments, limits.quotient_classes)
                if cyclic and str(cycle_policy).startswith("QUOTIENT")
                else limits.arguments
            )
            budget = TrackedBudget(
                max_arguments=None if limits.time_only else count,
                max_candidates=(None if limits.time_only else limits.construction_candidates),
                seconds=max(1e-6, min(limits.construct_seconds, _remaining())),
            )
            budget.memory_bytes = limits.memory_bytes
            budget._memory_base = _rss_bytes()
        enter_stage("construct")
        stage = "construction"
        mark = perf_counter()
        args = constructor.construct(theory, budget)
        timings["construct"] = perf_counter() - mark
        if stop_after == "construct":
            ids = {a: a.id for a in args}
            return snapshot("CONSTRUCTION_COMPLETE", resource_record(completed_stage="construct"))
        enter_stage("compile")
        consume("compile_items", len(args), "CONSTRUCTION_LIMIT")
        stage = "relations"
        mark = perf_counter()
        ids = {a: a.id for a in args}
        raw = []
        edges = set()
        if len(set(ids.values())) != len(ids):
            raise RuntimeError("argument ID collision")
        meter = CURRENT.get()
        enter_stage("attack")

        def probe():
            if not meter:
                return
            meter.pairs += 1
            if not limits.time_only and meter.pairs > limits.attack_pairs:
                raise ResourceLimit(
                    "CONSTRUCTION_LIMIT",
                    "attack-probe budget exceeded",
                    limit_kind="attack_pairs",
                    limit_value=limits.attack_pairs,
                    observed_count=meter.pairs,
                )
            if meter.pairs % 128 == 0 and (
                perf_counter() - started > limits.construct_seconds or _remaining() <= 0
            ):
                raise ResourceLimit(
                    "TIME_LIMIT" if limits.time_only else "CONSTRUCTION_LIMIT",
                    "Construction wall time exceeded",
                    limit_kind="construction_time",
                    limit_value=limits.construct_seconds,
                    observed_count=meter.pairs,
                )

        for event in all_attacks(theory, args, probe):
            if meter:
                meter.witnesses += 1
                if not limits.time_only and meter.witnesses > limits.attack_witnesses:
                    raise ResourceLimit(
                        "CONSTRUCTION_LIMIT",
                        "attack-witness budget exceeded",
                        limit_kind="attack_witnesses",
                        limit_value=limits.attack_witnesses,
                        observed_count=meter.witnesses,
                    )
            raw.append(event)
        timings["attack"] = perf_counter() - mark
        mark = perf_counter()
        if stop_after == "attack":
            return snapshot("CONSTRUCTION_COMPLETE", resource_record(completed_stage="attack"))
        enter_stage("preference")
        successful_events = [e for e in raw if succeeds(theory, e, ordering)]
        enter_stage("defeat")
        for event in successful_events:
            edge = (ids[event.attacker], ids[event.target])
            if edge not in edges:
                consume("defeats")
                edges.add(edge)
        timings["preference_and_defeat"] = perf_counter() - mark
        framework_complete = True
        if stop_after == "defeat":
            return snapshot("FRAMEWORK_COMPLETE", resource_record(completed_stage="defeat"))
        enter_stage("semantics")
        stage = "semantics"
        mark = perf_counter()
        if meter:
            meter.semantic_started = monotonic()
        conflicts = (
            {(ids[e.attacker], ids[e.target]) for e in raw} if conflict_free == "attack" else None
        )
        exts = tuple(
            sorted(
                set(extensions(ids.values(), edges, semantics, conflicts)),
                key=lambda e: sorted(e),
            )
        )
        if meter:
            meter.final_extensions = len(exts)
        if limits and not limits.time_only and len(exts) > limits.extensions:
            raise ResourceLimit(
                "SEMANTICS_LIMIT",
                "Final extension count exceeds configured limit",
                limit_kind="extension_count",
                limit_value=limits.extensions,
                observed_count=len(exts),
            )
        if meter:
            meter.final_extensions = len(exts)
        timings["semantics"] = perf_counter() - mark
        if limits and timings["semantics"] > limits.semantics_seconds:
            raise ResourceLimit(
                "TIME_LIMIT" if limits.time_only else "SEMANTICS_LIMIT",
                "Semantic time budget exceeded",
                limit_kind="solver_time",
                limit_value=limits.semantics_seconds,
                observed_count=meter.models if meter else None,
            )
        enter_stage("analysis")
        stage = "projection"
        mark = perf_counter()
        statuses = claim_statuses(exts, args, edges, ids)
        timings["claim_projection"] = perf_counter() - mark
        if limits and _remaining() <= 0:
            raise ResourceLimit(
                "TIME_LIMIT" if limits.time_only else "SEMANTICS_LIMIT",
                "Total evaluation deadline exceeded",
                limit_kind="total_time",
                limit_value=limits.wall_seconds,
                observed_count=None,
            )
        timings["total"] = perf_counter() - started
        status = "REFERENCE_LIMIT" if cyclic and cycle_policy == "UNRESTRICTED_UNROLL" else "OK"
        return Evaluation(
            status,
            tuple(sorted(args, key=lambda a: ids[a])),
            tuple(sorted(raw, key=lambda a: a.id)),
            frozenset(edges),
            exts,
            ids,
            statuses,
            timings,
            policy=cycle_policy if cyclic else "EXACT",
            theory=theory,
            configuration=stored,
            resource={**resource_record(), "complete": True},
            defeat_witnesses=_witnesses(),
        )
    except ConfigurationError as exc:
        return Evaluation("CONFIGURATION_ERROR", error=str(exc), timings=timings)
    except ResourceLimit as exc:
        details = resource_record(**exc.details)
        code = exc.status
        if limits and limits.time_only:
            code = (
                "TIME_LIMIT"
                if "time" in details.get("limit_kind", "")
                else (
                    "MEMORY_LIMIT"
                    if details.get("limit_kind") == "memory_bytes"
                    else "PROCESS_RESOURCE_FAILURE"
                )
            )
            active = CURRENT.get()
            phase = active.stage_name if active else stage
            details["phase"] = {
                "construct": "construction",
                "compile": "construction",
            }.get(phase, phase)
        if (
            not (limits and limits.time_only)
            and stage == "relations"
            and code in ("RELATION_LIMIT", "TIME_LIMIT")
        ):
            code = "CONSTRUCTION_LIMIT"
        if "limit_kind" not in details:
            details.update(limit_kind=str(exc).split()[0], limit_value=None, observed_count=None)
        if framework_complete:
            return __import__("dataclasses").replace(snapshot(code, details), error=str(exc))
        return Evaluation(code, error=str(exc), timings=timings, resource=details)
    except ConstructionLimit as exc:
        kind = (
            "construction_candidates"
            if budget
            and budget.max_candidates is not None
            and budget.candidates > budget.max_candidates
            else (
                "construction_time"
                if budget
                and limits
                and budget.seconds is not None
                and monotonic() - budget.started >= budget.seconds
                else (
                    "quotient_classes"
                    if limits
                    and cyclic
                    and str(cycle_policy).startswith("QUOTIENT")
                    and limits.quotient_classes < limits.arguments
                    else "arguments"
                )
            )
        )
        return Evaluation(
            (
                ("TIME_LIMIT" if kind == "construction_time" else "PROCESS_RESOURCE_FAILURE")
                if limits and limits.time_only
                else "CONSTRUCTION_LIMIT" if limits else "LIMIT_REACHED"
            ),
            error=str(exc),
            timings=timings,
            resource=resource_record(
                phase="construction",
                limit_kind=kind,
                limit_value=(
                    getattr(
                        limits,
                        {"construction_time": "construct_seconds"}.get(kind, kind),
                    )
                    if limits
                    else None
                ),
                observed_count=(
                    budget.candidates
                    if kind == "construction_candidates"
                    else (
                        getattr(budget, "observed_arguments", None)
                        if kind in ("arguments", "quotient_classes")
                        else None
                    )
                ),
            ),
        )
    except (ValueError, TypeError) as exc:
        return Evaluation(
            (
                ("VALIDATION_ERROR" if limits else "INVALID_THEORY")
                if stage == "validation"
                else "INTERNAL_ERROR"
            ),
            error=str(exc),
            timings=timings,
        )
    except MemoryError:
        return Evaluation(
            (
                "MEMORY_FAILURE"
                if limits and limits.time_only
                else "SEMANTICS_LIMIT" if stage == "semantics" else "MEMORY_LIMIT"
            ),
            error="worker memory allocation failed",
            timings=timings,
            resource={
                "complete": False,
                "framework_complete": framework_complete,
                "partial_family_available": False,
                "limit_kind": "memory",
                "limit_value": limits.memory_bytes if limits else None,
                "observed_count": None,
                "semantics": semantics,
            },
        )
    except OSError as exc:
        return Evaluation(
            (
                ("MEMORY_FAILURE" if limits and limits.time_only else "MEMORY_LIMIT")
                if exc.errno == errno.ENOMEM
                else "INTERNAL_ERROR"
            ),
            error=str(exc),
            timings=timings,
        )
    except RecursionError:
        return Evaluation(
            ("PROCESS_RESOURCE_FAILURE" if limits and limits.time_only else "CONSTRUCTION_LIMIT"),
            error="Python recursion limit reached; no complete result",
            timings=timings,
        )
    except Exception as exc:
        return Evaluation(
            "INTERNAL_ERROR",
            error=type(exc).__name__ + ": " + str(exc),
            timings=timings,
        )
    finally:
        if token is not None:
            CURRENT.reset(token)


def _evaluate_core(*args, **kwargs):
    result = _evaluate_core_impl(*args, **kwargs)
    if result.status not in ("OK", "REFERENCE_LIMIT"):
        import gc

        gc.collect()
    return result
