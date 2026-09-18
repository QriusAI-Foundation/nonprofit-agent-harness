"""Read activity data published to the IATI Standard.

IATI is the International Aid Transparency Initiative, the open standard most
development and humanitarian funders publish their activity data against. It is the
closest thing this sector has to a canonical, global, machine-readable dataset, which
is why it is the first data source here.

The Datastore is a SOLR-backed API behind an Azure gateway. Access needs a free key
from https://developer.iatistandard.org. The no-approval tier allows 5 calls a minute
and 100 calls a week, which is little enough that a cache is not optional in practice.

The endpoint path, field names, and key header are all constructor arguments on
purpose. If IATI moves something, a deployment can correct it in configuration rather
than waiting for a release.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

from nonprofit_harness.core.errors import DataSourceError, InvalidRequest
from nonprofit_harness.core.types import Document

BASE_URL = "https://api.iatistandard.org/datastore"
KEY_HEADER = "Ocp-Apim-Subscription-Key"
KEY_ENV = "IATI_API_KEY"

#: Where a plain search term is looked for. The Datastore's SOLR core declares no
#: default search field, so a bare term is rejected with "no field name specified in
#: query and no default specified" rather than treated as a full-text search. Every
#: query therefore has to name its fields.
TEXT_FIELDS = ("title_narrative", "description_narrative")

#: IATI's ActivityDateType codelist, which has these four values and is stable.
#: An activity reports its dates against them, so the raw date list arrives with each
#: value repeated and nothing to say which is which.
ACTIVITY_DATE_TYPES = {
    "1": "planned start",
    "2": "actual start",
    "3": "planned end",
    "4": "actual end",
}

#: Requested explicitly rather than taking every field, because an activity document
#: can be very large and the free tier's weekly call budget is better spent on more
#: activities than on more fields per activity.
DEFAULT_FIELDS = (
    "iati_identifier",
    "title_narrative",
    "description_narrative",
    "reporting_org_ref",
    "reporting_org_narrative",
    "recipient_country_code",
    "recipient_country_narrative",
    "sector_code",
    "sector_narrative",
    # Requested so a code is only resolved against the DAC list when it is a DAC code.
    # Without it, a publisher's own sector numbering would be given someone else's name.
    "sector_vocabulary",
    "activity_status_code",
    "activity_date_iso_date",
    "activity_date_type",
)


@dataclass(frozen=True, slots=True)
class IatiActivity:
    """One published activity, flattened into the fields an agent usually wants."""

    iati_identifier: str
    title: str = ""
    description: str = ""
    reporting_org: str = ""
    reporting_org_ref: str = ""
    recipient_countries: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()
    status: str = ""
    #: The status as words. Kept separate so `status` stays the raw code for anyone
    #: matching on it.
    status_label: str = ""
    dates: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        """A readable rendering, and the text a claim about this activity is checked against.

        Written out in full sentences rather than as a compact record, because the
        harness verifies citations by finding the quoted span in this text. A quote
        can only resolve against wording that actually appears here.
        """
        lines = [self.title or self.iati_identifier, ""]
        lines.append(f"IATI identifier: {self.iati_identifier}")
        if self.reporting_org:
            org = self.reporting_org
            if self.reporting_org_ref:
                org = f"{org} ({self.reporting_org_ref})"
            lines.append(f"Reporting organisation: {org}")
        if self.recipient_countries:
            lines.append(f"Recipient countries: {', '.join(self.recipient_countries)}")
        if self.sectors:
            lines.append(f"Sectors: {', '.join(self.sectors)}")
        if self.status:
            lines.append(f"Activity status: {self.status_label or self.status}")
        if self.dates:
            lines.append(f"Activity dates: {', '.join(self.dates)}")
        if self.description:
            lines.extend(["", self.description])
        return "\n".join(lines)

    def to_document(self) -> Document:
        """Turn this into harness input, so an agent consumes it like any other document."""
        return Document(
            text=self.to_text(),
            name=self.iati_identifier,
            media_type="text/plain",
            metadata={
                "source": "iati",
                "iati_identifier": self.iati_identifier,
                "reporting_org_ref": self.reporting_org_ref,
                "recipient_countries": list(self.recipient_countries),
            },
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> IatiActivity:
        """Flatten one record, filling in readable names where the publisher gave none.

        A narrative published alongside a code always wins: it is what the organisation
        itself chose to call the thing. The bundled codelists are a fallback for the
        common case of a code with no narrative, which would otherwise reach an agent as
        a bare number.
        """
        from nonprofit_harness.datasources.codelists import bundled

        identifier = _one(record.get("iati_identifier"))
        if not identifier:
            raise DataSourceError("IATI record has no iati_identifier")

        codes = bundled()
        country_codes = _many(record.get("recipient_country_code"))
        sector_codes = _many(record.get("sector_code"))
        status = _one(record.get("activity_status_code"))

        return cls(
            iati_identifier=identifier,
            title=_one(record.get("title_narrative")),
            description=_join(record.get("description_narrative")),
            reporting_org=_one(record.get("reporting_org_narrative")),
            reporting_org_ref=_one(record.get("reporting_org_ref")),
            recipient_countries=_pair(
                record.get("recipient_country_narrative"),
                record.get("recipient_country_code"),
                fallback=codes.labels("Country", country_codes),
            ),
            sectors=_pair(
                record.get("sector_narrative"),
                record.get("sector_code"),
                fallback=codes.sector_labels(
                    sector_codes, _many(record.get("sector_vocabulary"))
                ),
            ),
            status=status,
            status_label=codes.label("ActivityStatus", status) if status else "",
            dates=_dates(
                record.get("activity_date_iso_date"), record.get("activity_date_type")
            ),
            raw=record,
        )


class IatiClient:
    """A thin client over the IATI Datastore.

    Pass `cache` a dict to reuse responses within a process. With 100 calls a week on
    the free tier, repeating a query during development will exhaust the quota faster
    than most people expect.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        key_header: str = KEY_HEADER,
        timeout: float = 20.0,
        client: Any = None,
        cache: MutableMapping[str, Any] | None = None,
        text_fields: Iterable[str] = TEXT_FIELDS,
    ) -> None:
        self.api_key = api_key or os.getenv(KEY_ENV)
        self.base_url = base_url.rstrip("/")
        self.key_header = key_header
        self.timeout = timeout
        self.text_fields = tuple(text_fields)
        self._client = client
        self._cache = cache

    def search_activities(
        self,
        query: str = "*:*",
        *,
        reporting_org: str | None = None,
        country: str | None = None,
        sector: str | None = None,
        rows: int = 20,
        fields: Iterable[str] = DEFAULT_FIELDS,
    ) -> list[IatiActivity]:
        """Search published activities.

        A plain term such as "education" is expanded across `text_fields`, because the
        Datastore rejects an unqualified query. A term containing a colon is treated as
        SOLR syntax and passed through untouched, so any query you can write by hand
        still works.
        """
        if rows < 1:
            raise InvalidRequest("rows must be at least 1")

        query = _expand_free_text(query, self.text_fields)
        filters = []
        if reporting_org:
            filters.append(f"reporting_org_ref:{_escape(reporting_org)}")
        if country:
            filters.append(f"recipient_country_code:{_escape(country)}")
        if sector:
            filters.append(f"sector_code:{_escape(sector)}")

        params = {
            "q": " AND ".join([query, *filters]) if filters else query,
            "rows": str(rows),
            "fl": ",".join(fields),
            "wt": "json",
        }
        payload = self._get("activity/select", params)
        records = (payload.get("response") or {}).get("docs") or []
        return [IatiActivity.from_record(r) for r in records]

    def indicators(self, iati_identifier: str):
        """Fetch one activity's indicators, rebuilt into the results model.

        Returns an `IatiResults`, which carries what could be reconstructed and what
        could not. Read its `warnings` before reporting any number from it: the
        Datastore's flattening loses the link between results and their indicators, and
        sometimes the direction of an indicator too.
        """
        from nonprofit_harness.datasources.iati_results import (
            RESULT_FIELDS,
            IatiResults,
            results_from_record,
        )

        payload = self._get(
            "activity/select",
            {
                "q": f"iati_identifier:{_escape(iati_identifier)}",
                "rows": "1",
                "fl": ",".join(RESULT_FIELDS),
                "wt": "json",
            },
        )
        records = (payload.get("response") or {}).get("docs") or []
        return results_from_record(records[0]) if records else IatiResults()

    def activity(self, iati_identifier: str) -> IatiActivity | None:
        """Fetch one activity by its IATI identifier."""
        found = self.search_activities(
            f"iati_identifier:{_escape(iati_identifier)}", rows=1
        )
        return found[0] if found else None

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not self.api_key:
            raise DataSourceError(
                f"IATI needs an API key. Set {KEY_ENV}, or pass api_key. "
                "Register free at https://developer.iatistandard.org"
            )

        cache_key = f"{path}?{sorted(params.items())}"
        if self._cache is not None and cache_key in self._cache:
            return self._cache[cache_key]

        client = self._client or self._build_client()
        response = client.get(
            f"{self.base_url}/{path}",
            params=params,
            headers={self.key_header: self.api_key},
        )

        status = getattr(response, "status_code", 200)
        if status == 401 or status == 403:
            raise DataSourceError("IATI rejected the API key")
        if status == 429:
            raise DataSourceError(
                "IATI rate limit reached. The free tier allows 5 calls a minute and "
                "100 a week. Pass a cache, or request the full access subscription"
            )
        if status >= 400:
            raise DataSourceError(f"IATI returned HTTP {status}")

        payload = response.json()
        if self._cache is not None:
            self._cache[cache_key] = payload
        return payload

    def _build_client(self) -> Any:
        import httpx

        return httpx.Client(timeout=self.timeout)


def _many(value: Any) -> tuple[str, ...]:
    """IATI fields repeat, so a field is a value, a list, or absent."""
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(str(v) for v in value if v not in (None, ""))
    return (str(value),) if str(value) else ()


def _one(value: Any) -> str:
    found = _many(value)
    return found[0] if found else ""


def _join(value: Any, separator: str = "\n\n") -> str:
    return separator.join(_many(value))


def _pair(names: Any, codes: Any, *, fallback: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Render a code list as "Name (code)", preferring the publisher's own wording.

    Narratives are frequently absent in real published data, which is why `fallback`
    exists: names resolved from the bundled codelists. Codes repeat too, because an
    activity can report the same sector against several vocabularies, so the result is
    deduplicated either way.
    """
    name_list, code_list = _many(names), _many(codes)
    if not name_list:
        return _dedupe(fallback or code_list)
    if len(name_list) != len(code_list):
        return _dedupe(name_list)
    return _dedupe(tuple(f"{n} ({c})" for n, c in zip(name_list, code_list, strict=True)))


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _as_day(value: str) -> str:
    """Trim an ISO timestamp to its date. IATI returns "2019-01-01T00:00:00Z"."""
    return value.split("T", 1)[0]


def _dates(values: Any, types: Any) -> tuple[str, ...]:
    """Label each date with what it means, and drop the repeats.

    An activity reports a date per ActivityDateType, so the raw list arrives with the
    same day several times over. Unlabelled and undeduplicated, a real activity renders
    as eight dates that say nothing.
    """
    days = tuple(_as_day(value) for value in _many(values))
    kinds = _many(types)
    if not days:
        return ()
    if len(kinds) != len(days):
        return _dedupe(days)
    return _dedupe(
        tuple(
            f"{ACTIVITY_DATE_TYPES.get(kind, kind)} {day}"
            for kind, day in zip(kinds, days, strict=True)
        )
    )


def _expand_free_text(query: str, fields: tuple[str, ...]) -> str:
    """Turn a bare search term into a field-qualified SOLR query.

    Confirmed against the live API: `q=education` returns HTTP 400, while
    `q=title_narrative:education` succeeds. Anything already carrying a colon is
    assumed to be deliberate SOLR syntax and is left alone.
    """
    stripped = query.strip()
    if not stripped:
        return "*:*"
    if stripped == "*:*" or ":" in stripped or not fields:
        return stripped
    return "(" + " OR ".join(f"{name}:({stripped})" for name in fields) + ")"


def _escape(value: str) -> str:
    """Quote a SOLR term so a code containing a dash or colon is not parsed as syntax."""
    return '"' + value.replace('"', '\\"') + '"'


__all__ = [
    "BASE_URL",
    "DEFAULT_FIELDS",
    "KEY_ENV",
    "KEY_HEADER",
    "TEXT_FIELDS",
    "IatiActivity",
    "IatiClient",
]
