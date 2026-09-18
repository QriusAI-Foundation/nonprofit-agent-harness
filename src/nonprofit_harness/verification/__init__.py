"""Verifying that what an artifact asserts is actually in its sources.

The citation check costs nothing and runs offline. The cross-check costs model
calls and is opt-in. Both report to a human rather than deciding on their own: a
failed claim is a pointer for a reviewer, not grounds for throwing work away.
"""

from nonprofit_harness.verification.grounding import (
    SourceIndex,
    is_grounded,
    normalize,
    tokenize,
)
from nonprofit_harness.verification.types import (
    Citation,
    Claim,
    GroundingHit,
    Outcome,
    Verdict,
    VerificationReport,
)
from nonprofit_harness.verification.verifier import (
    SUPPORTED,
    UNSUPPORTED,
    UNSURE,
    GroundingVerifier,
)

__all__ = [
    "SUPPORTED",
    "UNSUPPORTED",
    "UNSURE",
    "Citation",
    "Claim",
    "GroundingHit",
    "GroundingVerifier",
    "Outcome",
    "SourceIndex",
    "VerificationReport",
    "Verdict",
    "is_grounded",
    "normalize",
    "tokenize",
]
