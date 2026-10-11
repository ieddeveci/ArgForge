import json, os, signal, subprocess, sys, tempfile, time
from dataclasses import asdict
from pathlib import Path
from .model import Theory
from .evaluation import Evaluation
from .resources import Limits
from .serialization import theory_to_dict, evaluation_from_dict


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
    limits = Limits() if limits is None else limits
    if not isinstance(limits, Limits):
        return Evaluation("VALIDATION_ERROR", error="expected Limits")
    if os.name != "posix":
        return Evaluation(
            "INTERNAL_ERROR",
            error="OS resource isolation is supported on POSIX only; no unsafe fallback",
        )
    started = time.monotonic()
    if cancel is not None and cancel.is_set():
        return Evaluation("CANCELLED", error="job cancelled before launch")
    if not isinstance(source, (str, Theory)):
        return Evaluation("VALIDATION_ERROR", error="expected source text or Theory")
    if isinstance(source, str) and len(source) > limits.input_bytes:
        return Evaluation("VALIDATION_ERROR", error="input byte budget exceeded")
    try:
        request = {
            "source": source if isinstance(source, str) else theory_to_dict(source),
            "structured": isinstance(source, Theory),
            "configuration": {
                "semantics": semantics,
                "ordering": ordering,
                "cycle_policy": cycle_policy,
                "depth": depth,
                "conflict_free": conflict_free,
                "transposition": transposition,
            },
            "limits": asdict(limits),
            "stop_after": stop_after,
        }
        chunks = []
        size = 0
        for chunk in json.JSONEncoder(ensure_ascii=True, separators=(",", ":")).iterencode(request):
            raw = chunk.encode()
            size += len(raw)
            if size > limits.input_bytes:
                return Evaluation("VALIDATION_ERROR", error="request JSON byte budget exceeded")
            chunks.append(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        return Evaluation("VALIDATION_ERROR", error=type(exc).__name__)
    with tempfile.TemporaryDirectory(
        prefix="argforge-progress-"
    ) as td, tempfile.TemporaryFile() as inp, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        for chunk in chunks:
            inp.write(chunk)
        inp.seek(0)
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("_worker.py")),
            str(limits.memory_bytes),
            str(max(limits.output_bytes, 4096)),
            str(Path(td) / "stage.json"),
        ]
        process = None
        try:
            process = subprocess.Popen(
                command, stdin=inp, stdout=out, stderr=err, start_new_session=True
            )
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    return Evaluation("CANCELLED", error="job cancelled; worker terminated")
                from .resources import transport_timeout

                stopped = transport_timeout(
                    limits,
                    started,
                    str(Path(td) / "stage.json"),
                )
                if stopped:
                    return stopped
                try:
                    process.wait(timeout=min(0.02, limits.wall_seconds))
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode != 0:
                err.seek(0)
                message = err.read(4096).decode(errors="replace")
                if process.returncode == -getattr(signal, "SIGXFSZ", 25):
                    return Evaluation(
                        ("PROCESS_RESOURCE_FAILURE" if limits.time_only else "OUTPUT_LIMIT"),
                        error="worker file-size limit reached",
                    )
                if any(
                    s in message.lower()
                    for s in (
                        "bad_alloc",
                        "cannot allocate memory",
                        "failed to map segment",
                        "memoryerror",
                    )
                ):
                    return Evaluation(
                        "MEMORY_FAILURE" if limits.time_only else "MEMORY_LIMIT",
                        error="worker allocation failed",
                    )
                return Evaluation(
                    "PROCESS_TERMINATED" if limits.time_only else "INTERNAL_ERROR",
                    error="worker exited without a valid result: " + str(process.returncode),
                )
            out.seek(0)
            wire = out.read(max(limits.output_bytes, 4096) + 1)
            if len(wire) > max(limits.output_bytes, 4096):
                return Evaluation(
                    "PROCESS_RESOURCE_FAILURE" if limits.time_only else "OUTPUT_LIMIT",
                    error="worker output exceeded transport budget",
                )
            result = evaluation_from_dict(json.loads(wire), _trusted=True)
            if time.monotonic() - started >= limits.wall_seconds:
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
        except (OSError, ValueError, KeyError, RecursionError) as exc:
            return Evaluation("INTERNAL_ERROR", error="worker protocol: " + type(exc).__name__)
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
