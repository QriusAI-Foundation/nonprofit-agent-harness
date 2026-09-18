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

`coverage` compares the slices against the undisaggregated total. Well below 1.0 means
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

## Not yet built

- Reading results straight out of the IATI adapter. The Datastore exposes result and
  indicator fields; wiring them into this model is the next step.
- Theory of change and logframe structures. Widely used, but mostly narrative rather
  than computable, so there is less here that code can check.
- SROI. The methodology is contested enough that shipping one interpretation as though
  it were arithmetic would be overclaiming.
