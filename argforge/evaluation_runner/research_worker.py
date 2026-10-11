import json, sys, os, time
from pathlib import Path


def main(request, output):
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
        resource.setrlimit(resource.RLIMIT_FSIZE, (25165824, 25165824))
    p = json.loads(Path(request).read_text())
    phase = Path(p["phase"])
    from explanation_and_analysis.experiments import config_from_dict, from_evaluation
    from engine import resources
    from engine.evaluation import Evaluation, _evaluate_core
    from .resource_policy import time_limits

    start = time.monotonic()
    config = config_from_dict(p["configuration"])
    lim = time_limits(p["seconds"])
    try:
        import clingo

        resources.STAGE_PATH = str(phase)
        e = _evaluate_core(p["source"], **config.core(), limits=lim)
        phase.write_text(json.dumps(["analysis", time.monotonic()]))
        analysis_start = time.monotonic()
        r = from_evaluation(
            e,
            config,
            p.get("provenance"),
            lim,
            max_nodes=float("inf"),
            max_edges=float("inf"),
        )
        r.metadata["analysis_elapsed_seconds"] = time.monotonic() - analysis_start
        if clingo.version() != (5, 8, 2):
            r.metadata["solver_version_warning"] = (
                "Validated with clingo 5.8.2; running %s" % ".".join(map(str, clingo.version()))
            )
        if config.transposition or r.metadata["canonical_theory"] is None:
            from engine import Theory
            from engine.serialization import theory_to_dict
            from explanation_and_analysis.common import identity

            t = theory_to_dict(Theory.parse(p["source"]))
            r.metadata.update(canonical_theory=t, theory_hash=identity(t))
        phase.write_text(json.dumps(["serialization", time.monotonic()]))
        d = r.to_dict()
    except MemoryError:
        d = from_evaluation(
            Evaluation("MEMORY_FAILURE", resource={"complete": False, "phase": "analysis"}),
            config,
        ).to_dict()
    except Exception as exc:
        d = from_evaluation(
            Evaluation(
                "PROCESS_RESOURCE_FAILURE",
                error=type(exc).__name__ + ": " + str(exc),
                resource={"complete": False},
            ),
            config,
        ).to_dict()
    Path(output).write_text(json.dumps(d, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
