from __future__ import annotations

import io
import itertools
import zipfile

import pytest

from nonprofit_harness.cli import main
from nonprofit_harness.config import HarnessConfig
from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.documents import (
    DocumentError,
    DocumentTooLarge,
    ExtractionLimits,
    extract,
    supported_media_types,
)
from nonprofit_harness.documents import extraction as extraction_module

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of Helvetica text per page.

    Written by hand so the tests need no PDF writer and no private pypdf API.
    """
    count = len(pages)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{4 + 2 * i} 0 R".encode() for i in range(count))
        + f"] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * index} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def _docx(paragraphs: list[str]) -> bytes:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def test_plain_text_is_extracted_with_metadata():
    document = extract(b"Hello field team.", media_type="text/plain", name="note.txt")

    assert document.text == "Hello field team."
    assert document.name == "note.txt"
    assert document.metadata["bytes"] == 17
    assert document.metadata["truncated"] is False


def test_text_is_truncated_on_request_and_says_so():
    document = extract(b"abcdefghij", media_type="text/plain", max_chars=4)

    assert document.text == "abcd"
    assert document.metadata["truncated"] is True
    assert document.metadata["truncated_by"] == "characters"


def test_invalid_utf8_does_not_crash_extraction():
    document = extract(b"caf\xff", media_type="text/plain")

    assert document.text.startswith("caf")


def test_an_unsupported_type_is_rejected_clearly():
    with pytest.raises(InvalidRequest, match="Unsupported media type"):
        extract(b"\x00\x01", media_type="image/png")


def test_a_charset_suffix_is_tolerated():
    document = extract(b"body", media_type="text/plain; charset=utf-8")

    assert document.text == "body"


def test_the_supported_set_covers_what_the_api_advertises():
    assert "application/pdf" in supported_media_types()
    assert "text/plain" in supported_media_types()


@pytest.mark.parametrize(
    ("media_type", "body"),
    [
        ("text/plain", b"Plain notes from the field."),
        ("text/csv", b"district,households\nNorth,120\nSouth,95\n"),
        ("application/json", b'{"district": "North", "households": 120}'),
    ],
)
def test_plain_text_csv_and_json_still_work_under_default_limits(media_type, body):
    document = extract(body, media_type=media_type, limits=ExtractionLimits())

    assert document.text == body.decode()
    assert document.metadata["truncated"] is False


def test_the_config_defaults_match_the_library_defaults():
    assert ExtractionLimits.from_config(HarnessConfig()) == ExtractionLimits()


def test_limits_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_PDF_PAGES", "7")
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "none")

    limits = ExtractionLimits.from_config(HarnessConfig.from_env())

    assert limits.max_pdf_pages == 7
    assert limits.max_bytes is None


def test_an_oversized_file_is_refused_before_extraction():
    with pytest.raises(DocumentTooLarge, match="upload limit"):
        extract(b"x" * 2048, media_type="text/plain", limits=ExtractionLimits(max_bytes=1024))


def test_extraction_stops_at_the_character_limit():
    data = b"a" * 1_000_000

    document = extract(data, media_type="text/plain", limits=ExtractionLimits(max_chars=10))

    assert document.text == "a" * 10
    assert document.metadata["truncated_by"] == "characters"


def test_a_short_file_is_not_marked_truncated_at_the_character_limit():
    document = extract(b"exact", media_type="text/plain", limits=ExtractionLimits(max_chars=5))

    assert document.text == "exact"
    assert document.metadata["truncated"] is False


# PDF


def test_an_ordinary_pdf_still_extracts():
    pytest.importorskip("pypdf")

    document = extract(_pdf(["Page one", "Page two"]), media_type="application/pdf")

    assert "Page one" in document.text
    assert "Page two" in document.text
    assert document.metadata["pages"] == 2
    assert document.metadata["truncated"] is False


def test_a_pdf_beyond_the_page_cap_stops_at_the_cap_and_says_so():
    pytest.importorskip("pypdf")
    data = _pdf([f"Page {n}" for n in range(1, 6)])

    document = extract(data, media_type="application/pdf", limits=ExtractionLimits(max_pdf_pages=2))

    assert "Page 2" in document.text
    assert "Page 3" not in document.text
    assert document.metadata["pages"] == 5
    assert document.metadata["pages_read"] == 2
    assert document.metadata["truncated_by"] == "pages"


def test_pdf_extraction_stops_reading_pages_at_the_character_limit():
    pytest.importorskip("pypdf")
    data = _pdf(["x" * 100 for _ in range(5)])

    document = extract(data, media_type="application/pdf", limits=ExtractionLimits(max_chars=150))

    assert len(document.text) == 150
    assert document.metadata["pages_read"] == 2
    assert document.metadata["truncated_by"] == "characters"


def test_a_slow_pdf_is_refused_at_the_time_ceiling(monkeypatch):
    pytest.importorskip("pypdf")
    clock = itertools.chain([0.0, 0.0], itertools.repeat(500.0))
    monkeypatch.setattr(extraction_module.time, "monotonic", lambda: next(clock))

    with pytest.raises(DocumentTooLarge, match="took longer than 100 seconds"):
        extract(
            _pdf(["one", "two", "three"]),
            media_type="application/pdf",
            limits=ExtractionLimits(timeout_seconds=100),
        )


def test_a_corrupt_pdf_gives_a_controlled_error():
    pytest.importorskip("pypdf")

    with pytest.raises(DocumentError, match="as PDF"):
        extract(b"%PDF-1.4\nthis is not really a pdf", media_type="application/pdf")


# DOCX


def test_an_ordinary_docx_still_extracts():
    document = extract(_docx(["First paragraph.", "Second paragraph."]), media_type=DOCX)

    assert document.text == "First paragraph.\nSecond paragraph."
    assert document.metadata["truncated"] is False


def test_docx_extraction_stops_at_the_character_limit():
    data = _docx([f"Paragraph {n} with some words." for n in range(200)])

    document = extract(data, media_type=DOCX, limits=ExtractionLimits(max_chars=50))

    assert len(document.text) <= 50
    assert document.text.startswith("Paragraph 0")
    assert document.metadata["truncated_by"] == "characters"


def test_a_zip_whose_declared_expansion_exceeds_the_cap_is_refused_before_reading(monkeypatch):
    docx = pytest.importorskip("docx")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"0" * (2 * 1024 * 1024))
    data = archive.getvalue()
    assert len(data) < 64 * 1024  # small on the wire, large once unzipped

    def must_not_parse(*_args, **_kwargs):
        raise AssertionError("the archive was parsed before its size was checked")

    monkeypatch.setattr(docx, "Document", must_not_parse)

    with pytest.raises(DocumentTooLarge, match="expands to 2MB once unzipped"):
        extract(
            data,
            media_type=DOCX,
            limits=ExtractionLimits(max_docx_expanded_bytes=1024 * 1024),
        )


@pytest.mark.parametrize(
    "data",
    [
        b"PK\x03\x04 this is not a zip archive",
        b"plain bytes, no archive at all",
    ],
)
def test_a_corrupt_docx_gives_a_controlled_error(data):
    pytest.importorskip("docx")

    with pytest.raises(DocumentError, match="as DOCX"):
        extract(data, media_type=DOCX)


def test_a_zip_that_is_not_a_docx_gives_a_controlled_error():
    pytest.importorskip("docx")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("hello.txt", "not a word document")

    with pytest.raises(DocumentError, match="as DOCX"):
        extract(archive.getvalue(), media_type=DOCX)


# Command line


def test_the_cli_refuses_an_oversized_file_without_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "16")
    brief = tmp_path / "brief.txt"
    brief.write_text("This brief is longer than sixteen bytes.")

    code = main(["run", "examples.summarizer:SummarizerAgent", str(brief)])

    assert code == 2
    err = capsys.readouterr()
    assert "upload limit" in err.err
    assert "run " not in err.out
