"""Regenerate phileas_hoard/travel/tables/airports.json from the ``airportsdata`` package (MIT licence).

    pip install airportsdata && python scripts/gen_airports.py

Keeps one row per IATA code: name, city, ISO country, IANA time zone. The app reads the JSON only; the package is not a
runtime dependency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "phileas_hoard" / "travel" / "tables" / "airports.json"


# The source capitalises every word ("Palma De Mallorca"): small joining words stay lower case inside a name.
PARTICLES = {"de", "del", "della", "di", "da", "do", "dos", "das", "du", "des", "of", "the", "and", "y", "am", "der", "von", "van", "den"}


def tidy(text: str) -> str:
    words = text.split(" ")
    return " ".join(w.lower() if i and w.lower() in PARTICLES else w for i, w in enumerate(words))


def main() -> int:
    try:
        import airportsdata
    except ImportError:
        print("install airportsdata first: pip install airportsdata")
        return 1
    data = airportsdata.load("IATA")
    rows = {}
    for code, a in sorted(data.items()):
        if len(code) != 3 or not a.get("tz"):
            continue
        rows[code] = [tidy(a["name"])[:60], tidy(a["city"])[:40], a["country"], a["tz"]]
    payload = {"source": f"airportsdata {getattr(airportsdata, '__version__', '')}".strip(), "licence": "MIT (airportsdata)",
               "columns": ["name", "city", "country", "tz"], "airports": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows)} airports, {OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
