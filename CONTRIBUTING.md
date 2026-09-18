# Contributing

Thanks for considering it. This project is most useful when it is shaped by people
running agents in real nonprofit settings, so field feedback is as welcome as code.

## Getting set up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,documents]"
make test
```

The test suite runs offline. If a change makes tests need a network call, an API key, or
a cloud account, that is a design problem with the change, not with the tests.

## Before opening a pull request

```bash
make lint
make test
```

## What we are looking for

- Provider adapters for models other than Gemini.
- Storage adapters beyond in-memory and GCP.
- Real readiness instruments, or improvements to the scoring engine.
- Documentation written from the perspective of someone deploying this with no platform
  team behind them.

## What belongs somewhere else

- Orchestration DSLs, agent graphs, and routing layers. Use a framework for that and run
  it inside your `run` method.
- Anything that makes a first run require a cloud account.
- Specific agents. This repo is the harness. Your agent lives in your repo.

## Code conventions

- Comments explain *why*, not *what*. If a line needs a comment to say what it does,
  rename something instead.
- Every guarantee the harness advertises should have a test that fails when it breaks.
- Prefer a protocol with an in-process default over a hard dependency.

## Licensing of contributions

Contributions are accepted under the [Apache License 2.0](LICENSE), the same terms the
project ships under.
