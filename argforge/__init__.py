from engine import Limits, Theory, __version__
from engine.wellformed import close_under_transposition, diagnose
from explanation_and_analysis.experiments import Config
from explanation_and_analysis.experiments import research_evaluate as evaluate

from .api import (
    ArgumentationError,
    ArgumentInfo,
    ArgumentStatus,
    AttackInfo,
    ClaimInfo,
    Reasoner,
    Result,
    SolverConfig,
    TheoryBuilder,
    as_theory,
    solve,
)
from .gradual import strengths
from .graphs import Graph
from .lint import lint
from . import nl
from .generator import GeneratorParams, generate

__all__ = [
    "ArgumentInfo",
    "ArgumentStatus",
    "ArgumentationError",
    "AttackInfo",
    "ClaimInfo",
    "Config",
    "Graph",
    "Limits",
    "Reasoner",
    "Result",
    "SolverConfig",
    "Theory",
    "TheoryBuilder",
    "__version__",
    "as_theory",
    "close_under_transposition",
    "diagnose",
    "lint",
    "GeneratorParams",
    "generate",
    "evaluate",
    "solve",
    "strengths",
]


def diagnose(theory):
    from engine.wellformed import diagnose as _diagnose

    from .api import as_theory

    return _diagnose(as_theory(theory))
