"""Parse IATI activity XML into the results model, with the nesting intact.

The Datastore flattens an activity into parallel arrays and loses which indicator
belongs to which result, and which disaggregated slice belongs to which number. The
published XML does not. A real activity reads:

    <target value="1848">
      <dimension name="age" value="18+"/>
      <dimension name="gender" value="female"/>
    </target>

So everything the flattened path has to refuse is recoverable here, which makes this
the preferred way to read results. The flattened path remains useful for searching,
because you cannot search XML you have not fetched yet.

Uses the standard library's ElementTree, so this adds no dependency. ElementTree does
not resolve external entities and does not expand DTD-defined ones, which are the two
attacks XML parsing usually invites. A size ceiling covers the rest, since the input is
someone else's file.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from nonprofit_harness.core.errors import DataSourceError
from nonprofit_harness.results.model import (
    Baseline,
    Dimension,
    Indicator,
    Measure,
    Measurement,
    Period,
    Result,
    ResultType,
)

#: Published activity files are large, and this parses input from elsewhere.
MAX_XML_BYTES = 32 * 1024 * 1024


@dataclass(slots=True)
class XmlActivity:
    """One activity, with its results fully reconstructed."""

    iati_identifier: str
    title: str = ""
    description: str = ""
    results: list[Result] = field(default_factory=list)

    @property
    def indicators(self) -> list[Indicator]:
        return [indicator for result in self.results for indicator in result.indicators]


def parse_activities(xml: str | bytes) -> list[XmlActivity]:
    """Parse an IATI activity file, which may hold one activity or many."""
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    if len(xml) > MAX_XML_BYTES:
        size, ceiling = len(xml) // 1_048_576, MAX_XML_BYTES // 1_048_576
        raise DataSourceError(f"IATI XML is {size}MB, over the {ceiling}MB ceiling")

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DataSourceError(f"Could not parse IATI XML: {exc}") from None

    # A file is normally <iati-activities> wrapping many, but a single activity on its
    # own is common enough in fixtures and API responses to accept directly.
    activities = (
        [root] if _tag(root) == "iati-activity" else root.findall(".//iati-activity")
    )
    return [_activity(element) for element in activities]


def results_from_xml(xml: str | bytes, iati_identifier: str | None = None) -> list[Result]:
    """The results of one activity. Without an identifier, the first activity's."""
    activities = parse_activities(xml)
    if iati_identifier:
        activities = [a for a in activities if a.iati_identifier == iati_identifier]
    return activities[0].results if activities else []


def _activity(element: Any) -> XmlActivity:
    return XmlActivity(
        iati_identifier=(element.findtext("iati-identifier") or "").strip(),
        title=_narrative(element.find("title")),
        description=_narrative(element.find("description")),
        results=[_result(child) for child in element.findall("result")],
    )


def _result(element: Any) -> Result:
    return Result(
        title=_narrative(element.find("title")),
        type=ResultType.from_code(element.get("type", "1")),
        description=_narrative(element.find("description")),
        indicators=[_indicator(child) for child in element.findall("indicator")],
        metadata={"source": "iati-xml", "aggregation_status": element.get("aggregation-status")},
    )


def _indicator(element: Any) -> Indicator:
    reference = element.find("reference")
    # The standard requires @measure. An absent or unrecognised one stays UNKNOWN, since
    # assuming a count would let labels and ranks into sums and percentages.
    code = element.get("measure") or ""
    return Indicator(
        title=_narrative(element.find("title")),
        description=_narrative(element.find("description")),
        measure=Measure.from_code(code),
        # Absent means unknown rather than false. Assuming upward matches the flattened
        # path, and is the assumption that reverses a descending indicator's result, so
        # it is recorded rather than hidden.
        ascending=_bool(element.get("ascending"), default=True),
        aggregatable=_bool(element.get("aggregation-status"), default=True),
        baseline=_baseline(element.findall("baseline")),
        periods=[_period(child) for child in element.findall("period")],
        reference=reference.get("code", "") if reference is not None else "",
        metadata={
            "source": "iati-xml",
            "direction_published": element.get("ascending") is not None,
            "measure_code": code,
        },
    )


def _baseline(elements: list[Any]) -> Baseline | None:
    """The overall baseline where one is published, else the first.

    The standard allows a baseline per slice. Taking the first by position could hand a
    women-only figure to an overall result; preferring the unscoped one avoids that, and
    a scoped one that remains is refused by the arithmetic rather than applied.
    """
    baselines = [_one_baseline(element) for element in elements]
    overall = [b for b in baselines if b.scope.is_total]
    return next(iter(overall or baselines), None)


def _one_baseline(element: Any) -> Baseline:
    year = element.get("year")
    return Baseline(
        value=_number(element.get("value")),
        year=int(year) if year and year.isdigit() else None,
        iso_date=_date(element.get("iso-date")),
        dimensions=_dimensions(element),
        comment=_narrative(element.find("comment")),
        location=_location(element),
    )


def _period(element: Any) -> Period:
    start, end = element.find("period-start"), element.find("period-end")
    return Period(
        start=_date(start.get("iso-date")) if start is not None else None,
        end=_date(end.get("iso-date")) if end is not None else None,
        targets=[_measurement(m) for m in element.findall("target")],
        actuals=[_measurement(m) for m in element.findall("actual")],
    )


def _measurement(element: Any) -> Measurement:
    return Measurement(
        value=_number(element.get("value")),
        dimensions=_dimensions(element),
        location=_location(element),
        comment=_narrative(element.find("comment")),
    )


def _location(element: Any) -> str:
    location = element.find("location")
    return (location.get("ref") or "").strip() if location is not None else ""


def _dimensions(element: Any) -> tuple[Dimension, ...]:
    """The slice a measurement describes, such as age 18+ and gender female.

    This is the thing the Datastore's flattening destroys, and the reason this parser
    exists at all.
    """
    found = []
    for child in element.findall("dimension"):
        name, value = (child.get("name") or "").strip(), (child.get("value") or "").strip()
        # A publisher marking a dimension TBD has not disaggregated anything.
        if name and value and name.upper() != "TBD" and value.upper() != "TBD":
            found.append(Dimension(name=name.lower(), value=value))
    return tuple(found)


def _narrative(element: Any) -> str:
    """Join an element's narratives. IATI repeats them per language."""
    if element is None:
        return ""
    parts = [(child.text or "").strip() for child in element.findall("narrative")]
    parts = [part for part in parts if part]
    if parts:
        return "\n\n".join(parts)
    return (element.text or "").strip()


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
    return str(value).strip().lower() in {"true", "1", "yes"}


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).split("T", 1)[0])
    except ValueError:
        return None


def _tag(element: Any) -> str:
    """Element tag without any namespace, since publishers vary."""
    tag = str(element.tag)
    return tag.rsplit("}", 1)[-1]


__all__ = ["MAX_XML_BYTES", "XmlActivity", "parse_activities", "results_from_xml"]
