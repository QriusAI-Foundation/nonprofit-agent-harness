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

**A bare term is expanded, because the Datastore rejects an unqualified query.** Its
SOLR core declares no default search field, so `q=education` returns HTTP 400 with
"no field name specified in query and no default specified". `search_activities("education")`
therefore sends `(title_narrative:(education) OR description_narrative:(education))`.
Anything you write containing a colon is treated as deliberate SOLR syntax and passed
through untouched. Change which fields a plain term searches with `text_fields=`.

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

### What real published data looks like

Worth knowing before you build on this, because live records are messier than the
standard suggests:

- **Narratives are often missing.** Many publishers send `sector_code` and
  `recipient_country_code` with no matching narrative. The bundled codelists fill those
  in, so you get `Primary education (11220)` rather than `11220`. See below.
- **Codes repeat.** An activity can report the same sector against several
  vocabularies, so the raw list contains duplicates. They are deduplicated.
- **Dates arrive as timestamps, several times over.** An activity reports a date per
  ActivityDateType, so `activity_date_iso_date` can hold the same day four times.
  Dates are trimmed to days, labelled with their type, and deduplicated, turning eight
  meaningless entries into `planned start 2019-01-01, actual end 2019-12-31`.

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

### Indicators and results

Two paths, and they are not equivalent.

```python
results = client.results("XM-DAC-41114-PROJECT-1")     # XML, full fidelity
parsed  = client.indicators("XM-DAC-41114-PROJECT-1")  # flattened, lossy
```

`results()` reads the activity's published XML, which keeps results grouped with their
indicators and every disaggregated slice attached to its number. `indicators()` reads
the flattened rows, which lose both and say so in `parsed.warnings`. Both cost one
call, so prefer the XML. See [results.md](results.md).

### Codes become readable

Published data is full of codes. Without resolution an activity reaches an agent
saying `Sectors: 11220` and `Recipient countries: PS`, which is precise and useless.

```
Recipient countries: Palestine, State of (PS)
Sectors: Primary education (11220)
Activity status: Closed (4)
```

The lists are **bundled, not fetched**, so this needs no network, no key, and none of
the weekly call budget. Sector, Country, ActivityStatus, Region and OrganisationType
ship with the package, 631 entries in about 22KB.

Three rules govern how a name is chosen:

- **The publisher's own narrative always wins.** It is what the organisation chose to
  call the thing. Codelists are a fallback for the common case of a code with no
  narrative at all.
- **The code is kept alongside the name**, as `Name (code)`, because the code is what
  anyone cross-referencing the published data will search for.
- **An unresolved code is passed through bare.** Better a number than a wrong name, and
  better than dropping it.

### A code only means something inside its vocabulary

IATI lets a publisher report sectors against their own numbering rather than the OECD
DAC list. Their code `11220` means whatever they say it means, so resolving it against
the DAC list would attach a real and wrong name to it.

So `sector_vocabulary` is requested alongside the codes, and a sector is only resolved
where the vocabulary is the DAC one or is absent, which the standard treats as the
default. Where vocabularies are published but cannot be matched to their codes, nothing
is resolved.

### Keeping them current

Bundled data goes stale. The generated file records its source and the date it was
taken, and `bundled().fetched` exposes that at runtime.

```bash
python scripts/refresh_codelists.py
```

Refetches from [Code for IATI](https://codelists.codeforiati.org/) and rewrites the
bundled file. Only the code and name are kept; the upstream Sector list is 120KB,
almost all of it descriptions nothing here reads.

## Sources not yet written

Candidates, roughly in order of how much of the sector they cover:

- **IRS Form 990** bulk data and Tax Exempt Organization Search, for United States
  organisations. Free, no key.
- **Charity Commission register API**, for England and Wales. Free, key required.
- **NGO-DARPAN**, for India.

Contributions welcome. A data source needs to produce `Document`s, keep fetching on
the caller's side, and have tests that run offline against recorded responses.
