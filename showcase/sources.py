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
from nonprofit_harness.documents.extraction import ExtractionLimits

HERE = Path(__file__).resolve().parent
CACHE = HERE / "sources"

#: The harness caps a PDF at 300 pages and two minutes by default (HARNESS_MAX_PDF_PAGES,
#: HARNESS_EXTRACT_TIMEOUT_SECONDS), which protects a public upload endpoint. These are
#: known documents read on purpose, the longest at 748 pages, so the deployer lifts them.
LIMITS = ExtractionLimits(
    max_bytes=None, max_pdf_pages=1_000, max_chars=None, timeout_seconds=900.0
)


@dataclass(frozen=True)
class Source:
    slug: str
    filename: str
    url: str
    sha256: str
    #: Extract page by page and skip pages pypdf cannot parse. Needed for a PDF on
    #: which the harness's own `extract` raises; the skipped pages are recorded.
    tolerant: bool = False


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

#: Added after the first pass, at the Foundation's request for longer documents.
MORE_DOCUMENTS = (
    Source(
        "alnap-sohs-2022",
        "alnap-sohs-2022.pdf",
        # A byte-identical mirror: the ALNAP URL for the full report returned 404.
        "https://www.oiren.org/wp-content/uploads/2023/11/State-of-Humanitarian-System-2022_Full-report.pdf",
        "982ffd712b56d36276c58e399f7d09c788e2e324410484770e1b014ed45bca06",
    ),
    Source(
        "wdr-2018-learning",
        "wdr-2018-learning.pdf",
        "https://documents1.worldbank.org/curated/en/240351507784846426/pdf/120299-WDR-v1-PUBLIC-main.pdf",
        "091c14411843f9efec16b097e715fdc00e29e18f8973fab4e399500d409a7393",
        tolerant=True,
    ),
    Source(
        "wb-vnen-evaluation",
        "wb-vnen-impact-evaluation-2017.pdf",
        "https://documents1.worldbank.org/curated/en/339001502818131149/pdf/118675-REVISED-PUBLIC-1708908-VNEN-IE-Web.pdf",
        "4253431599023da2c296e1574e0bdad624f1a4d8c1b3098b22704d040065ad7f",
    ),
)

ALL_DOCUMENTS = DOCUMENTS + MORE_DOCUMENTS

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
    if not source.tolerant:
        return extract(
            path.read_bytes(), media_type="application/pdf", name=source.filename, limits=LIMITS
        )
    from pypdf import PdfReader

    pages, skipped = [], []
    for number, page in enumerate(PdfReader(str(path)).pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one unparseable page should not sink the rest
            pages.append("")
            skipped.append(number)
    return Document(
        text="\n\n".join(pages).strip(),
        name=source.filename,
        media_type="application/pdf",
        metadata={"pages": len(pages), "skipped_pages": skipped},
    )


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
    for source in ALL_DOCUMENTS:
        path = fetch(source)
        print(f"ok  {source.filename}  {hashlib.sha256(path.read_bytes()).hexdigest()}")
    for slug, _ in results_documents():
        print(f"ok  iati/{slug}.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
