"""Adapters for the sector's own open data.

A data source's job is to produce `Document`s. Once it does, everything else in the
harness applies unchanged: an agent consumes them like any other input, and a claim
citing them is verified against the same text the agent was given.
"""

from nonprofit_harness.datasources.codelists import Codelists
from nonprofit_harness.datasources.codelists import bundled as codelists
from nonprofit_harness.datasources.iati import IatiActivity, IatiClient
from nonprofit_harness.datasources.iati_results import (
    RESULT_FIELDS,
    IatiResults,
    results_from_record,
)
from nonprofit_harness.datasources.iati_xml import (
    XmlActivity,
    parse_activities,
    results_from_xml,
)

__all__ = [
    "RESULT_FIELDS",
    "Codelists",
    "IatiActivity",
    "IatiClient",
    "IatiResults",
    "XmlActivity",
    "codelists",
    "parse_activities",
    "results_from_record",
    "results_from_xml",
]
