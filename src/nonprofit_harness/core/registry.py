from __future__ import annotations

from nonprofit_harness.core.agent import Agent
from nonprofit_harness.core.errors import InvalidRequest, NotFound


class AgentRegistry:
    """Name to agent lookup. The API exposes whatever is registered here."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> Agent:
        if agent.name in self._agents:
            raise InvalidRequest(f"An agent named {agent.name!r} is already registered")
        self._agents[agent.name] = agent
        return agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError:
            raise NotFound(f"No agent named {name!r}") from None

    def all(self) -> list[Agent]:
        return list(self._agents.values())

    def clear(self) -> None:
        self._agents.clear()

    def __contains__(self, name: object) -> bool:
        return name in self._agents

    def __len__(self) -> int:
        return len(self._agents)


registry = AgentRegistry()

__all__ = ["AgentRegistry", "registry"]
