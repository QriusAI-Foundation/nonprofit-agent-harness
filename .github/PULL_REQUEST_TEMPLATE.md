## What this changes

<!-- One or two sentences. What is different afterwards, and why. -->

## Checklist

- [ ] `make lint` and `make test` pass
- [ ] Tests run offline, with no API key, no network, and no cloud account
- [ ] A guarantee that changed has a test that fails without the change
- [ ] Comments explain why, not what
- [ ] `CHANGELOG.md` updated under Unreleased, if a user would notice this

## For changes that touch the guarantees

The harness advertises a few things it will always do. If this touches any of them,
say how it still holds:

- [ ] Nothing is released without a recorded review decision
- [ ] Citation checking still costs no model call
- [ ] Budget ceilings still cannot be bypassed from inside an agent
- [ ] A fresh clone still runs with no cloud account and no optional extras
