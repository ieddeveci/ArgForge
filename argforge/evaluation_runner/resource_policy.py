from dataclasses import asdict
from engine.resources import Limits
import math, platform

VISUAL = {
    "max_nodes": 150,
    "max_edges": 600,
    "initial_extensions": 6,
    "initial_claims": 6,
}


def time_limits(seconds=60):
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or not 0 < seconds <= 300
    ):
        raise ValueError("Time limit must be greater than 0 and at most 300 seconds")
    return Limits(
        time_only=True,
        wall_seconds=seconds,
        **{k: seconds for k in asdict(Limits()) if k.endswith("_seconds") and k != "wall_seconds"},
        output_bytes=24 * 1024 * 1024
    )


def resolve(seconds=60):
    lim = time_limits(seconds)
    return lim, dict(
        schema="time-1",
        time_limit_per_configuration=seconds,
        containment=dict(
            memory_bytes=lim.memory_bytes,
            input_bytes=lim.input_bytes,
            output_bytes=lim.output_bytes,
        ),
        execution_context=dict(
            os=platform.system(),
            python=platform.python_version(),
            processor=platform.machine(),
        ),
    )


def catalog():
    return dict(default_time_seconds=60, maximum_time_seconds=300, presentation=VISUAL)
