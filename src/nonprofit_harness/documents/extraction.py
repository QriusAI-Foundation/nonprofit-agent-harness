from __future__ import annotations

import io
from dataclasses import dataclass

from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.core.types import Document

TEXT_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json"}
PDF_TYPES = {"application/pdf"}
DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True, slots=True)
class Extraction:
    text: str
    pages: int = 1
    truncated: bool = False


def supported_media_types() -> set[str]:
    return TEXT_TYPES | PDF_TYPES | DOCX_TYPES


def extract(
    data: bytes,
    *,
    media_type: str,
    name: str = "untitled",
    max_chars: int | None = None,
) -> Document:
    """Turn an uploaded file into the plain text an agent actually receives.

    Agents never see bytes. Keeping extraction here means a new input format is a
    change in one place, not in every agent.
    """
    extraction = _extract_raw(data, media_type=media_type)
    text = extraction.text
    truncated = extraction.truncated
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    return Document(
        text=text,
        name=name,
        media_type=media_type,
        metadata={"pages": extraction.pages, "truncated": truncated, "bytes": len(data)},
    )


def _extract_raw(data: bytes, *, media_type: str) -> Extraction:
    base_type = media_type.split(";")[0].strip().lower()

    if base_type in TEXT_TYPES:
        return Extraction(text=data.decode("utf-8", errors="replace"))
    if base_type in PDF_TYPES:
        return _extract_pdf(data)
    if base_type in DOCX_TYPES:
        return _extract_docx(data)

    raise InvalidRequest(
        f"Unsupported media type {media_type!r}. Supported: {sorted(supported_media_types())}"
    )


def _extract_pdf(data: bytes) -> Extraction:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise InvalidRequest(
            "PDF extraction needs the `documents` extra: "
            "pip install 'nonprofit-agent-harness[documents]'"
        ) from exc

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return Extraction(text="\n\n".join(pages).strip(), pages=len(pages))


def _extract_docx(data: bytes) -> Extraction:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise InvalidRequest(
            "DOCX extraction needs the `documents` extra: "
            "pip install 'nonprofit-agent-harness[documents]'"
        ) from exc

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return Extraction(text="\n".join(parts).strip())


__all__ = ["Extraction", "extract", "supported_media_types"]
