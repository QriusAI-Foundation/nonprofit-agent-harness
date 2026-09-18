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

__version__ = "0.1.0"

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
