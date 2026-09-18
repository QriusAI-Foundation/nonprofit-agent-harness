from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from nonprofit_harness.core.types import AgentResult, Artifact, Document
from nonprofit_harness.providers.base import ModelProvider
from nonprofit_harness.verification.types import Claim


@dataclass(slots=True)
class RunContext:
    """Everything an agent is allowed to touch during one run.

    An agent receives this and nothing else. It never reaches for a global client,
    a database handle, or an environment variable of its own, which is what makes
    the same agent runnable locally with no cloud account and in production unchanged.
    """

    run_id: str
    org_id: str
    inputs: list[Document]
    provider: ModelProvider
    options: dict[str, Any] = field(default_factory=dict)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("nonprofit_harness"))

    def option(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


class Agent(ABC):
    """Base class for every agent that runs on this harness.

    Subclass it, set `name`, and implement `run`. The harness owns everything
    around it: input handling, budget accounting, review, persistence, and the
    HTTP surface.
    """

    name: ClassVar[str]
    description: ClassVar[str] = ""
    version: ClassVar[str] = "0.1.0"

    #: When true, artifacts enter review instead of being released directly.
    #: Default on: in this sector an unreviewed output can reach a beneficiary.
    requires_review: ClassVar[bool] = True

    #: Per-run spend ceiling in USD. None means the deployment-wide default applies.
    budget_usd: ClassVar[float | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # ABCMeta has not computed __abstractmethods__ for cls yet at this point, so
        # "does this class define run()" is the reliable test for a concrete agent.
        if "run" in cls.__dict__ and not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__} must set a class-level `name`")

    @abstractmethod
    def run(self, ctx: RunContext) -> AgentResult:
        """Do the work and return the artifacts produced."""

    def artifact(
        self,
        kind: str,
        content: str,
        *,
        title: str = "",
        claims: list[Claim] | None = None,
        **metadata: Any,
    ) -> Artifact:
        """Build an artifact.

        Attaching `claims` opts this artifact into verification: the harness checks
        that each cited span really appears in the run's inputs before a reviewer
        ever sees it.
        """
        return Artifact(
            kind=kind,
            content=content,
            title=title,
            claims=list(claims or []),
            metadata=metadata,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "requires_review": self.requires_review,
            "budget_usd": self.budget_usd,
        }


__all__ = ["Agent", "RunContext"]
