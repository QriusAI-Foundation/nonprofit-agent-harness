from __future__ import annotations

from nonprofit_harness.datasources.codelists import Codelists, bundled
from nonprofit_harness.datasources.iati import IatiActivity

SMALL = Codelists(
    lists={
        "Sector": {"11220": "Primary education", "12220": "Basic health care"},
        "Country": {"KE": "Kenya", "PS": "Palestine"},
        "ActivityStatus": {"2": "Implementation", "4": "Closed"},
    },
    source="test",
    fetched="2026-09-19",
)


# --- the bundled data ---------------------------------------------------------------


def test_the_bundle_ships_with_the_package():
    codes = bundled()

    assert len(codes) > 500
    assert set(codes.lists) >= {"Sector", "Country", "ActivityStatus"}


def test_the_bundle_records_where_it_came_from_and_when():
    """Bundled data goes stale silently unless it says when it was taken."""
    codes = bundled()

    assert codes.source.startswith("http")
    assert codes.fetched


def test_real_codes_resolve():
    codes = bundled()

    assert codes.name("Country", "KE") == "Kenya"
    assert codes.name("Sector", "11220")
    assert codes.name("ActivityStatus", "2")


def test_reading_the_bundle_is_cached():
    assert bundled() is bundled()


# --- resolution ---------------------------------------------------------------------


def test_a_label_keeps_the_code_alongside_the_name():
    """The code is what anyone cross-referencing the published data searches for."""
    assert SMALL.label("Sector", "11220") == "Primary education (11220)"


def test_an_unknown_code_stays_a_bare_code():
    assert SMALL.label("Sector", "99999") == "99999"
    assert SMALL.name("Sector", "99999") is None


def test_an_unknown_list_does_not_raise():
    assert SMALL.label("Nonsense", "1") == "1"


def test_an_empty_code_resolves_to_nothing():
    assert SMALL.name("Sector", "") is None


# --- the vocabulary guard -----------------------------------------------------------


def test_dac_sectors_resolve():
    assert SMALL.sector_labels(("11220",), ("1",)) == ("Primary education (11220)",)


def test_a_missing_vocabulary_is_treated_as_dac():
    """Which is what the standard's own default says."""
    assert SMALL.sector_labels(("11220",)) == ("Primary education (11220)",)


def test_a_publishers_own_numbering_is_never_given_a_dac_name():
    """The failure this guard exists for.

    Vocabulary 99 is the publisher's own scheme. Their code 11220 means whatever they
    say it means, and calling it "Primary education" would be a real, wrong name.
    """
    assert SMALL.sector_labels(("11220",), ("99",)) == ("11220",)


def test_mixed_vocabularies_resolve_per_code():
    got = SMALL.sector_labels(("11220", "12220"), ("1", "99"))

    assert got == ("Primary education (11220)", "12220")


def test_unalignable_vocabularies_resolve_nothing():
    """With counts that do not match, there is no safe way to pair code to vocabulary."""
    got = SMALL.sector_labels(("11220", "12220"), ("99",))

    assert got == ("11220", "12220")


# --- through the activity parser ----------------------------------------------------


def test_codes_without_narratives_become_readable():
    """Real published data often carries codes and no narrative at all."""
    activity = IatiActivity.from_record(
        {
            "iati_identifier": "XX-1",
            "recipient_country_code": ["KE"],
            "sector_code": ["11220"],
            "activity_status_code": "2",
        }
    )

    assert activity.recipient_countries == ("Kenya (KE)",)
    assert activity.sectors == ("Primary education (11220)",)
    assert activity.status_label == "Implementation (2)"


def test_the_publishers_own_narrative_wins_over_the_codelist():
    """It is what the organisation chose to call the thing."""
    activity = IatiActivity.from_record(
        {
            "iati_identifier": "XX-1",
            "sector_code": ["11220"],
            "sector_narrative": ["Our primary schooling workstream"],
        }
    )

    assert activity.sectors == ("Our primary schooling workstream (11220)",)


def test_a_non_dac_vocabulary_survives_the_parser_unresolved():
    activity = IatiActivity.from_record(
        {
            "iati_identifier": "XX-1",
            "sector_code": ["11220"],
            "sector_vocabulary": ["99"],
        }
    )

    assert activity.sectors == ("11220",)


def test_the_raw_status_code_is_still_available_for_matching():
    activity = IatiActivity.from_record(
        {"iati_identifier": "XX-1", "activity_status_code": "4"}
    )

    assert activity.status == "4"
    assert "Closed" in activity.status_label


def test_the_document_an_agent_receives_reads_in_words():
    activity = IatiActivity.from_record(
        {
            "iati_identifier": "XX-1",
            "title_narrative": ["Schools programme"],
            "recipient_country_code": ["KE"],
            "sector_code": ["11220"],
            "activity_status_code": "4",
        }
    )

    text = activity.to_document().text

    assert "Recipient countries: Kenya (KE)" in text
    assert "Sectors: Primary education (11220)" in text
    assert "Activity status: Closed (4)" in text
    assert "Activity status: 4" not in text


def test_an_unknown_code_still_reaches_the_agent_rather_than_vanishing():
    activity = IatiActivity.from_record(
        {"iati_identifier": "XX-1", "sector_code": ["99999"]}
    )

    assert activity.sectors == ("99999",)
