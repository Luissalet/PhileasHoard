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
              "notifications since the last visit, mails to review, mail and carrier sources, scheduler, and a `travel` block "
              "(trips on now, next trip, check-ins to do, travel mails to review).",
              "- `POST /api/dashboard/visit` — marks notifications seen and records the visit.",
              "- `GET /api/shipments/{id}` — one shipment with events, mails, similar parcels and the sources that answer for it.",
              "- `GET /api/stats` — delivery days per carrier and shop, and how accurate their dates were.",
              "- `GET /api/trips/ics` — calendar file (`text/calendar`) with every upcoming and ongoing trip; `?trip=<id or title>` for one.",
              "- `GET /api/trips/{id}/ics` — calendar file of one trip: a VEVENT per segment, times in UTC, an alarm when check-in opens.",
              "- `GET /api/family/agenda?from=&to=&sphere=` — the family agenda contract (Bearer token of this app): expected deliveries "
              "(`delivery`), pickup deadlines (`deadline`), trips and the departures of their flights, trains, buses and ferries (`other`). "
              "Nothing that is over is listed; a late parcel stays on its expected day.",
              "- `POST /api/ui/call` `{name, arguments}` — any tool above, uncapped.", "",
              "## Events on the family bus", "",
              "Emitted through Hoard Link (`family.emit`); the payload carries ids and short titles only.", "",
              "| Event | When | Payload |", "|---|---|---|",
              "| `phileas.trip.new` | a trip is created from a mail or by hand | `trip_id`, `title`, `start_date`, `end_date` |",
              "| `phileas.trip.changed` | a trip's segments or dates change (a booking changed, cancelled, merged, split or moved) | `trip_id`, `title`, `start_date`, `end_date` |",
              "| `phileas.checkin.open` | a flight's online check-in opens | `trip_id`, `segment_id`, `number`, `from`, `to`, `dep_local` |",
              "| `phileas.trip.update` | every notification about a trip, through the hub channel | `event_id`, `type`, `severity`, `title`, `summary`, `trip_id`, `segment_id`, `trip_title`, `start_date`, `end_date`, `url` |",
              "| `phileas.update` | every notification about a parcel, through the hub channel (unchanged) | `event_id`, `type`, `severity`, `title`, `summary`, `shipment_id`, … |",
              "| `phileas.shipment.new` | a parcel is created from a live mail (never for the first import or old mail) | `shipment_id`, `merchant`, `order_ref`, `message_id`, `items`, `carrier`, `tracking_number` |",
              "| `phileas.shipment.delivered` | a parcel becomes delivered (carrier, mail or by hand; never for history) | the same, plus `delivered_at` (local ISO time) |",
              "| `phileas.status` | a parcel's status really changes (not for its first status, not for history, not when the same status arrives again) | `shipment_id`, `from`, `to`, `label`, `source` |", ""]
    (ROOT / "docs" / "API.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(TOOLS)} tools")
    return 0


if __name__ == "__main__":
    sys.exit(main())
