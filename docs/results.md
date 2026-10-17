# Results and indicators

Whether a programme did what it set out to do, and the arithmetic for saying so.

These are deterministic. No model calls, nothing to configure, nothing to spend. They
are the sector's equivalent of the valuation operators a finance toolkit ships: the
domain's own calculations, written down once so that every agent built on this harness
does them the same way.

## Why this shape

Not invented here. The [IATI Standard](https://iatistandard.org/) already specifies a
results model, and publishers report against it. The structure mirrors the standard's
`result` element, so data read from IATI maps across without translation, and an
organisation not yet publishing ends up with a shape it could publish later.

```
Result                what you set out to change (output, outcome, impact)
  Indicator           what you measure it by
    Baseline          where things stood before
    Period            a window
      target          what you aimed for
      actual          what happened
        Dimension     a slice, such as sex=female
```

## The three things that go wrong

Each of these is a way of producing a confident number that is simply incorrect. All
three are prevented here rather than documented as caveats.

### Direction

An indicator has a direction. Clinics built improves upward. Cases of a disease
improves downward. The standard records this as `ascending`.

```python
Indicator(title="Disease cases", ascending=False, periods=[...])  # target 50, actual 40
```

Forty against a target of fifty is a **success**. A plain actual-over-target ratio
reports 80% and reads as a shortfall, which is the wrong answer written confidently.
Here it reports 125%.

### Baselines

Progress is measured from where you started, not from zero:

```
(actual - baseline) / (target - baseline)
```

An enrolment rate moving 60 to 70 against a target of 80 is **50%** of the intended
change. Measuring from zero gives 87.5%, which credits the programme with the sixty
percent that was already true before it began.

This formula also needs no special case for direction. A descending indicator has a
target below its baseline, so both differences turn negative together and cancel.

### What may be added

Only counts add up. Summing percentages is meaningless, and nominal and ordinal codes
are labels that happen to look like numbers. The standard also carries
`aggregation-status`, the publisher's own statement about whether their values may be
summed at all.

```python
total_actual(indicators)
# Total(value=8.0, counted=1,
#       refused=['Attendance: percentage values do not add up'])
```

It refuses rather than filtering quietly. A total that silently dropped three of five
indicators is more dangerous than no total, because it looks complete.

## Scope: which population a figure describes

Every target, actual and baseline describes a population. Its **scope** is its
dimensions (such as `sex=female`) and its location (an IATI location `ref`). An empty
scope is the whole programme. Two figures may only be compared when their scopes are
equal.

**A headline total must be identifiable as a total.** It has no dimensions and no
location. IATI has no explicit "total" marker on a target or actual; the bundled
codelists and the standard's `aggregation-status` describe whether values *may* be
summed, not which one is the whole. So the absence of dimensions and location is the
only signal, and it is the one used.

- A figure for one district is a slice. Two districts with no dimensions do not make
  the first district the programme's actual.
- Selection is by scope, never by position. Reordering targets or actuals never changes
  which population is reported. Two overall figures that disagree are refused
  (`CONFLICTING_TOTALS`) rather than resolved by taking the first.
- No overall figure gives `NotCalculable.NO_TOTAL`, and `detail` names the scopes that
  were found, for example
  `the actual is reported only for location KE-01; location KE-02, with no overall figure`.
- Because target and actual are both overall, they always describe the same
  population. The baseline is the one figure that can still describe another. A
  women-only baseline of 60 against an overall target of 100 and actual of 80 would
  report 50%, comparing two different groups. It is refused with
  `BASELINE_SCOPE_MISMATCH`:
  `the baseline is for sex=female, but the target and actual are overall`.
  The XML parser prefers the overall baseline when a publisher sends one per slice.

## Which measures permit which arithmetic

| Measure       | Achievement ratio | Sum in `total_actual` | Refusal reason      |
|---------------|-------------------|-----------------------|---------------------|
| `UNIT`        | yes               | yes                   |                     |
| `PERCENTAGE`  | yes               | no                    |                     |
| `ORDINAL`     | no                | no                    | `ORDINAL_SCALE`     |
| `NOMINAL`     | no                | no                    | `NOMINAL_LABELS`    |
| `QUALITATIVE` | no                | no                    | `NOT_NUMERIC`       |
| `UNKNOWN`     | no                | no                    | `UNKNOWN_MEASURE`   |

- **Nominal** values are category labels. Category 2 against category 4 is not 50%.
- **Ordinal** values are ranks with no fixed distance between them. Moving from rank 2
  to rank 3 is not a known fraction of moving from 2 to 4, so no percentage of the way
  to target is stated. Comparing ranks (did the rating reach the target?) is legitimate,
  and is left to the caller, who knows the scale.
- **Unknown** is not an IATI code. A publisher's code that is not recognised, or an
  absent one, parses as `UNKNOWN` with the raw code kept in
  `indicator.metadata["measure_code"]`. It is never assumed to be a count. The
  flattened path also adds a warning.

Every refusal sets `reason` and a sentence in `detail`, which `explain()` and
`to_dict()` include.

## Using it

```python
from nonprofit_harness.results import Indicator, Baseline, achievement

got = achievement(indicator)

got.percent      # 50.0
got.met          # False
got.basis        # Basis.FROM_BASELINE, so you can see how it was worked out
got.explain()    # "Enrolment: 50.0% (70 from a baseline of 60 towards 80)"
```

Nothing returns a bare number. Every figure carries how it was reached, because a
number in a funder report has to be explicable to the person who signs it.

When a figure cannot be produced, it says so rather than guessing:

```python
achievement(qualitative_indicator).reason   # NotCalculable.NOT_NUMERIC
achievement(indicator_with_no_actual).reason # NotCalculable.NO_ACTUAL
```

A missing actual is never treated as zero.

## Disaggregation

```python
dimension_totals(measurements, "sex")   # {"female": 60, "male": 40}
coverage(measurements, "sex")           # 1.0
```

`coverage` compares the slices against the overall total (no dimensions, no location). Well below 1.0 means
the breakdown is partial. Above 1.0 means the slices overlap, or one of them is itself
a total. Either is worth seeing before a breakdown goes into a report.

Slices are never mixed with the headline figure. A period reporting only slices has no
stated total, and adding them up would assume they are exhaustive and do not overlap.
Neither is guaranteed, so the total comes back as `None`.

## Budget

```python
utilisation(spent=75_000, budget=100_000, delivered=500, currency="USD")
# "USD 75000 of USD 100000 (75.0%), USD 150 per unit delivered"
```

Unit cost is omitted rather than reported as infinity when nothing was delivered, since
"infinite cost per beneficiary" is not a finding anyone can act on.

## Reading results from IATI

There are two paths, and they are not equivalent. **Prefer the XML one.**

```python
from nonprofit_harness.datasources import IatiClient

client = IatiClient(cache={})
results = client.results("NL-KVK-41236410-6970")   # XML: full fidelity
```

The XML keeps the nesting. Results hold their own indicators, and every measurement
keeps the slice it describes:

```python
period = results[0].indicators[0].periods[0]
dimension_totals(period.actuals, "gender")   # {'female': 2965.0, 'male': 2049.0}
dimension_totals(period.actuals, "age")      # {'18+': 2692.0, 'under 18': 2322.0}
```

That is the same activity for which the flattened path below can recover no values at
all. One call either way, so there is rarely a reason to choose the lossy one.

Parsing uses the standard library, so it adds no dependency. External entities are not
resolved and DTD entities are not expanded, which are the two attacks XML parsing
usually invites, and a size ceiling covers the rest, since the input is someone else's
file.

### The flattened path, and why it still exists

```python
parsed = client.indicators("US-EIN-521257057-WRI-23-27")
parsed.indicators      # rebuilt, ready for achievement()
parsed.result_titles   # published, but deliberately unattached
parsed.warnings        # read these before reporting any number
```

You cannot search XML you have not fetched, so searching still goes through the
flattened collection. Use it to find activities, then read the ones you care about as
XML.

**Read the warnings.** The Datastore flattens a nested activity into parallel arrays,
and IATI's guidance is explicit that this is lossy: you cannot tell which element of
one list belongs to which element of another.

That is not theoretical. A real activity returns `result_title_narrative` with 16
entries and `result_indicator_*` with 301. Sixteen results, 301 indicator rows, nothing
relating them. Other activities happen to return matching lengths, which makes the
association look recoverable when it is only coincidence.

So indicators are reconstructed, because their fields are internally consistent, and
results are reported without being attached to them. Since the arithmetic operates on
indicators, almost nothing analytical is lost.

Three other warnings to watch for:

- **A field was dropped for length mismatch.** Sparse optional fields come back
  compacted rather than padded, so using them positionally would attach a comment or a
  value to the wrong indicator.
- **Direction is unknown.** Where `ascending` is not published, it is assumed upward
  and says so. Check any indicator where a lower number is better, because that
  assumption reverses its result.
- **The activity disaggregates.** See below.

### Disaggregation is reported, never attached

```python
parsed.disaggregated      # True
parsed.dimensions_used    # {"sex": ("female", "male"), "age": ("under 18", "18+")}
```

You get *which* breakdowns a programme reports by, and not which number belongs to
which slice. That distinction is forced by the data.

Checked against three publishers reporting genuine sex and age breakdowns: 26 values
against 52 dimensions, 8 against 28, and 16 against 21. The number of dimensions per
measurement varies inside a single activity, so a flat array of 21 dimensions and 16
values says nothing about which belong together. The clean 2:1 case is the dangerous
one, because zipping would look correct there and mis-assign everywhere else.

**A heavily disaggregated activity may yield no values at all.** One real activity has
7 indicator rows and 26 reported actuals, because each indicator carries several
disaggregated measurements per period. Those 26 cannot be matched to the 7, so they are
dropped and the warning says so. Titles and structure survive; the numbers do not.

Knowing the breakdown exists is still worth having. That a programme reports by sex and
age is real information, and `disaggregated` being false is a finding too: a programme
reporting only totals cannot say who it reached.

All of which is why `client.results()` exists. The published XML keeps every slice
attached to its number, so none of the above applies there.

### Using disaggregation you hold yourself

None of this limits the model. If your own system knows which slice a number belongs
to, build `Measurement`s with their dimensions and the arithmetic works:

```python
dimension_totals(measurements, "sex")   # {"female": 60, "male": 40}
coverage(measurements, "sex")           # 1.0
```

The limitation is IATI's flattening, not the harness.

## Not yet built

- Theory of change and logframe structures. Widely used, but mostly narrative rather
  than computable, so there is less here that code can check.
- SROI. The methodology is contested enough that shipping one interpretation as though
  it were arithmetic would be overclaiming.
