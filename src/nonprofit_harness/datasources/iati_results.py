"""Reconstruct indicators from a flattened IATI Datastore record.

The Datastore returns an activity as one row, so nested results are flattened into
parallel arrays. IATI's own guidance warns that this is lossy: "It is not possible to
tell from these lists which element in one field applies to an element in another
list."

That warning is load-bearing here. Confirmed against the live API, a real activity
returns `result_title_narrative` with 16 entries and `result_indicator_*` with 301.
Sixteen results, 301 indicator rows, and nothing relating them. Other activities happen
to return matching lengths, which makes the association look recoverable when it is
only coincidence.

So this reconstructs **indicators**, which are internally consistent, and refuses to
attach them to results. The arithmetic in `nonprofit_harness.results` operates on
indicators, so almost nothing analytical is lost, and what is lost is reported rather
than guessed at.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from nonprofit_harness.results.model import (
    Baseline,
    Indicator,
    Measure,
    Measurement,
    Period,
)

PREFIX = "result_indicator_"

#: Requested explicitly, because asking for everything returns whole narrative bodies
#: for every indicator and the free tier's weekly call budget is better spent elsewhere.
RESULT_FIELDS = (
    "result_type",
    "result_title_narrative",
    "result_indicator_title_narrative",
    "result_indicator_description_narrative",
    "result_indicator_measure",
    "result_indicator_ascending",
    "result_indicator_aggregation_status",
    "result_indicator_reference_code",
    "result_indicator_baseline_value",
    "result_indicator_baseline_year",
    "result_indicator_period_period_start_iso_date",
    "result_indicator_period_period_end_iso_date",
    "result_indicator_period_target_value",
    "result_indicator_period_actual_value",
)


@dataclass(slots=True)
class IatiResults:
    """What could be reconstructed, and what could not."""

    indicators: list[Indicator] = field(default_factory=list)
    #: Present on the activity but deliberately unattached. See the module docstring.
    result_titles: tuple[str, ...] = ()
    rows: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.indicators) and not self.warnings


def results_from_record(record: dict[str, Any]) -> IatiResults:
    """Rebuild indicators from one flattened activity record.

    Only fields sharing the dominant length are used. Sparse optional fields come back
    compacted rather than padded, so a shorter array does not line up with the rest and
    using it positionally would attach values to the wrong indicator.
    """
    parsed = IatiResults()

    arrays = {
        key: value
        for key, value in record.items()
        if key.startswith(PREFIX) and isinstance(value, list) and value
    }
    if not arrays:
        return parsed

    lengths = Counter(len(value) for value in arrays.values())
    rows = lengths.most_common(1)[0][0]
    parsed.rows = rows

    aligned = {key: value for key, value in arrays.items() if len(value) == rows}
    for key, value in sorted(arrays.items()):
        if len(value) != rows:
            parsed.warnings.append(
                f"{key} has {len(value)} entries against {rows} indicator rows, "
                "so it was left out rather than misaligned"
            )

    titles = aligned.get(f"{PREFIX}title_narrative")
    if not titles:
        parsed.warnings.append("no aligned indicator titles, so nothing was reconstructed")
        return parsed

    if f"{PREFIX}ascending" not in aligned:
        # Without direction, an indicator that improves downward scores backwards.
        parsed.warnings.append(
            "no aligned `ascending` field, so direction is unknown and was assumed "
            "upward. Check any indicator where a lower number is better"
        )

    result_titles = record.get("result_title_narrative")
    if result_titles:
        parsed.result_titles = tuple(dict.fromkeys(str(t) for t in result_titles))
        parsed.warnings.append(
            f"{len(parsed.result_titles)} result(s) are published but cannot be matched "
            f"to these {rows} indicator rows, so indicators are returned ungrouped"
        )

    grouped: dict[tuple, Indicator] = {}
    for position in range(rows):
        cell = {key[len(PREFIX) :]: value[position] for key, value in aligned.items()}
        identity = (
            str(cell.get("title_narrative", "")),
            str(cell.get("description_narrative", "")),
            str(cell.get("measure", "1")),
            str(cell.get("reference_code", "")),
        )

        indicator = grouped.get(identity)
        if indicator is None:
            indicator = Indicator(
                title=identity[0],
                description=identity[1],
                measure=Measure.from_code(identity[2]),
                ascending=_bool(cell.get("ascending"), default=True),
                aggregatable=_bool(cell.get("aggregation_status"), default=True),
                reference=identity[3],
                baseline=_baseline(cell),
                metadata={"source": "iati"},
            )
            grouped[identity] = indicator

        period = _period(cell)
        if period is not None:
            indicator.periods.append(period)

    parsed.indicators = list(grouped.values())
    return parsed


def _period(cell: dict[str, Any]) -> Period | None:
    start = _date(cell.get("period_period_start_iso_date"))
    end = _date(cell.get("period_period_end_iso_date"))
    target = _number(cell.get("period_target_value"))
    actual = _number(cell.get("period_actual_value"))

    if start is None and end is None and target is None and actual is None:
        return None

    return Period(
        start=start,
        end=end,
        targets=[Measurement(value=target)] if target is not None else [],
        actuals=[Measurement(value=actual)] if actual is not None else [],
    )


def _baseline(cell: dict[str, Any]) -> Baseline | None:
    value = _number(cell.get("baseline_value"))
    year = cell.get("baseline_year")
    if value is None and year is None:
        return None
    return Baseline(value=value, year=int(year) if str(year or "").isdigit() else None)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).split("T", 1)[0])
    except ValueError:
        return None


__all__ = ["RESULT_FIELDS", "IatiResults", "results_from_record"]
