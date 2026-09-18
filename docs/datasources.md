# Data sources

A data source reads the sector's own open data and turns it into `Document`s. Once it
does, everything else in the harness applies unchanged: an agent consumes those
documents exactly as it would an uploaded PDF, and a claim citing them is verified
against the same text the agent saw.

## The shape

Data sources run on the **caller's** side, not inside the agent.

```python
from nonprofit_harness.datasources import IatiClient

client = IatiClient(cache={})
activities = client.search_activities(reporting_org="XM-DAC-41114", rows=5)

run = runner.start(
    "iati-portfolio",
    org_id="org_1",
    inputs=[activity.to_document() for activity in activities],
)
```

This is deliberate. An agent that could fetch its own data would be an agent that
reaches past its inputs, cannot be tested offline, and cannot have its claims checked
against a known set of sources. Keeping fetching outside preserves all three.

See [examples/iati_portfolio.py](../examples/iati_portfolio.py) for a working version.

## IATI

The International Aid Transparency Initiative is the open standard most development
and humanitarian funders publish activity data against. It is the closest thing this
sector has to a canonical, global, machine-readable dataset.

### Getting a key

Register free at [developer.iatistandard.org](https://developer.iatistandard.org),
then subscribe to a plan:

| Plan | Limits | Approval |
|---|---|---|
| Exploratory | 5 calls a minute, 100 a week | None |
| Full access | Unlimited | Requested |

Set the key in your environment. It is read from `IATI_API_KEY`.

```bash
export IATI_API_KEY=...
```

**100 calls a week is the binding constraint.** Re-running a script during development
will exhaust it quickly. Pass a cache:

```python
client = IatiClient(cache={})          # reused within one process
```

A dictionary is enough to stop a repeated query costing a second call. For anything
longer-lived, pass any mutable mapping, including one backed by disk.

### Searching

```python
client.search_activities("education")                       # free text
client.search_activities(reporting_org="XM-DAC-41114")      # by publisher
client.search_activities(country="KE", sector="11320")      # by filters
client.activity("XM-DAC-41114-PROJECT-1")                   # one, by identifier
```

The named arguments build the SOLR query for you, so you do not need to know the
field names. `query` is passed through if you do.

### What you get back

```python
activity.iati_identifier     # "XM-DAC-41114-PROJECT-1"
activity.title
activity.description
activity.reporting_org       # with .reporting_org_ref alongside
activity.recipient_countries # ("Kenya (KE)", "Uganda (UG)")
activity.sectors             # ("Secondary education (11320)",)
activity.dates
activity.raw                 # the untouched record, for anything not flattened
```

IATI fields repeat, so the API returns some of them as lists and some as single
values. The parser handles both, and missing fields become empty rather than raising.

### Why `to_text()` reads the way it does

`to_document()` renders an activity as full sentences rather than a compact record.
That is not cosmetic. Claim verification works by finding a quoted span in the
document text, so a quote can only resolve against wording that actually appears
there. A terse record would make most honest citations unverifiable.

### Errors

| Situation | What happens |
|---|---|
| No key set | `DataSourceError` before any request is made |
| Key rejected | `DataSourceError`, reported as a key problem |
| Rate limited | `DataSourceError` stating the actual quota |
| Anything else 4xx or 5xx | `DataSourceError` with the status |

### If IATI moves something

The base URL, the key header, and the requested field list are all constructor
arguments. If the API changes, a deployment can correct it in configuration rather
than waiting for a release:

```python
IatiClient(base_url="https://...", key_header="X-Custom-Key")
```

## Sources not yet written

Candidates, roughly in order of how much of the sector they cover:

- **IRS Form 990** bulk data and Tax Exempt Organization Search, for United States
  organisations. Free, no key.
- **Charity Commission register API**, for England and Wales. Free, key required.
- **NGO-DARPAN**, for India.

Contributions welcome. A data source needs to produce `Document`s, keep fetching on
the caller's side, and have tests that run offline against recorded responses.
