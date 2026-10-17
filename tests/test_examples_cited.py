"""The cited examples, run offline through the real runner with the echo provider."""

from __future__ import annotations

import json
from datetime import date

import pytest
from examples._cited import parse_json
from examples.board_brief import BoardBriefAgent
from examples.funder_report import FunderReportAgent
from examples.results_narrative import ResultsNarrativeAgent, results_sheet

from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.types import Document, RunStatus
from nonprofit_harness.datasources.iati_xml import XmlActivity
from nonprofit_harness.providers.echo import EchoProvider
from nonprofit_harness.results import Baseline, Indicator, Measurement, Period, Result
from nonprofit_harness.storage.memory import memory_stores
from nonprofit_harness.verification.types import Outcome

SOURCE = Document(
    name="manual.txt",
    text=(
        "Volunteers visit every household once a week. In 2025 the programme trained "
        "240 volunteers, of whom 212 were still active after six months."
    ),
)


def _runner(agent, provider=None) -> AgentRunner:
    registry = AgentRegistry()
    registry.register(agent)
    return AgentRunner(
        registry=registry,
        stores=memory_stores(),
        provider=provider or EchoProvider(),
        config=HarnessConfig(max_tokens=None, max_calls=None),
    )


def _reply(*quotes: str) -> str:
    claims = [{"statement": f"says {q}", "quote": q, "locator": "p.1"} for q in quotes]
    return "```json\n" + json.dumps({"text": "A short brief.", "claims": claims}) + "\n```"


@pytest.mark.parametrize("agent_class", [BoardBriefAgent, FunderReportAgent])
def test_each_cited_agent_runs_offline_and_waits_for_review(agent_class):
    run = _runner(agent_class()).start(agent_class.name, org_id="o", inputs=[SOURCE])

    assert run.status == RunStatus.AWAITING_REVIEW
    assert len(run.artifacts) == 1


@pytest.mark.parametrize("agent_class", [BoardBriefAgent, FunderReportAgent])
def test_a_real_quote_verifies_and_a_swapped_number_does_not(agent_class):
    provider = EchoProvider(
        canned={
            "manual.txt": _reply(
                "trained 240 volunteers", "trained 420 volunteers, of whom 212 were still"
            )
        }
    )

    run = _runner(agent_class(), provider).start(agent_class.name, org_id="o", inputs=[SOURCE])

    outcomes = [v.outcome for v in run.artifacts[0].verification.verdicts]
    assert outcomes == [Outcome.VERIFIED, Outcome.CITATION_NOT_FOUND]
    assert "## Evidence cited" in run.artifacts[0].content


def test_an_unreadable_reply_is_an_artifact_with_no_claims_not_a_failed_run():
    provider = EchoProvider(canned={"manual.txt": "Sorry, no JSON here."})

    run = _runner(BoardBriefAgent(), provider).start("board-brief", org_id="o", inputs=[SOURCE])

    assert run.status == RunStatus.AWAITING_REVIEW
    assert run.artifacts[0].claims == []


def test_parse_json_reads_a_fenced_object():
    assert parse_json('Here:\n```json\n{"text": "x", "claims": []}\n```') == {
        "text": "x",
        "claims": [],
    }


def test_parse_json_skips_an_echoed_schema():
    reply = '{"type": "object", "properties": {}}\n\n{"text": "Brief.", "claims": []}'

    assert parse_json(reply) == {"text": "Brief.", "claims": []}


def _activity() -> XmlActivity:
    reached = Indicator(
        title="Households visited",
        baseline=Baseline(value=100, year=2023),
        periods=[
            Period(
                start=date(2024, 1, 1),
                end=date(2024, 12, 31),
                targets=[Measurement(300)],
                actuals=[Measurement(250)],
            )
        ],
    )
    unreported = Indicator(
        title="Referrals completed",
        periods=[Period(end=date(2024, 12, 31), targets=[Measurement(50)])],
    )
    return XmlActivity(
        iati_identifier="XM-TEST-1",
        title="Community health pilot",
        results=[Result(title="Access", indicators=[reached, unreported])],
    )


def test_the_results_sheet_does_the_arithmetic_before_the_model_sees_it():
    sheet = results_sheet(_activity())

    # (250 - 100) / (300 - 100), measured from the baseline rather than from zero.
    assert "Households visited: 75.0%" in sheet.text
    assert "target 50, actual none reported" in sheet.text
    assert sheet.metadata["not_calculable"] == [
        "Referrals completed: not calculable (no actual)"
    ]


def test_what_is_not_calculable_is_listed_whatever_the_model_writes():
    run = _runner(ResultsNarrativeAgent()).start(
        "results-narrative", org_id="o", inputs=[results_sheet(_activity())]
    )

    content = run.artifacts[0].content
    assert "## Not calculable from the published data" in content
    assert "Referrals completed: not calculable (no actual)" in content
