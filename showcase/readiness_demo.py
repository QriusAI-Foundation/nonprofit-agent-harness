"""What the readiness scorer reports for messy answers, on the bundled demo instrument.

    python -m showcase.readiness_demo generate     # model call through the harness
    python -m showcase.readiness_demo score        # offline, through `harness score`

A demo of the demo instrument. `example_instrument()` is six made-up questions, not a
validated readiness index, and these 50 organisations are fictional. The point is to
show how the scorer behaves on answers real forms produce: duplicates, gaps, "don't
know", values off the scale, and options that do not exist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from examples._cited import parse_json

from nonprofit_harness import Agent, AgentResult, RunContext
from nonprofit_harness.core.types import Document
from nonprofit_harness.readiness import example_instrument
from showcase import harness_setup as setup

OUT = setup.HERE / "readiness"
ANSWERS = OUT / "answers"
HARNESS = Path(sys.executable).with_name("harness")

SCENARIOS = {
    "complete": "answer every question with a valid option",
    "duplicate_selection": "in p1, select the same option twice",
    "none_plus_others": "in p1, select none_of_these together with real skills",
    "all_dont_know": "answer dont_know wherever it exists, and leave the rest blank",
    "one_dimension_blank": "answer only the Data & Systems questions",
    "incomplete": "leave two or three questions out",
    "scale_off_range": "give d3 a value outside 1 to 5",
    "unknown_option": "answer one single-choice question with a value not in its options",
    "empty_values": "give one question an empty string and p1 an empty list",
    "some_dont_know": "answer dont_know on one or two questions, valid elsewhere",
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "d1": {"type": "string"},
        "d2": {"type": "string"},
        "d3": {"type": "number"},
        "p1": {"type": "array", "items": {"type": "string"}},
        "p2": {"type": "string"},
        "p3": {"type": "string"},
    },
}

SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "organisations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "profile": {"type": "string"},
                    "scenario": {"type": "string"},
                    "answers": ANSWER_SCHEMA,
                },
                "required": ["name", "profile", "scenario", "answers"],
            },
        },
    },
    "required": ["text", "organisations"],
}


class ReadinessAnswersAgent(Agent):
    name = "readiness-answers"
    description = "Writes fictional organisations' answers to a readiness questionnaire."
    version = "0.1.0"

    def run(self, ctx: RunContext) -> AgentResult:
        response = ctx.provider.generate(
            ctx.inputs[0].text,
            system=(
                "You write test data. Invent small nonprofits (fictional names, varied "
                "countries, sizes, and sectors) and fill in a questionnaire as each would, "
                "following the scenario assigned to it exactly, including its mistakes."
            ),
            json_schema=SCHEMA,
            max_output_tokens=32_000,
        )
        return AgentResult(artifacts=[self.artifact("answer-sets", response.text)])


def brief(count: int) -> Document:
    instrument = json.dumps(example_instrument().to_dict(), indent=1)
    names = list(SCENARIOS)
    lines = [
        f"Write {count} organisations. The questionnaire is below. Each organisation's "
        "scenario, in order:",
        *(
            f"{n + 1}. {names[n % len(names)]}: {SCENARIOS[names[n % len(names)]]}"
            for n in range(count)
        ),
        "",
        "Leave a question out of `answers` to show it unanswered. Questionnaire:",
        instrument,
    ]
    return Document(text="\n".join(lines), name="readiness-brief")


def generate(count: int, model: str) -> None:
    setup.require_key()
    setup.require_headroom(2.0)
    run = setup.runner(ReadinessAnswersAgent(), model).start(
        ReadinessAnswersAgent.name, org_id="showcase", inputs=[brief(count)]
    )
    setup.record("readiness", run, model)
    print(f"{run.status} ${run.usage.cost_usd:.4f} {run.error or ''}")
    payload = parse_json(run.artifacts[0].content) if run.artifacts else {}
    ANSWERS.mkdir(parents=True, exist_ok=True)
    for number, org in enumerate(payload.get("organisations") or [], start=1):
        record = {"name": org["name"], "profile": org["profile"], "scenario": org["scenario"]}
        (ANSWERS / f"{number:02d}.answers.json").write_text(
            json.dumps(org["answers"], indent=2) + "\n", encoding="utf-8"
        )
        (ANSWERS / f"{number:02d}.org.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"wrote {len(payload.get('organisations') or [])} answer sets")


def score_all() -> None:
    rows = []
    for path in sorted(ANSWERS.glob("*.answers.json")):
        org = json.loads(path.with_name(path.name.replace("answers", "org")).read_text())
        done = subprocess.run(
            [str(HARNESS), "score", str(path)], capture_output=True, text=True, check=False
        )
        if done.returncode == 0:
            result = json.loads(done.stdout)
            reported = (
                f"{result['overall']:.3f} {result['tier']}; dimensions "
                f"{len(result['dimension_scores'])}/2; excluded {result['excluded_questions']}"
                f"; unanswered {result['unanswered_questions']}"
            )
        else:
            last = (done.stderr.strip().splitlines() or ["(no output)"])[-1]
            reported = f"exit {done.returncode}: {last[:120]}"
        rows.append((path.name[:2], org["scenario"], org["name"], reported))

    by_scenario: dict[str, list[str]] = defaultdict(list)
    for _, scenario, _, reported in rows:
        by_scenario[scenario].append(reported)
    lines = [
        "# Readiness scorer on messy answers (demo instrument)",
        "",
        "A demo of the demo instrument: `example_instrument()` is not a validated index,",
        "and these organisations are fictional. Each row is `harness score <file>` as it",
        f"ran at commit {setup.git_commit()}.",
        "",
        "| # | Scenario | Organisation | What `harness score` reported |",
        "|---|---|---|---|",
        *(f"| {n} | {s} | {o} | {r} |" for n, s, o, r in rows),
        "",
    ]
    (OUT / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="showcase.readiness_demo")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--count", type=int, default=50)
    gen.add_argument("--model", default="claude-sonnet-5-5")
    sub.add_parser("score")
    args = parser.parse_args(argv)
    if args.command == "generate":
        generate(args.count, args.model)
    else:
        score_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
