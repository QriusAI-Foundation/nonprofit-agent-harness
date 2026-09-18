from __future__ import annotations

import pytest

from nonprofit_harness.core.errors import InvalidRequest
from nonprofit_harness.documents import extract, supported_media_types


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
