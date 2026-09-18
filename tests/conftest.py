from __future__ import annotations

import pytest

from nonprofit_harness import Agent, AgentResult, RunContext
from nonprofit_harness.api.app import create_app
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.types import Document
from nonprofit_harness.providers.echo import EchoProvider
from nonprofit_harness.review.gate import ReviewGate
from nonprofit_harness.storage.memory import memory_stores


class NoteAgent(Agent):
    name = "note"
    description = "Writes one note per input document."

    def run(self, ctx: RunContext) -> AgentResult:
        artifacts = []
        for document in ctx.inputs:
            response = ctx.provider.generate(f"Note on {document.name}: {document.text}")
            artifacts.append(
                self.artifact("note", response.text, title=f"Note on {document.name}")
            )
        return AgentResult(artifacts=artifacts, summary=f"{len(artifacts)} note(s)")


class OpenAgent(NoteAgent):
    name = "open"
    description = "Releases without review."
    requires_review = False


class ChattyAgent(Agent):
    name = "chatty"
    description = "Calls the model many times, to exercise budget ceilings."

    def run(self, ctx: RunContext) -> AgentResult:
        for index in range(20):
            ctx.provider.generate(f"call {index}")
        return AgentResult(artifacts=[self.artifact("noop", "done")])


class BrokenAgent(Agent):
    name = "broken"
    description = "Always raises."

    def run(self, ctx: RunContext) -> AgentResult:
        raise ValueError("this agent is broken on purpose")


@pytest.fixture
def config() -> HarnessConfig:
    return HarnessConfig(provider="echo", storage="memory", max_tokens=None, max_calls=None)


@pytest.fixture
def registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(NoteAgent())
    reg.register(OpenAgent())
    reg.register(ChattyAgent())
    reg.register(BrokenAgent())
    return reg


@pytest.fixture
def stores():
    return memory_stores()


@pytest.fixture
def provider() -> EchoProvider:
    return EchoProvider()


@pytest.fixture
def runner(registry, stores, provider, config) -> AgentRunner:
    return AgentRunner(
        registry=registry,
        stores=stores,
        provider=provider,
        config=config,
        gate=ReviewGate(stores.runs),
    )


@pytest.fixture
def documents() -> list[Document]:
    return [
        Document(text="Annual report body text.", name="annual-report.txt"),
        Document(text="Second document body.", name="notes.txt"),
    ]


@pytest.fixture
def client(registry, stores, provider, config):
    from fastapi.testclient import TestClient

    app = create_app(config=config, registry=registry, stores=stores, provider=provider)
    return TestClient(app)
