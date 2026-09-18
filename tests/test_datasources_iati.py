from __future__ import annotations

import pytest

from nonprofit_harness.core.errors import DataSourceError, InvalidRequest
from nonprofit_harness.datasources.iati import IatiActivity, IatiClient

# Shaped like a Datastore SOLR response. Fields repeat in IATI, so several arrive as
# lists, which is the part worth exercising.
#
# REAL_WORLD below is copied from the shape of an actual live response. It matters
# because real published data is messier than an idealised fixture: narratives are
# often absent, codes repeat across vocabularies, and dates arrive as full timestamps.
# A fixture that is tidier than reality is how tests pass while the code does not work.
REAL_WORLD = {
    "response": {
        "numFound": 1,
        "docs": [
            {
                "iati_identifier": "XM-DAC-41130-2019ProgB-2-EG05",
                "title_narrative": ["2019 Programme Budget - Gaza - Education"],
                "description_narrative": ["2019 Programme Budget - Gaza - Education"],
                "reporting_org_ref": "XM-DAC-41130",
                "reporting_org_narrative": ["UNRWA"],
                "recipient_country_code": ["PS"],
                # no recipient_country_narrative, no sector_narrative
                "sector_code": ["11220", "11220"],
                "activity_status_code": "4",
                "activity_date_iso_date": ["2019-01-01T00:00:00Z", "2019-12-31T00:00:00Z"],
            }
        ],
    }
}

RESPONSE = {
    "response": {
        "numFound": 1,
        "docs": [
            {
                "iati_identifier": "XM-DAC-41114-PROJECT-1",
                "title_narrative": ["Girls' secondary education programme"],
                "description_narrative": [
                    "The programme supports girls to complete secondary education.",
                    "It reached 12 districts in the reporting year.",
                ],
                "reporting_org_ref": "XM-DAC-41114",
                "reporting_org_narrative": ["Example Development Agency"],
                "recipient_country_code": ["KE", "UG"],
                "recipient_country_narrative": ["Kenya", "Uganda"],
                "sector_code": ["11320"],
                "sector_narrative": ["Secondary education"],
                "activity_status_code": "2",
                "activity_date_iso_date": ["2024-01-01", "2026-12-31"],
            }
        ],
    }
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeHttp:
    """Records the requests made, so the query built can be asserted on."""

    def __init__(self, payload=RESPONSE, status_code=200):
        self._payload = payload
        self._status = status_code
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return FakeResponse(self._payload, self._status)


@pytest.fixture
def client():
    return IatiClient(api_key="test-key", client=FakeHttp())


# --- parsing -----------------------------------------------------------------------


def test_an_activity_is_flattened_from_a_record():
    activity = IatiActivity.from_record(RESPONSE["response"]["docs"][0])

    assert activity.iati_identifier == "XM-DAC-41114-PROJECT-1"
    assert activity.title == "Girls' secondary education programme"
    assert activity.reporting_org == "Example Development Agency"
    assert activity.recipient_countries == ("Kenya (KE)", "Uganda (UG)")
    assert activity.sectors == ("Secondary education (11320)",)
    assert activity.dates == ("2024-01-01", "2026-12-31")


def test_repeated_description_narratives_are_joined():
    activity = IatiActivity.from_record(RESPONSE["response"]["docs"][0])

    assert "complete secondary education" in activity.description
    assert "reached 12 districts" in activity.description


def test_a_record_without_an_identifier_is_rejected():
    with pytest.raises(DataSourceError, match="no iati_identifier"):
        IatiActivity.from_record({"title_narrative": "No identifier"})


def test_missing_fields_do_not_break_parsing():
    activity = IatiActivity.from_record({"iati_identifier": "XX-1"})

    assert activity.title == ""
    assert activity.recipient_countries == ()


def test_a_code_outside_the_codelist_is_still_passed_through():
    """Better a bare code than a wrong name, and better than dropping it entirely."""
    activity = IatiActivity.from_record(
        {"iati_identifier": "XX-1", "sector_code": ["99998", "99999"]}
    )

    assert activity.sectors == ("99998", "99999")


def test_real_published_data_parses():
    """Against the shape of an actual live response, not an idealised one."""
    activity = IatiActivity.from_record(REAL_WORLD["response"]["docs"][0])

    assert activity.iati_identifier == "XM-DAC-41130-2019ProgB-2-EG05"
    assert activity.reporting_org == "UNRWA"
    # No narrative published, so the name comes from the bundled codelist.
    assert activity.recipient_countries == ("Palestine, State of (PS)",)


def test_a_code_repeated_across_vocabularies_appears_once():
    activity = IatiActivity.from_record(REAL_WORLD["response"]["docs"][0])

    assert activity.sectors == ("Primary education (11220)",)


def test_dates_are_labelled_with_their_type_and_deduplicated():
    """A real activity repeats each day once per date type, so eight entries collapse to four."""
    activity = IatiActivity.from_record(
        {
            "iati_identifier": "XX-1",
            "activity_date_iso_date": [
                "2019-01-01T00:00:00Z",
                "2019-12-31T00:00:00Z",
                "2019-01-01T00:00:00Z",
                "2019-12-31T00:00:00Z",
            ],
            "activity_date_type": ["1", "3", "2", "4"],
        }
    )

    assert activity.dates == (
        "planned start 2019-01-01",
        "planned end 2019-12-31",
        "actual start 2019-01-01",
        "actual end 2019-12-31",
    )


def test_unlabelled_dates_fall_back_to_deduplicated_days():
    activity = IatiActivity.from_record(
        {
            "iati_identifier": "XX-1",
            "activity_date_iso_date": ["2019-01-01T00:00:00Z", "2019-01-01T00:00:00Z"],
        }
    )

    assert activity.dates == ("2019-01-01",)


def test_timestamps_are_shown_as_dates():
    """IATI returns 2019-01-01T00:00:00Z, which is noise in a document a person reads."""
    text = IatiActivity.from_record(REAL_WORLD["response"]["docs"][0]).to_text()

    assert "Activity dates: 2019-01-01, 2019-12-31" in text
    assert "T00:00:00Z" not in text


# --- conversion to harness input ---------------------------------------------------


def test_an_activity_becomes_a_document():
    document = IatiActivity.from_record(RESPONSE["response"]["docs"][0]).to_document()

    assert document.name == "XM-DAC-41114-PROJECT-1"
    assert document.metadata["source"] == "iati"
    assert document.metadata["recipient_countries"] == ["Kenya (KE)", "Uganda (UG)"]


def test_the_document_text_carries_the_facts_a_claim_would_cite():
    """Verification finds a quoted span in this text, so the facts have to be in it."""
    text = IatiActivity.from_record(RESPONSE["response"]["docs"][0]).to_text()

    assert "Girls' secondary education programme" in text
    assert "Example Development Agency (XM-DAC-41114)" in text
    assert "Kenya (KE), Uganda (UG)" in text
    assert "reached 12 districts" in text


def test_a_claim_citing_a_fetched_activity_verifies():
    from nonprofit_harness.verification import Citation, Claim, GroundingVerifier

    document = IatiActivity.from_record(RESPONSE["response"]["docs"][0]).to_document()
    verifier = GroundingVerifier()

    good = verifier.verify(
        Claim(
            statement="The programme reached 12 districts.",
            citations=[Citation(text="reached 12 districts in the reporting year")],
        ),
        {document.name: document.text},
    )
    invented = verifier.verify(
        Claim(
            statement="The programme reached 90 districts.",
            citations=[Citation(text="reached 90 districts in the reporting year")],
        ),
        {document.name: document.text},
    )

    assert good.ok
    assert not invented.ok


# --- the client ---------------------------------------------------------------------


def test_searching_sends_the_key_and_returns_activities(client):
    found = client.search_activities("education")

    assert len(found) == 1
    call = client._client.calls[0]
    assert call["headers"]["Ocp-Apim-Subscription-Key"] == "test-key"
    assert call["url"].endswith("/activity/select")


def test_a_bare_term_is_expanded_across_text_fields(client):
    """The live Datastore returns HTTP 400 for an unqualified query, so it must not send one."""
    client.search_activities("education")

    q = client._client.calls[0]["params"]["q"]
    assert q == "(title_narrative:(education) OR description_narrative:(education))"
    assert not q.startswith("education")


def test_explicit_solr_syntax_is_passed_through_untouched(client):
    client.search_activities("title_narrative:education AND sector_code:11320")

    assert (
        client._client.calls[0]["params"]["q"]
        == "title_narrative:education AND sector_code:11320"
    )


def test_the_match_all_query_is_left_alone(client):
    client.search_activities()

    assert client._client.calls[0]["params"]["q"] == "*:*"


def test_an_empty_query_becomes_match_all(client):
    client.search_activities("   ")

    assert client._client.calls[0]["params"]["q"] == "*:*"


def test_the_searched_text_fields_are_configurable():
    narrow = IatiClient(api_key="k", client=FakeHttp(), text_fields=["title_narrative"])
    narrow.search_activities("education")

    assert narrow._client.calls[0]["params"]["q"] == "(title_narrative:(education))"


def test_named_filters_become_a_solr_query(client):
    """The reporting_org form here is the one confirmed working against the live API."""
    client.search_activities(reporting_org="XM-DAC-41114", country="KE", sector="11320")

    q = client._client.calls[0]["params"]["q"]
    assert 'reporting_org_ref:"XM-DAC-41114"' in q
    assert 'recipient_country_code:"KE"' in q
    assert 'sector_code:"11320"' in q


def test_an_identifier_with_dashes_is_quoted_not_parsed_as_syntax(client):
    client.activity("XM-DAC-41114-PROJECT-1")

    assert client._client.calls[0]["params"]["q"] == 'iati_identifier:"XM-DAC-41114-PROJECT-1"'


def test_a_missing_activity_returns_none():
    empty = IatiClient(api_key="k", client=FakeHttp({"response": {"docs": []}}))

    assert empty.activity("XX-nope") is None


def test_no_key_is_a_clear_error_not_a_request(monkeypatch):
    monkeypatch.delenv("IATI_API_KEY", raising=False)
    http = FakeHttp()

    with pytest.raises(DataSourceError, match="needs an API key"):
        IatiClient(client=http).search_activities("x")

    assert http.calls == []


def test_the_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("IATI_API_KEY", "from-env")
    http = FakeHttp()

    IatiClient(client=http).search_activities("x")

    assert http.calls[0]["headers"]["Ocp-Apim-Subscription-Key"] == "from-env"


def test_a_rate_limit_says_what_the_quota_actually_is():
    limited = IatiClient(api_key="k", client=FakeHttp({}, status_code=429))

    with pytest.raises(DataSourceError, match="100 a week"):
        limited.search_activities("x")


def test_a_rejected_key_is_reported_as_such():
    with pytest.raises(DataSourceError, match="rejected the API key"):
        IatiClient(api_key="bad", client=FakeHttp({}, status_code=401)).search_activities("x")


def test_rows_must_be_positive(client):
    with pytest.raises(InvalidRequest):
        client.search_activities("x", rows=0)


def test_a_cache_prevents_a_second_call():
    """The free tier allows 100 calls a week, so a repeated query must not spend two."""
    http = FakeHttp()
    cached = IatiClient(api_key="k", client=http, cache={})

    cached.search_activities("education")
    cached.search_activities("education")

    assert len(http.calls) == 1


def test_different_queries_are_cached_separately():
    http = FakeHttp()
    cached = IatiClient(api_key="k", client=http, cache={})

    cached.search_activities("education")
    cached.search_activities("health")

    assert len(http.calls) == 2
