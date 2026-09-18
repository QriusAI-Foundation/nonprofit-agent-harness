from __future__ import annotations

import pytest

from nonprofit_harness.core.errors import DataSourceError, InvalidRequest
from nonprofit_harness.datasources.iati import IatiActivity, IatiClient

# Shaped like a Datastore SOLR response. Fields repeat in IATI, so several arrive as
# lists, which is the part worth exercising.
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


def test_codes_are_used_when_names_are_absent():
    activity = IatiActivity.from_record(
        {"iati_identifier": "XX-1", "sector_code": ["11320", "11220"]}
    )

    assert activity.sectors == ("11320", "11220")


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
    assert call["params"]["q"] == "education"


def test_named_filters_become_a_solr_query(client):
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
