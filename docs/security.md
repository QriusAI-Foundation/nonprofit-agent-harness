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

**With auth on, a caller reaches only their own organisation's work.** Every route
that returns or changes a run, an artifact, or an uploaded file needs a valid session
token, and then checks that the run or file belongs to the caller's organisation. This
covers run lookup, released output, every review decision, and files named as run
inputs. A run or file in another organisation answers 404, the same as one that does
not exist, so a valid id from elsewhere is not confirmed. New runs land in the caller's
organisation; asking for another one is refused with 403. One function,
`can_access` in `api/deps.py`, makes this decision for every route.

**Sign-in proves identity, not membership.** Google tells the harness who someone is.
Which organisation they belong to comes from the harness's own user record. See
[Organisations and membership](#organisations-and-membership).

**Secrets are not echoed.** The admin configuration endpoint reports whether each
secret is set, never its value.

**Agents cannot route around any of this.** An agent receives a `RunContext` and
nothing else. The budget guard wraps the provider before the agent sees it, and the
review gate is on the other side of the interface.

## Organisations and membership

The rule:

- A user's organisation is a server-side record. Sign-in reads it and signs it into
  the session token. Sign-in never writes it from the request.
- A first sign-in creates the record in `HARNESS_DEFAULT_ORG` (`org_default` unless you
  change it). Set `HARNESS_DEFAULT_ORG=` (empty) to refuse anyone an admin has not
  enrolled. Admins can always sign in, so the first admin can enrol everyone else.
- Only an admin changes membership: `PUT /v1/admin/members/{email}` with
  `{"org_id": "...", "org_name": "..."}`. It creates the user record and the org record
  when they do not exist yet.
- `org_id` in the sign-in body is optional. If it is present and does not match the
  record, sign-in is refused with 403. It never changes the record.

**Any Google account can sign in while a default org is set.** In a deployment for more
than one organisation, either set `HARNESS_DEFAULT_ORG=` empty, or keep the default org
free of real work and treat it as a waiting room until an admin assigns the user.

**A membership change reaches a session at its next sign-in.** The token carries the
organisation it was issued with, so a user moved out of an organisation keeps access to
it until their token expires (`HARNESS_JWT_TTL_SECONDS`, 12 hours by default). Shorten
the lifetime if you need removal to take effect faster.

**Admins reach every organisation.** An address in `HARNESS_ADMIN_EMAILS` can read,
review, and release any organisation's runs and use any organisation's files, and can
create runs in any organisation by naming its `org_id`. That is deliberate: admins
support the organisations on the deployment. Admin status comes from the allowlist on
every request, never from the token alone, so editing a token cannot make an admin.
Listings (`GET /v1/runs`, `GET /v1/review/queue`) still show only the admin's own
organisation.

**With auth off there is one shared workspace.** A request with no token is anonymous
and reaches every run, in every org it names. This is what makes a local clone work in
one command, and it is why auth must be on before a URL leaves your laptop.

**Open by design, also with auth on:** `GET /healthz`, `GET /v1/agents`, the readiness
instrument and scoring (`/v1/readiness/*`, which hold no stored data), and
`/v1/webhooks/*`, which check their own signatures.

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

Runs and documents carry an organisation id. Listings filter on it and lookups by id
check it. This is application level separation, not isolation. Everything shares one database and one
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

The harness strips credentials from provider error text before raising, because on the
API key path the SDK builds request URLs containing `?key=...` and an error can quote
the URL it failed on. Both a key embedded in any URL and the configured key itself are
redacted. If you write your own provider, do the same: `scrub_secrets` in
`providers/google.py` is the reference.

## Deployment checklist

Before a URL goes to anyone outside your team:

- [ ] `HARNESS_AUTH_REQUIRED=true`, with a client id and a 32 byte or longer secret
- [ ] `HARNESS_ADMIN_EMAILS` set to real people, exact addresses
- [ ] For more than one organisation: `HARNESS_DEFAULT_ORG=` empty, or a default org
      that holds no real work
- [ ] Every user enrolled with `PUT /v1/admin/members/{email}` in the right org
- [ ] `HARNESS_JWT_TTL_SECONDS` short enough that a removed member loses access in time
- [ ] A request to `GET /v1/runs/{run_id}` with no token returns 401
- [ ] A cost ceiling set, and pricing configured so it means something
- [ ] Quota and rate limiting in front of the service
- [ ] `GET /v1/admin/config` returns an empty `warnings` array, or only the open
      default org warning, for a deployment that serves one organisation
- [ ] Firestore composite index created
- [ ] Billing alerts configured, understanding that they alert rather than stop
- [ ] `.env` is not committed anywhere
