"""Results and indicators: the sector's own model of whether something worked.

Structured to match the IATI Standard's `result` element rather than invented here, so
data read from IATI maps across without translation and an organisation not yet
publishing ends up with a shape it could publish.

The calculations are deterministic and cost nothing to run. What they mostly do is
refuse to be silently wrong: about direction, about which measures can be added, and
about whether a breakdown accounts for the whole.
"""

from nonprofit_harness.results.analysis import (
    Achievement,
    Basis,
    NotCalculable,
    Total,
    Utilisation,
    achievement,
    achievements,
    coverage,
    dimension_totals,
    disaggregate,
    total_actual,
    utilisation,
)
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

__all__ = [
    "Achievement",
    "Baseline",
    "Basis",
    "Dimension",
    "Indicator",
    "Measure",
    "Measurement",
    "NotCalculable",
    "Period",
    "Result",
    "ResultType",
    "Total",
    "Utilisation",
    "achievement",
    "achievements",
    "coverage",
    "dimension_totals",
    "disaggregate",
    "total_actual",
    "utilisation",
]
