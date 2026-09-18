from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\w)(?:\+\d{1,3}[\s-]?)?(?:\d[\s-]?){9,13}\d(?!\w)"),
    "aadhaar": re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)"),
    "ssn": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "card": re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
}


@dataclass
class Redactor:
    """Masks direct identifiers before text reaches a model.

    Nonprofits hold beneficiary records, so the default path should not ship a
    name-and-phone-number list to a third-party API by accident. This is a blunt
    pattern matcher, not a promise of anonymity, and it is documented as such.
    """

    enabled: set[str] = field(default_factory=lambda: set(_PATTERNS))
    placeholder: str = "[redacted:{kind}]"

    def redact(self, text: str) -> str:
        return self.scan(text)[0]

    def scan(self, text: str) -> tuple[str, dict[str, int]]:
        counts: dict[str, int] = {}
        out = text
        for kind, pattern in _PATTERNS.items():
            if kind not in self.enabled:
                continue
            out, hits = pattern.subn(self.placeholder.format(kind=kind), out)
            if hits:
                counts[kind] = hits
        return out, counts


__all__ = ["Redactor"]
