# Security model

What this harness protects, what it does not, and what you have to add yourself. Read
this before putting an instance on a public URL.

For reporting a vulnerability, see [SECURITY.md](../SECURITY.md).

## What it protects

**Nothing releases without a decision.** Artifacts sit in `pending_review` until a
person approves them, every decision is recorded with who made it, and
`ReviewGate.release` raises rather than quietly returning a shorter list. Automatic
releases still write a review record, so an audit can always answer who released a
given artifact.

**Claims are checked against their sources.** Cited spans must appear in the run's own
inputs. A changed quantity rejects the match, so a swapped figure does not pass as an
approximate quote. This runs by default and costs nothing.

**A single run cannot run away.** Cost, token, and call ceilings apply to every run.
The guard records spend and then checks, so a run that overshoots reports what it
actually spent rather than less.

**Secrets are not echoed.** The admin configuration endpoint reports whether each
secret is set, never its value.

**Agents cannot route around any of this.** An agent receives a `RunContext` and
nothing else. The budget guard wraps the provider before the agent sees it, and the
review gate is on the other side of the interface.

## What it does not protect, and what to add

### Total spend

**The ceilings bound one run, not a total.** Ten thousand runs at two cents each
respect every ceiling and still cost two hundred dollars.

If your instance is reachable by people you do not know, you need, in rough order of
how much money they save:

1. **Authentication.** `HARNESS_AUTH_REQUIRED=false` is the default and is correct only
   for a laptop. With it off, the API is anonymously writable and points at your model
   billing account.
2. **Quota per organisation and per deployment**, daily, with a kill switch. Nothing in
   the harness implements this today.
3. **Rate limiting** on `POST /v1/runs` and `POST /v1/uploads`, per caller and per
   address.
4. **An edge layer.** A CDN or WAF in front stops scraper and scanner traffic before it
   reaches a model call. This is usually the cheapest large improvement.

Cloud billing budgets send alerts. They do not stop spend. The application level cap is
the real brake, and it is the piece you have to build.

### Redaction

`Redactor` masks common direct identifiers with regular expressions. It will miss
things. It is a reduction in exposure, not anonymisation, and not a lawful basis for
processing personal data.

### Uploads

Individual uploads are capped at 20MB. The number of uploads is not capped, and files
are not scanned for malware. Extraction parses untrusted PDF and DOCX input with
third-party libraries, so treat a public upload endpoint as a real attack surface.

### Multi-tenancy

Runs and documents carry an organisation id and listings filter on it. This is
application level separation, not isolation. Everything shares one database and one
bucket. If you need tenants who must not be able to reach each other's data under any
failure, run separate deployments.

### Prompt injection

Input documents are untrusted text that goes to a model. A document can contain
instructions aimed at your agent. The review gate limits the damage, because output
still reaches a person before it goes anywhere, but the harness does not detect or
neutralise injected instructions.

## Handling keys

Prefer **Vertex AI over an API key**. On Vertex the harness authenticates with the
service account and there is no long-lived credential to leak. The Dockerfile defaults
to it.

If you do use `GOOGLE_API_KEY`, keep it in Secret Manager or an equivalent, never in a
committed file. `.env` is gitignored.

Be aware that provider errors can carry request detail, and on the API key path a
request URL can contain the key. Anything that logs or returns a raw provider error can
therefore surface it. Scrub provider error text before logging it in your own code.

## Deployment checklist

Before a URL goes to anyone outside your team:

- [ ] `HARNESS_AUTH_REQUIRED=true`, with a client id and a 32 byte or longer secret
- [ ] `HARNESS_ADMIN_EMAILS` set to real people, exact addresses
- [ ] A cost ceiling set, and pricing configured so it means something
- [ ] Quota and rate limiting in front of the service
- [ ] `GET /v1/admin/config` returns an empty `warnings` array
- [ ] Firestore composite index created
- [ ] Billing alerts configured, understanding that they alert rather than stop
- [ ] `.env` is not committed anywhere
