from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.registry import AgentRegistry
from nonprofit_harness.core.runner import AgentRunner
from nonprofit_harness.core.types import Document
from nonprofit_harness.documents import extract
from nonprofit_harness.providers import load_provider
from nonprofit_harness.readiness import example_instrument, score
from nonprofit_harness.readiness.instrument import Instrument
from nonprofit_harness.storage import load_stores

_MEDIA_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description="Nonprofit Agent Harness")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="Run an agent over one or more files")
    run_cmd.add_argument("agent", help="Import path, e.g. examples.summarizer:SummarizerAgent")
    run_cmd.add_argument("files", nargs="+", type=Path)
    run_cmd.add_argument("--org", default="org_local")
    run_cmd.add_argument("--option", action="append", default=[], metavar="KEY=VALUE")

    score_cmd = sub.add_parser("score", help="Score readiness answers against an instrument")
    score_cmd.add_argument("answers", type=Path, help="JSON file of question_id to answer")
    score_cmd.add_argument("--instrument", type=Path, default=None)

    check_cmd = sub.add_parser("check", help="Report the effective configuration")
    check_cmd.set_defaults(func=None)

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    if args.command == "score":
        return _score(args)
    return _check()


def _import_agent(reference: str):
    module_name, _, attribute = reference.partition(":")
    if not attribute:
        raise ValueError("Agent must be given as module:ClassName")
    # Agents live in the user's own project, not in this package, so the directory
    # they ran the command from has to be importable.
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    return getattr(importlib.import_module(module_name), attribute)


def _run(args) -> int:
    try:
        agent_class = _import_agent(args.agent)
    except (ValueError, ImportError, AttributeError) as exc:
        print(f"Could not load agent {args.agent!r}: {exc}", file=sys.stderr)
        return 2

    config = HarnessConfig.from_env()
    registry = AgentRegistry()
    registry.register(agent_class())

    documents: list[Document] = []
    for path in args.files:
        media_type = _MEDIA_TYPES.get(path.suffix.lower(), "text/plain")
        documents.append(extract(path.read_bytes(), media_type=media_type, name=path.name))

    options = dict(item.split("=", 1) for item in args.option if "=" in item)
    runner = AgentRunner(
        registry=registry,
        stores=load_stores(config.storage),
        provider=load_provider(config.provider),
        config=config,
    )
    run = runner.start(agent_class.name, org_id=args.org, inputs=documents, options=options)

    print(f"run {run.id}: {run.status}")
    if run.error:
        print(f"error: {run.error}", file=sys.stderr)
        return 1
    print(
        f"usage: {run.usage.calls} calls, "
        f"{run.usage.input_tokens + run.usage.output_tokens} tokens, "
        f"${run.usage.cost_usd:.4f}"
    )
    for artifact in run.artifacts:
        print(f"\n--- {artifact.kind} [{artifact.status}] {artifact.title} ---")
        print(artifact.content)
    if run.pending_review:
        print(f"\n{len(run.pending_review)} artifact(s) awaiting human review.")
    return 0


def _score(args) -> int:
    instrument = (
        Instrument.from_json(args.instrument) if args.instrument else example_instrument()
    )
    answers = json.loads(args.answers.read_text(encoding="utf-8"))
    print(json.dumps(score(instrument, answers).to_dict(), indent=2))
    return 0


def _check() -> int:
    config = HarnessConfig.from_env()
    problems = config.validate()
    print(f"provider: {config.provider}")
    print(f"storage:  {config.storage}")
    print(
        "budget:   "
        f"cost={config.max_cost_usd} tokens={config.max_tokens} calls={config.max_calls}"
    )
    print(f"auth:     required={config.auth_required}")
    if problems:
        print("\nwarnings:")
        for problem in problems:
            print(f"  - {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
