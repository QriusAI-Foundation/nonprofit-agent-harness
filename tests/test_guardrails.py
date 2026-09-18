from __future__ import annotations

from nonprofit_harness.core.types import Document
from nonprofit_harness.guardrails.redaction import Redactor


def test_direct_identifiers_are_masked():
    text = "Contact Asha at asha@example.org or +91 98765 43210 about the grant."
    redacted, counts = Redactor().scan(text)

    assert "asha@example.org" not in redacted
    assert "98765 43210" not in redacted
    assert counts["email"] == 1
    assert counts["phone"] == 1


def test_text_without_identifiers_is_left_alone():
    text = "The programme reached twelve villages this quarter."
    redacted, counts = Redactor().scan(text)

    assert redacted == text
    assert counts == {}


def test_only_enabled_patterns_run():
    text = "asha@example.org"
    redacted, _ = Redactor(enabled={"phone"}).scan(text)

    assert redacted == text


def test_the_runner_redacts_inputs_when_configured(runner):
    runner.config.redact_inputs = True
    run = runner.start(
        "note",
        org_id="org_1",
        inputs=[Document(text="Reach me at asha@example.org", name="c.txt")],
    )

    stored = run.inputs[0]
    assert "asha@example.org" not in stored.text
    assert stored.metadata["redacted"]["email"] == 1


def test_the_runner_leaves_inputs_alone_by_default(runner):
    run = runner.start(
        "note",
        org_id="org_1",
        inputs=[Document(text="Reach me at asha@example.org", name="c.txt")],
    )

    assert "asha@example.org" in run.inputs[0].text
