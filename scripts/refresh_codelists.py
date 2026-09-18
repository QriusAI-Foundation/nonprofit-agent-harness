#!/usr/bin/env python3
"""Regenerate the bundled IATI codelists.

    python scripts/refresh_codelists.py

The codelists are bundled rather than fetched at runtime, so that reading published
data needs no network, no key, and no quota. The cost of that choice is staleness,
which is why the generated file records where the data came from and when, and why
this script exists rather than the file being edited by hand.

Only the code and the name are kept. The upstream Sector list is 120KB, almost all of
it descriptions that nothing here reads.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

SOURCE = "https://codelists.codeforiati.org/api/json/en/"

#: Kept deliberately short. Each list is weight in every install, so a list earns its
#: place by appearing in output a person reads.
WANTED = ("Sector", "Country", "ActivityStatus", "Region", "OrganisationType")

TARGET = (
    Path(__file__).parent.parent
    / "src"
    / "nonprofit_harness"
    / "datasources"
    / "codelists.json"
)


def fetch(name: str) -> dict[str, str]:
    import httpx

    response = httpx.get(f"{SOURCE}{name}.json", timeout=60.0)
    response.raise_for_status()
    body = response.json()
    items = body.get("data") if isinstance(body, dict) else body

    resolved: dict[str, str] = {}
    for item in items:
        code, label = str(item.get("code", "")), str(item.get("name", "")).strip()
        # A code with no name resolves to nothing useful, and an entry that maps a code
        # to itself is worse than leaving the code bare.
        if code and label and label != code:
            resolved[code] = label
    return resolved


def main() -> int:
    lists: dict[str, dict[str, str]] = {}
    for name in WANTED:
        try:
            lists[name] = fetch(name)
        except Exception as exc:  # noqa: BLE001 - report and carry on with the rest
            print(f"  {name}: FAILED ({exc})", file=sys.stderr)
            continue
        print(f"  {name}: {len(lists[name])} entries")

    if not lists:
        print("nothing fetched, leaving the bundled file alone", file=sys.stderr)
        return 1

    TARGET.write_text(
        json.dumps(
            {
                "source": SOURCE,
                "fetched": datetime.now(UTC).date().isoformat(),
                "lists": lists,
            },
            indent=1,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {TARGET.relative_to(Path.cwd())} ({TARGET.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
