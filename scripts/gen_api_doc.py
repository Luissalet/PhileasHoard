"""Regenerate docs/API.md from the tool catalogue: python scripts/gen_api_doc.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from phileas_hoard.agent_tools import TOOLS  # noqa: E402


def main() -> int:
    lines = ["# Phileas's Hoard — agent tools", "",
             "Every tool is served by the app at `GET /api/agent/tools` and `POST /api/agent/call` (Bearer token from `data/mcp-token`), "
             "by the stdio bridge `mcp_server.py`, and to the bundled UI through `POST /api/ui/call`. The argument tables are generated "
             "from the code (`python scripts/gen_api_doc.py`).", ""]
    for t in TOOLS:
        first, _, rest = t.description.partition("\n")
        lines += [f"## `{t.name}`", "", first]
        if rest.strip():
            lines += ["", rest.strip()]
        schema = t.input_model.model_json_schema()
        props, required = schema.get("properties", {}), set(schema.get("required", []))
        flags = ", ".join(k for k, v in t.annotations.items() if v)
        lines += ["", f"Annotations: {flags or 'none'}."]
        if props:
            lines += ["", "| Argument | Required | Description |", "|---|---|---|"]
            for name, spec in props.items():
                kind = spec.get("type") or "/".join(x.get("type", "") for x in spec.get("anyOf", []) if x.get("type"))
                if "enum" in spec:
                    kind = " \\| ".join(map(str, spec["enum"]))
                desc = (spec.get("description") or "").replace("|", "\\|")
                lines.append(f"| `{name}` ({kind}) | {'yes' if name in required else 'no'} | {desc} |")
        lines.append("")
    lines += ["## REST routes for the UI", "", "- `GET /api/health`, `GET /api/status`",
              "- `GET /api/dashboard` — active parcels sorted by estimated day, arriving today, needs attention, delivered this week, "
              "notifications since the last visit, mails to review, mail and carrier sources, scheduler.",
              "- `POST /api/dashboard/visit` — marks notifications seen and records the visit.",
              "- `GET /api/shipments/{id}` — one shipment with events, mails, similar parcels and the sources that answer for it.",
              "- `GET /api/stats` — delivery days per carrier and shop, and how accurate their dates were.",
              "- `POST /api/ui/call` `{name, arguments}` — any tool above, uncapped.", ""]
    (ROOT / "docs" / "API.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(TOOLS)} tools")
    return 0


if __name__ == "__main__":
    sys.exit(main())
