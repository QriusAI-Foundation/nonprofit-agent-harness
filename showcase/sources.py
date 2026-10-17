"""Fetch the showcase's source documents and turn them into harness `Document`s.

The PDFs are openly licensed but not ours to redistribute, so they are downloaded at run
time into `showcase/sources/` (gitignored) and checked against the hashes recorded in
`SOURCES.md`. A hash mismatch stops the run: a changed document would make the committed
outputs impossible to reproduce.

    python -m showcase.sources            # download and verify
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from nonprofit_harness.core.types import Document
from nonprofit_harness.documents import extract

HERE = Path(__file__).resolve().parent
CACHE = HERE / "sources"


@dataclass(frozen=True)
class Source:
    slug: str
    filename: str
    url: str
    sha256: str


DOCUMENTS = (
    Source(
        "who-chw-curriculum",
        "who-chw-curriculum-2025.pdf",
        "https://iris.who.int/server/api/core/bitstreams/38c8b2d1-d82f-413c-b4d2-e7e95d9365ca/content",
        "2005dd144340e8b8ba28e006d04356bee28e1dfedc9e4e3ba8fb4fd32118e4ba",
    ),
    Source(
        "ifrc-cbhfa-volunteers",
        "ifrc-cbhfa-volunteer-manual.pdf",
        "https://preparecenter.org/wp-content/sites/default/files/145600-3-cbfa-volunteers_lr_1.pdf",
        "2a2b38f92e14cda840d9d75c61cb3334f54a7ef1dcff2a068936f5f392d55b41",
    ),
    Source(
        "pathfinder-chbc-trainers",
        "pathfinder-chbc-trainers-guide-2006.pdf",
        "https://chwcentral.org/wp-content/uploads/2013/11/Community-Home-Based-Care-for-People-and-Communities-living-with-HIV-AIDS-A-Comprehensive-Training-Course-for-Community-Health-Workers-Entire-Trainers-Guide.pdf",
        "db71a3ceedc4077a8acc76c0b102a3b1b50dc2dbd87b5a82930629ce4e005caa",
    ),
)

#: Published IATI activities, fetched once through `IatiClient.activity_xml` and cached,
#: because the free tier allows 100 calls a week.
IATI_ACTIVITIES = (
    ("nlrc-pneumonia-cote-divoire", "NL-KVK-40409352-PRJ08-272-0005"),
    ("wbtf-rwanda-chw", "XI-IATI-WBTF-P175583"),
    ("cordaid-teenage-pregnancy-sl", "NL-KVK-41160054-200782"),
)


def fetch(source: Source) -> Path:
    import httpx

    path = CACHE / source.filename
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        response = httpx.get(
            source.url, follow_redirects=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}
        )
        response.raise_for_status()
        path.write_bytes(response.content)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source.sha256:
        raise SystemExit(f"{source.filename}: sha256 {digest} does not match SOURCES.md")
    return path


def document(source: Source) -> Document:
    path = fetch(source)
    return extract(path.read_bytes(), media_type="application/pdf", name=source.filename)


def iati_xml(slug: str, identifier: str) -> bytes:
    path = CACHE / "iati" / f"{slug}.xml"
    if not path.exists():
        from nonprofit_harness.datasources import IatiClient

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(IatiClient().activity_xml(identifier), encoding="utf-8")
    return path.read_bytes()


def results_documents() -> list[tuple[str, Document]]:
    from examples.results_narrative import results_sheet
    from nonprofit_harness.datasources.iati_xml import parse_activities

    sheets = []
    for slug, identifier in IATI_ACTIVITIES:
        activity = parse_activities(iati_xml(slug, identifier))[0]
        sheets.append((slug, results_sheet(activity, name=f"{identifier} results sheet")))
    return sheets


def main() -> int:
    for source in DOCUMENTS:
        path = fetch(source)
        print(f"ok  {source.filename}  {hashlib.sha256(path.read_bytes()).hexdigest()}")
    for slug, _ in results_documents():
        print(f"ok  iati/{slug}.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
