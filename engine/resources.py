from dataclasses import dataclass, asdict, field
from contextvars import ContextVar
import math, os, time, json
from collections import Counter

STAGE_FD = None
STAGE_PATH = None


def finish_stage():
    meter = CURRENT.get()
    if (
        meter is not None
        and meter.stage_name is not None
        and meter.stage_elapsed[meter.stage_name] + time.monotonic() - meter.stage_start
        > getattr(meter.limits, meter.stage_name + "_seconds")
    ):
        raise ResourceLimit(
            (
                "TIME_LIMIT"
                if meter.limits.time_only
                else (
                    "SEMANTICS_LIMIT"
                    if meter.stage_name == "semantics"
                    else (
                        "CONSTRUCTION_LIMIT"
                        if meter.stage_name
                        in ("construct", "compile", "attack", "preference", "defeat")
                        else "TIME_LIMIT"
                    )
                )
            ),
            meter.stage_name + " stage limit",
            limit_kind=(
                "solver_time" if meter.stage_name == "semantics" else meter.stage_name + "_time"
            ),
            limit_value=getattr(meter.limits, meter.stage_name + "_seconds"),
            observed_count=None,
        )


def enter_stage(name):
    meter = CURRENT.get()
    if meter is None:
        return
    finish_stage()
    if name == meter.stage_name:
        return
    now = time.monotonic()
    if meter.stage_name is not None:
        meter.stage_elapsed[meter.stage_name] += now - meter.stage_start
    meter.stage_name = name
    meter.stage_start = now
    if STAGE_PATH is not None:
        from pathlib import Path

        Path(STAGE_PATH).write_text(
            json.dumps([name, meter.stage_start - meter.stage_elapsed[name]])
        )
    if STAGE_FD is not None:
        raw = json.dumps([name, meter.stage_start - meter.stage_elapsed[name]]).encode()
        os.lseek(STAGE_FD, 0, 0)
        os.write(STAGE_FD, raw)
        os.ftruncate(STAGE_FD, len(raw))


def consume(name, amount=1, status="RELATION_LIMIT"):
    meter = CURRENT.get()
    if meter is not None:
        meter.counts[name] += amount
        if not meter.limits.time_only and meter.counts[name] > getattr(meter.limits, name):
            raise ResourceLimit(
                status,
                name + " budget exceeded",
                limit_kind=name,
                limit_value=getattr(meter.limits, name),
                observed_count=meter.counts[name],
            )


@dataclass(frozen=True, slots=True)
class Limits:
    time_only: bool = True
    wall_seconds: float = 60.0
    memory_bytes: int = 536870912
    input_bytes: int = 1048576
    label_bytes: int = 16384
    arguments: int = 10000
    quotient_classes: int = 10000
    construction_candidates: int = 1000000
    attack_pairs: int = 1000000
    attack_witnesses: int = 100000
    solver_models: int = 10000
    extensions: int = 10000
    output_bytes: int = 10485760
    defeats: int = 100000
    preference_checks: int = 100000
    compile_items: int = 100000
    analysis_work: int = 1000000
    comparison_work: int = 1000000
    analysis_nodes: int = 1000
    analysis_edges: int = 10000
    parse_seconds: float = 60.0
    validate_seconds: float = 60.0
    construct_seconds: float = 60.0
    compile_seconds: float = 60.0
    attack_seconds: float = 60.0
    preference_seconds: float = 60.0
    defeat_seconds: float = 60.0
    semantics_seconds: float = 60.0
    analysis_seconds: float = 60.0
    comparison_seconds: float = 60.0
    serialization_seconds: float = 60.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "time_only":
                if type(value) is not bool:
                    raise ValueError("time_only must be boolean")
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("limits must be finite positive numbers")
            if not name.endswith("seconds") and not isinstance(value, int):
                raise ValueError("count/byte limits must be integers")


class ResourceLimit(RuntimeError):
    def __init__(self, status, message, **details):
        self.status = status
        self.details = details
        super().__init__(message)


@dataclass
class Meter:
    limits: Limits
    models: int = 0
    pairs: int = 0
    witnesses: int = 0
    counts: object = field(default_factory=Counter)
    stage_elapsed: object = field(default_factory=Counter)
    stage_name: str | None = None
    stage_start: float = 0.0
    semantic_phase: str = "not_started"
    final_extensions: int = 0
    final_seen: object = field(default_factory=set)
    semantic_started: float = 0.0
    deadline: float = 0.0


CURRENT = ContextVar("evaluation_meter", default=None)


class ControlledSolver:

    def __init__(self, control):
        self.control = control

    def __getattr__(self, name):
        return getattr(self.control, name)

    def solve(self, *args, **kwargs):
        meter = CURRENT.get()
        callback = kwargs.pop("on_model", None)
        exhausted = None

        def on_model(model):
            nonlocal exhausted
            if meter is not None:
                meter.models += 1
                if not meter.limits.time_only and meter.models > meter.limits.solver_models:
                    exhausted = ResourceLimit(
                        "SEMANTICS_LIMIT",
                        "Intermediate solver model limit exceeded",
                        limit_kind="intermediate_model_count",
                        limit_value=meter.limits.solver_models,
                        observed_count=meter.models,
                        dependency_phase=meter.semantic_phase,
                    )
                    return False
                if meter.semantic_phase in ("final_direct", "final_exact_range"):
                    ext = frozenset(
                        s.arguments[0].string for s in model.symbols(shown=True) if s.name == "in"
                    )
                    meter.final_seen.add(ext)
                    meter.final_extensions = len(meter.final_seen)
                    if (
                        not meter.limits.time_only
                        and meter.final_extensions > meter.limits.extensions
                    ):
                        exhausted = ResourceLimit(
                            "SEMANTICS_LIMIT",
                            "Final extension count exceeds configured limit",
                            limit_kind="extension_count",
                            limit_value=meter.limits.extensions,
                            observed_count=meter.final_extensions,
                            dependency_phase=meter.semantic_phase,
                        )
                        return False
            return callback(model) if callback else True

        if meter is None:
            return self.control.solve(*args, on_model=on_model, **kwargs)
        remaining = meter.limits.semantics_seconds - (time.monotonic() - meter.semantic_started)
        if meter.deadline:
            remaining = min(remaining, meter.deadline - time.monotonic())
        if remaining <= 0:
            raise ResourceLimit(
                "TIME_LIMIT" if meter.limits.time_only else "SEMANTICS_LIMIT",
                "Semantic solver time budget exceeded",
                limit_kind="solver_time",
                limit_value=meter.limits.semantics_seconds,
                observed_count=meter.models,
                dependency_phase=meter.semantic_phase,
            )
        with self.control.solve(*args, on_model=on_model, async_=True, **kwargs) as handle:
            if not handle.wait(remaining):
                handle.cancel()
                handle.wait()
                raise ResourceLimit(
                    "TIME_LIMIT" if meter.limits.time_only else "SEMANTICS_LIMIT",
                    "Semantic solver time budget exceeded",
                    limit_kind="solver_time",
                    limit_value=meter.limits.semantics_seconds,
                    observed_count=meter.models,
                    dependency_phase=meter.semantic_phase,
                )
            result = handle.get()
        if exhausted:
            raise exhausted
        return result


def check_time():
    meter = CURRENT.get()
    if meter is None:
        return
    remaining = meter.limits.semantics_seconds - (time.monotonic() - meter.semantic_started)
    if meter.deadline:
        remaining = min(remaining, meter.deadline - time.monotonic())
    if remaining <= 0:
        raise ResourceLimit(
            "TIME_LIMIT" if meter.limits.time_only else "SEMANTICS_LIMIT",
            "Semantic solver time budget exceeded",
            limit_kind="solver_time",
            limit_value=meter.limits.semantics_seconds,
            observed_count=meter.models,
            dependency_phase=meter.semantic_phase,
        )


def semantic_phase(name):
    meter = CURRENT.get()
    if meter is not None:
        meter.semantic_phase = name


def transport_timeout(limits, started, progress=None):
    from .evaluation import Evaluation

    now = time.monotonic()
    stage = None
    began = None
    if progress:
        try:
            from pathlib import Path

            stage, began = json.loads(Path(progress).read_text())
        except (OSError, ValueError, TypeError):
            pass
    semantic = stage == "semantics"
    limit_kind = (
        "solver_time"
        if semantic
        else (
            "construction_time"
            if stage in ("construct", "compile", "attack", "preference", "defeat")
            else "process_time"
        )
    )
    value = (
        limits.semantics_seconds
        if semantic
        else (
            limits.construct_seconds if limit_kind == "construction_time" else limits.wall_seconds
        )
    )
    overall = now - started >= limits.wall_seconds
    exceeded = overall or semantic and now - began >= limits.semantics_seconds
    if overall and semantic and now - began < limits.semantics_seconds:
        limit_kind = "process_limit"
        value = limits.wall_seconds
    if not exceeded:
        return None
    code = (
        "TIME_LIMIT"
        if limits.time_only
        else (
            "SEMANTICS_LIMIT"
            if semantic
            else ("CONSTRUCTION_LIMIT" if limit_kind == "construction_time" else "TIME_LIMIT")
        )
    )
    return Evaluation(
        code,
        error="Worker watchdog time budget exceeded",
        resource=dict(
            complete=False,
            framework_complete=semantic,
            partial_family_available=False,
            phase={"construct": "construction", "compile": "construction"}.get(
                stage, stage or "startup"
            ),
            limit_kind=limit_kind,
            limit_value=value,
            observed_count=None,
            elapsed_ms=round((now - started) * 1000, 3),
            dependency_phase="unknown_after_worker_termination",
            termination="worker_watchdog",
        ),
    )


def report_transport_stage(name):
    if STAGE_PATH is not None:
        from pathlib import Path

        Path(STAGE_PATH).write_text(json.dumps([name, time.monotonic()]))
