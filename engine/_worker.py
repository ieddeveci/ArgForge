import os, sys, resource, json, errno

memory = int(sys.argv[1])
output = int(sys.argv[2])
resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def fail(status, message):
    return {
        "schema_version": "1.1",
        "status": status,
        "error": message,
        "policy": None,
        "configuration": {},
        "theory": None,
        "arguments": [],
        "argument_nodes": [],
        "attacks": [],
        "defeats": [],
        "extensions": None,
        "claims": {},
        "resource": {"complete": False},
    }


try:
    request = json.load(sys.stdin)
    from engine.resources import Limits
    from engine import resources

    resources.STAGE_PATH = sys.argv[3] if len(sys.argv) > 3 else None
    from engine.serialization import theory_from_dict
    from engine.evaluation import _evaluate_core

    limits = Limits(**request["limits"])
    source = theory_from_dict(request["source"]) if request["structured"] else request["source"]
    result = _evaluate_core(
        source, **request["configuration"], limits=limits, stop_after=request.get("stop_after")
    )
    from dataclasses import replace

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
        1024 if sys.platform != "darwin" else 1
    )
    result = replace(result, timings={**dict(result.timings), "worker_peak_rss_bytes": rss})
    resources.report_transport_stage("serialization")
    data = result.to_dict(include_timings=True)
    encoded = []
    size = 0
    for chunk in json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).iterencode(data):
        size += len(chunk.encode())
        if size > limits.output_bytes:
            data = fail(
                "PROCESS_RESOURCE_FAILURE" if limits.time_only else "OUTPUT_LIMIT",
                "serialized result exceeds output byte budget",
            )
            encoded = None
            break
        encoded.append(chunk)
    wire = "".join(encoded) if encoded is not None else json.dumps(data, separators=(",", ":"))
except MemoryError:
    wire = json.dumps(fail("MEMORY_FAILURE", "worker address-space limit reached"))
except OSError as exc:
    wire = json.dumps(
        fail(
            "MEMORY_FAILURE" if exc.errno == errno.ENOMEM else "INTERNAL_ERROR",
            str(exc)[:200],
        )
    )
except (ValueError, TypeError) as exc:
    wire = json.dumps(fail("VALIDATION_ERROR", str(exc)[:200]))
except Exception as exc:
    wire = json.dumps(fail("INTERNAL_ERROR", type(exc).__name__ + ": " + str(exc)[:200]))
sys.stdout.write(wire)
