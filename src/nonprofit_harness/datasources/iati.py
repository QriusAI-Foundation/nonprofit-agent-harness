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
            lines.append(f"Activity status: {self.status}")
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
        identifier = _one(record.get("iati_identifier"))
        if not identifier:
            raise DataSourceError("IATI record has no iati_identifier")
        return cls(
            iati_identifier=identifier,
            title=_one(record.get("title_narrative")),
            description=_join(record.get("description_narrative")),
            reporting_org=_one(record.get("reporting_org_narrative")),
            reporting_org_ref=_one(record.get("reporting_org_ref")),
            recipient_countries=_pair(
                record.get("recipient_country_narrative"), record.get("recipient_country_code")
            ),
            sectors=_pair(record.get("sector_narrative"), record.get("sector_code")),
            status=_one(record.get("activity_status_code")),
            dates=_many(record.get("activity_date_iso_date")),
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
    ) -> None:
        self.api_key = api_key or os.getenv(KEY_ENV)
        self.base_url = base_url.rstrip("/")
        self.key_header = key_header
        self.timeout = timeout
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

        `query` is passed through to SOLR. The named arguments are conveniences that
        add the usual filters, so callers do not have to know the field names.
        """
        if rows < 1:
            raise InvalidRequest("rows must be at least 1")

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


def _pair(names: Any, codes: Any) -> tuple[str, ...]:
    """Render a code list as "Name (code)" where a name is available."""
    name_list, code_list = _many(names), _many(codes)
    if not name_list:
        return code_list
    if len(name_list) != len(code_list):
        return name_list
    return tuple(f"{n} ({c})" for n, c in zip(name_list, code_list, strict=True))


def _escape(value: str) -> str:
    """Quote a SOLR term so a code containing a dash or colon is not parsed as syntax."""
    return '"' + value.replace('"', '\\"') + '"'


__all__ = [
    "BASE_URL",
    "DEFAULT_FIELDS",
    "KEY_ENV",
    "KEY_HEADER",
    "IatiActivity",
    "IatiClient",
]
