from pathlib import Path
from dataclasses import asdict
import json, os, sys, time, tempfile, subprocess, signal
from .resource_policy import time_limits, resolve


def _failure(source, config, seconds, status, phase, elapsed, reason):
    from engine.evaluation import Evaluation
    from explanation_and_analysis.experiments import from_evaluation

    e = Evaluation(
        status,
        error=reason,
        configuration=config.core(),
        resource={
            "complete": False,
            "phase": phase,
            "limit_kind": "time" if status == "TIME_LIMIT" else "process",
            "limit_value": seconds,
            "observed_count": None,
            "elapsed_ms": elapsed * 1000,
            "partial_family_available": False,
        },
    )
    r = from_evaluation(e, config, limits=time_limits(seconds))
    r.metadata["submitted_source"] = source
    from explanation_and_analysis.common import identity

    r.metadata.update(
        theory_hash=identity(source),
        theory_hash_scope="submitted source (deadline expired)",
        canonical_theory=None,
        time_execution=resolve(seconds)[1],
        evaluation_wall_seconds=elapsed,
    )
    return r


def _stop_worker(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def evaluate_research(source, config, seconds=60, provenance=None):
    from explanation_and_analysis.experiments import ResearchResult, config_from_dict
    from engine.serialization import evaluation_from_dict

    if hasattr(source, "rules"):
        from engine.surface import serialize_theory

        source = serialize_theory(source)
    lim = time_limits(seconds)
    start = time.monotonic()
    proc = None
    with tempfile.TemporaryDirectory(prefix="argforge-config-") as td:
        req = Path(td) / "request.json"
        out = Path(td) / "result.json"
        phase = Path(td) / "phase.json"
        req.write_text(
            json.dumps(
                dict(
                    source=source,
                    configuration=asdict(config),
                    seconds=seconds,
                    provenance=provenance or {},
                    phase=str(phase),
                )
            ),
            encoding="utf-8",
        )
        env = dict(os.environ)
        try:
            if os.name == "nt":
                from argforge_platform.jobs import WindowsJobProcess

                proc = WindowsJobProcess(
                    "research",
                    [req, out],
                    memory=lim.memory_bytes,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
            else:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "argforge.evaluation_runner.research_worker",
                        str(req),
                        str(out),
                    ],
                    env=env,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            try:
                proc.wait(timeout=max(0.001, seconds - (time.monotonic() - start)))
            except subprocess.TimeoutExpired:
                try:
                    stage = json.loads(phase.read_text())[0]
                except Exception:
                    stage = "startup"
                return _failure(
                    source,
                    config,
                    seconds,
                    "TIME_LIMIT",
                    {"construct": "construction", "compile": "construction"}.get(stage, stage),
                    time.monotonic() - start,
                    "Configuration time limit expired; no complete result",
                )
            if not out.exists():
                return _failure(
                    source,
                    config,
                    seconds,
                    "PROCESS_TERMINATED",
                    "unknown",
                    time.monotonic() - start,
                    "Contained worker exited without a result",
                )
            if out.stat().st_size > lim.output_bytes:
                return _failure(
                    source,
                    config,
                    seconds,
                    "PROCESS_RESOURCE_FAILURE",
                    "serialization",
                    time.monotonic() - start,
                    "Emergency output containment",
                )
            d = json.loads(out.read_text())
            e = evaluation_from_dict(d["evaluation"], _trusted=True)
            r = ResearchResult(
                e, config_from_dict(d["configuration"]), d["metadata"], d["analysis"]
            )
            if time.monotonic() - start > seconds:
                return _failure(
                    source,
                    config,
                    seconds,
                    "TIME_LIMIT",
                    "serialization",
                    time.monotonic() - start,
                    "Result decoding exceeded configuration time",
                )
            r.metadata.update(
                submitted_source=source,
                time_execution=resolve(seconds)[1],
                evaluation_wall_seconds=time.monotonic() - start,
            )
            return r
        finally:
            if proc:
                if os.name == "nt":
                    proc.close()
                elif proc.poll() is None:
                    _stop_worker(proc)
