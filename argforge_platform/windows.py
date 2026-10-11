import json, os, sys, tempfile, time, subprocess
from pathlib import Path
from dataclasses import asdict
from .jobs import WindowsJobProcess


def evaluate(
    source,
    semantics="grounded",
    ordering="last_link_elitist",
    cycle_policy=None,
    depth=None,
    *,
    limits=None,
    cancel=None,
    stop_after=None,
    conflict_free="defeat",
    transposition=False,
):
    from engine import Theory, Limits, Evaluation
    from engine.serialization import (
        theory_to_dict,
        evaluation_from_dict,
    )

    limits = Limits() if limits is None else limits
    if not isinstance(limits, Limits):
        return Evaluation("VALIDATION_ERROR", error="expected Limits")
    if not isinstance(source, (str, Theory)):
        return Evaluation("VALIDATION_ERROR", error="expected source text or Theory")
    if isinstance(source, str) and len(source) > limits.input_bytes:
        return Evaluation("VALIDATION_ERROR", error="input byte budget exceeded")
    if cancel is not None and cancel.is_set():
        return Evaluation("CANCELLED", error="cancelled before launch")
    request = {
        "source": theory_to_dict(source) if isinstance(source, Theory) else source,
        "structured": isinstance(source, Theory),
        "configuration": dict(
            semantics=semantics,
            ordering=ordering,
            cycle_policy=cycle_policy,
            depth=depth,
            conflict_free=conflict_free,
            transposition=transposition,
        ),
        "limits": asdict(limits),
        "stop_after": stop_after,
    }
    try:
        chunks = []
        size = 0
        for chunk in json.JSONEncoder(ensure_ascii=True, separators=(",", ":")).iterencode(request):
            encoded = chunk.encode("utf-8")
            size += len(encoded)
            if size > limits.input_bytes:
                return Evaluation("VALIDATION_ERROR", error="request JSON byte budget exceeded")
            chunks.append(encoded)
    except (ValueError, TypeError, RecursionError):
        return Evaluation("VALIDATION_ERROR", error="invalid request")
    start = time.monotonic()
    proc = None
    with tempfile.TemporaryDirectory(prefix="argforge-eval-") as td:
        request["progress_path"] = str(Path(td) / "stage.json")
        req = Path(td) / "request.json"
        out = Path(td) / "result.json"
        req.write_text(json.dumps(request), encoding="utf-8")
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                proc = WindowsJobProcess(
                    "evaluate",
                    [req, out],
                    memory=limits.memory_bytes,
                    stdout=stdout,
                    stderr=stderr,
                )
                while proc.poll() is None:
                    if cancel is not None and cancel.is_set():
                        return Evaluation("CANCELLED", error="cancelled; Job terminated")
                    from engine.resources import transport_timeout

                    stopped = transport_timeout(limits, start, request["progress_path"])
                    if stopped:
                        return stopped
                    if os.fstat(stderr.fileno()).st_size > max(limits.output_bytes, 4096):
                        return Evaluation(
                            ("PROCESS_RESOURCE_FAILURE" if limits.time_only else "OUTPUT_LIMIT"),
                            error="worker diagnostic output budget exceeded",
                        )
                    if out.exists() and out.stat().st_size > max(limits.output_bytes, 4096):
                        return Evaluation(
                            ("PROCESS_RESOURCE_FAILURE" if limits.time_only else "OUTPUT_LIMIT"),
                            error="transport budget exceeded",
                        )
                    try:
                        proc.wait(timeout=0.02)
                    except subprocess.TimeoutExpired:
                        pass
                if not out.exists():
                    return Evaluation(
                        "PROCESS_TERMINATED" if limits.time_only else "INTERNAL_ERROR",
                        error="Windows worker exited without a result: " + str(proc.returncode),
                    )
                if out.stat().st_size > max(limits.output_bytes, 4096):
                    return Evaluation(
                        ("PROCESS_RESOURCE_FAILURE" if limits.time_only else "OUTPUT_LIMIT"),
                        error="transport budget exceeded",
                    )
                result = evaluation_from_dict(json.loads(out.read_bytes()), _trusted=True)
                if time.monotonic() - start >= limits.wall_seconds:
                    return Evaluation(
                        "TIME_LIMIT",
                        error="result decoding exceeded wall-clock time",
                        resource={
                            "complete": False,
                            "phase": "serialization",
                            "limit_kind": "serialization_time",
                            "limit_value": limits.wall_seconds,
                            "partial_family_available": False,
                        },
                    )
                return result
            except ImportError:
                return Evaluation(
                    "INTERNAL_ERROR",
                    error="Windows runtime requires the declared pywin32 dependency",
                )
            except (OSError, ValueError, KeyError, RecursionError) as e:
                return Evaluation("INTERNAL_ERROR", error="Windows transport: " + type(e).__name__)
            finally:
                if proc:
                    proc.close()


def worker(request_path, output_path):
    from engine import Evaluation, Limits
    from engine.protocol import loads
    from engine.serialization import theory_from_dict
    from engine.evaluation import _evaluate_core

    limits = None
    try:
        request = loads(Path(request_path).read_bytes())
        limits = Limits(**request["limits"])
        from engine import resources

        resources.STAGE_PATH = request.get("progress_path")
        source = theory_from_dict(request["source"]) if request["structured"] else request["source"]
        result = _evaluate_core(
            source,
            **request["configuration"],
            limits=limits,
            stop_after=request.get("stop_after"),
        )
        resources.report_transport_stage("serialization")
        data = result.to_dict(include_timings=True)
        chunks = []
        size = 0
        for chunk in json.JSONEncoder(
            sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).iterencode(data):
            size += len(chunk.encode("utf-8"))
            if size > limits.output_bytes:
                chunks = [
                    json.dumps(
                        Evaluation(
                            ("PROCESS_RESOURCE_FAILURE" if limits.time_only else "OUTPUT_LIMIT"),
                            error="serialized result exceeds budget",
                        ).to_dict()
                    )
                ]
                break
            chunks.append(chunk)
        raw = "".join(chunks)
    except MemoryError:
        raw = json.dumps(
            Evaluation(
                ("MEMORY_FAILURE" if limits is None or limits.time_only else "MEMORY_LIMIT"),
                error="Windows worker allocation failed",
            ).to_dict()
        )
    except (ValueError, TypeError) as e:
        raw = json.dumps(Evaluation("VALIDATION_ERROR", error=str(e)[:200]).to_dict())
    except Exception as e:
        raw = json.dumps(Evaluation("INTERNAL_ERROR", error=type(e).__name__).to_dict())
    Path(output_path).write_text(raw, encoding="utf-8")
