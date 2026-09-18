"""An open agent harness for the nonprofit sector."""

from nonprofit_harness.core.agent import Agent, RunContext
from nonprofit_harness.core.errors import (
    AgentFailed,
    BudgetExceeded,
    HarnessError,
    NotFound,
    ReviewRequired,
)
from nonprofit_harness.core.registry import AgentRegistry, registry
from nonprofit_harness.core.types import (
    AgentResult,
    Artifact,
    ArtifactStatus,
    Document,
    Review,
    Run,
    RunStatus,
    Usage,
)
from nonprofit_harness.verification import (
    Citation,
    Claim,
    GroundingVerifier,
    Outcome,
    Verdict,
    VerificationReport,
)


def _detect_version() -> str:
    """Read the version from installed metadata rather than repeating it here.

    Hardcoding it means a release has to remember to change two files, and the one
    that gets forgotten is this one, which then reports a version the package is not.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("nonprofit-agent-harness")
    except PackageNotFoundError:  # a source tree that was never installed
        return "0.0.0+unknown"


__version__ = _detect_version()

__all__ = [
    "Agent",
    "AgentFailed",
    "AgentRegistry",
    "AgentResult",
    "Artifact",
    "ArtifactStatus",
    "BudgetExceeded",
    "Citation",
    "Claim",
    "Document",
    "GroundingVerifier",
    "HarnessError",
    "NotFound",
    "Outcome",
    "Review",
    "ReviewRequired",
    "Run",
    "RunContext",
    "RunStatus",
    "Usage",
    "VerificationReport",
    "Verdict",
    "__version__",
    "registry",
]
