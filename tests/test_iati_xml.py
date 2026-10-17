"""Parsing IATI activity XML, where the nesting the Datastore destroys survives.

The fixture mirrors a real published activity: two dimensions per measurement, no
undisaggregated total, and `ascending` absent.
"""

from __future__ import annotations

from datetime import date

import pytest

from nonprofit_harness.core.errors import DataSourceError
from nonprofit_harness.datasources.iati_xml import (
    MAX_XML_BYTES,
    parse_activities,
    results_from_xml,
)
from nonprofit_harness.results import (
    Measure,
    NotCalculable,
    ResultType,
    achievement,
    coverage,
    dimension_totals,
)

REAL = """<?xml version="1.0" encoding="UTF-8"?>
<iati-activities version="2.03">
 <iati-activity default-currency="EUR">
  <iati-identifier>NL-KVK-41236410-6970</iati-identifier>
  <title><narrative>Humanitarian response</narrative></title>
  <description><narrative>Cash and protection programming.</narrative></description>
  <result type="1" aggregation-status="1">
   <title><narrative>Distribution of MPC grants</narrative></title>
   <indicator measure="1">
    <title><narrative>People benefitting from grants</narrative></title>
    <baseline year="2018" iso-date="2018-01-01" value="0"/>
    <period>
     <period-start iso-date="2018-01-01"/>
     <period-end iso-date="2018-12-31"/>
     <target value="1050">
      <dimension name="age" value="18+"/>
      <dimension name="gender" value="female"/>
     </target>
     <target value="700">
      <dimension name="age" value="18+"/>
      <dimension name="gender" value="male"/>
     </target>
     <actual value="1848">
      <dimension name="age" value="18+"/>
      <dimension name="gender" value="female"/>
     </actual>
     <actual value="844">
      <dimension name="age" value="18+"/>
      <dimension name="gender" value="male"/>
     </actual>
    </period>
   </indicator>
  </result>
  <result type="2">
   <title><narrative>Protection outcomes</narrative></title>
   <indicator measure="1" ascending="0" aggregation-status="0">
    <title><narrative>Reported incidents</narrative></title>
    <reference vocabulary="99" code="P1"/>
    <baseline year="2018" value="400"/>
    <period>
     <period-end iso-date="2018-12-31"/>
     <target value="200"/>
     <actual value="300"/>
    </period>
   </indicator>
  </result>
 </iati-activity>
</iati-activities>
"""


# --- the nesting --------------------------------------------------------------------


def test_results_keep_their_indicators():
    """The grouping the flattened path has to refuse."""
    results = results_from_xml(REAL)

    assert [r.title for r in results] == [
        "Distribution of MPC grants",
        "Protection outcomes",
    ]
    assert all(len(r.indicators) == 1 for r in results)


def test_result_types_are_read():
    results = results_from_xml(REAL)

    assert results[0].type is ResultType.OUTPUT
    assert results[1].type is ResultType.OUTCOME


def test_a_measurement_keeps_the_slice_it_describes():
    """The whole reason this parser exists."""
    period = results_from_xml(REAL)[0].indicators[0].periods[0]

    female = next(m for m in period.actuals if m.matches(gender="female"))
    assert female.value == 1848
    assert female.matches(age="18+", gender="female")


def test_the_disaggregated_numbers_can_be_totalled():
    period = results_from_xml(REAL)[0].indicators[0].periods[0]

    assert dimension_totals(period.actuals, "gender") == {"female": 1848, "male": 844}
    assert dimension_totals(period.targets, "gender") == {"female": 1050, "male": 700}


def test_no_headline_is_invented_from_slices():
    """This activity publishes no undisaggregated total, so there is not one."""
    period = results_from_xml(REAL)[0].indicators[0].periods[0]

    assert period.actual is None
    assert coverage(period.actuals, "gender") is None


# --- indicator attributes -----------------------------------------------------------


def test_direction_is_read_when_published():
    reported = results_from_xml(REAL)[1].indicators[0]

    assert reported.ascending is False
    assert reported.metadata["direction_published"] is True


def test_absent_direction_is_assumed_upward_and_recorded_as_assumed():
    grants = results_from_xml(REAL)[0].indicators[0]

    assert grants.ascending is True
    assert grants.metadata["direction_published"] is False


def test_the_aggregation_flag_is_honoured():
    assert results_from_xml(REAL)[0].indicators[0].aggregatable is True
    assert results_from_xml(REAL)[1].indicators[0].aggregatable is False


def test_baselines_and_references_are_read():
    grants = results_from_xml(REAL)[0].indicators[0]
    reported = results_from_xml(REAL)[1].indicators[0]

    assert grants.baseline.value == 0
    assert grants.baseline.year == 2018
    assert grants.baseline.iso_date == date(2018, 1, 1)
    assert reported.reference == "P1"


def test_periods_are_typed():
    period = results_from_xml(REAL)[0].indicators[0].periods[0]

    assert period.start == date(2018, 1, 1)
    assert period.end == date(2018, 12, 31)


def test_the_parsed_indicators_compute_correctly():
    """Descending, baseline 400, target 200, actual 300. Halfway."""
    reported = results_from_xml(REAL)[1].indicators[0]

    assert achievement(reported).percent == 50.0


# --- activities ---------------------------------------------------------------------


def test_the_activity_carries_its_own_identity():
    activity = parse_activities(REAL)[0]

    assert activity.iati_identifier == "NL-KVK-41236410-6970"
    assert activity.title == "Humanitarian response"
    assert len(activity.indicators) == 2


def test_a_file_of_several_activities_parses():
    two = REAL.replace("</iati-activities>", "") + """
 <iati-activity>
  <iati-identifier>XX-2</iati-identifier>
  <title><narrative>Second</narrative></title>
 </iati-activity>
</iati-activities>"""

    activities = parse_activities(two)

    assert [a.iati_identifier for a in activities] == ["NL-KVK-41236410-6970", "XX-2"]


def test_results_can_be_selected_by_identifier():
    two = REAL.replace("</iati-activities>", "") + """
 <iati-activity><iati-identifier>XX-2</iati-identifier></iati-activity>
</iati-activities>"""

    assert results_from_xml(two, "XX-2") == []
    assert len(results_from_xml(two, "NL-KVK-41236410-6970")) == 2


def test_a_bare_activity_element_is_accepted():
    bare = REAL.split("<iati-activities version=\"2.03\">")[1].rsplit("</iati-activities>", 1)[0]

    assert parse_activities(f"<?xml version='1.0'?>{bare}")[0].iati_identifier


# --- robustness ---------------------------------------------------------------------


def test_malformed_xml_is_a_clear_error():
    with pytest.raises(DataSourceError, match="Could not parse"):
        parse_activities("<iati-activities><unclosed>")


def test_an_oversized_document_is_refused_before_parsing():
    with pytest.raises(DataSourceError, match="ceiling"):
        parse_activities(b"<a/>" + b" " * (MAX_XML_BYTES + 1))


def test_an_activity_with_no_results_yields_none():
    assert parse_activities(
        "<iati-activities><iati-activity>"
        "<iati-identifier>X</iati-identifier></iati-activity></iati-activities>"
    )[0].results == []


def test_an_unparseable_value_becomes_absent_rather_than_zero():
    xml = """<iati-activities><iati-activity><iati-identifier>X</iati-identifier>
      <result type="1"><indicator measure="1"><period>
        <actual value="n/a"/></period></indicator></result>
      </iati-activity></iati-activities>"""

    assert results_from_xml(xml)[0].indicators[0].periods[0].actuals[0].value is None


def test_placeholder_dimensions_are_not_treated_as_a_breakdown():
    xml = """<iati-activities><iati-activity><iati-identifier>X</iati-identifier>
      <result type="1"><indicator measure="1"><period>
        <actual value="5"><dimension name="TBD" value="TBD"/></actual>
      </period></indicator></result></iati-activity></iati-activities>"""

    assert results_from_xml(xml)[0].indicators[0].periods[0].actuals[0].dimensions == ()


def test_dimension_names_are_normalised():
    xml = """<iati-activities><iati-activity><iati-identifier>X</iati-identifier>
      <result type="1"><indicator measure="1"><period>
        <actual value="5"><dimension name="Gender" value="Female"/></actual>
      </period></indicator></result></iati-activity></iati-activities>"""

    measurement = results_from_xml(xml)[0].indicators[0].periods[0].actuals[0]

    assert measurement.matches(gender="Female")


def test_qualitative_indicators_survive_without_values():
    xml = """<iati-activities><iati-activity><iati-identifier>X</iati-identifier>
      <result type="1"><indicator measure="5">
        <title><narrative>Perception</narrative></title>
        <period><actual><comment><narrative>Improved</narrative></comment></actual></period>
      </indicator></result></iati-activity></iati-activities>"""

    indicator = results_from_xml(xml)[0].indicators[0]

    assert indicator.measure is Measure.QUALITATIVE
    assert indicator.periods[0].actuals[0].comment == "Improved"
    assert achievement(indicator).ratio is None


def test_repeated_narratives_are_joined():
    xml = """<iati-activities><iati-activity><iati-identifier>X</iati-identifier>
      <title><narrative xml:lang="en">English</narrative>
             <narrative xml:lang="fr">Francais</narrative></title>
      </iati-activity></iati-activities>"""

    assert parse_activities(xml)[0].title == "English\n\nFrancais"


# --- scope and measure (audit F09, F10, F11) ---------------------------------------


def _one_indicator(body: str, measure: str = 'measure="1"'):
    xml = f"""<iati-activities><iati-activity><iati-identifier>X</iati-identifier>
      <result type="1"><indicator {measure}>
        <title><narrative>Wells</narrative></title>{body}
      </indicator></result></iati-activity></iati-activities>"""
    return results_from_xml(xml)[0].indicators[0]


def test_location_only_actuals_parse_as_slices_not_a_total():
    indicator = _one_indicator(
        """<period><period-end iso-date="2026-12-31"/><target value="100"/>
           <actual value="30"><location ref="KE-01"/></actual>
           <actual value="50"><location ref="KE-02"/></actual></period>"""
    )

    got = achievement(indicator)

    assert indicator.periods[0].actual is None
    assert got.reason is NotCalculable.NO_TOTAL
    assert "location KE-01; location KE-02" in got.detail


def test_the_overall_baseline_is_preferred_over_a_slice_published_first():
    indicator = _one_indicator(
        """<baseline value="60"><dimension name="sex" value="female"/></baseline>
           <baseline value="50"/>
           <period><target value="100"/><actual value="75"/></period>"""
    )

    assert indicator.baseline.value == 50
    assert achievement(indicator).percent == 50.0


def test_a_baseline_published_only_for_one_location_is_refused():
    indicator = _one_indicator(
        """<baseline value="60"><location ref="KE-01"/></baseline>
           <period><target value="100"/><actual value="80"/></period>"""
    )

    got = achievement(indicator)

    assert indicator.baseline.location == "KE-01"
    assert got.reason is NotCalculable.BASELINE_SCOPE_MISMATCH


@pytest.mark.parametrize("measure", ['measure="9"', ""])
def test_parsing_preserves_an_unknown_measure(measure):
    """Absent or unrecognised is kept as doubt, not resolved into a count."""
    indicator = _one_indicator(
        "<period><target value='4'/><actual value='2'/></period>", measure
    )

    assert indicator.measure is Measure.UNKNOWN
    assert indicator.metadata["measure_code"] == ("9" if measure else "")
    assert achievement(indicator).reason is NotCalculable.UNKNOWN_MEASURE


def test_a_nominal_indicator_parses_and_is_not_scored():
    indicator = _one_indicator(
        "<period><target value='4'/><actual value='2'/></period>", 'measure="3"'
    )

    assert indicator.measure is Measure.NOMINAL
    assert achievement(indicator).reason is NotCalculable.NOMINAL_LABELS
