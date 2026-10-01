# Phileas's Hoard

A local shipment tracker. It reads the shipping mail in your inbox (shops, Amazon, carriers), turns it into shipments, follows each parcel with its carrier, and tells you when it should arrive and why — from the carrier's own date, the shop's date and promise, and how long your past parcels actually took.

Part of the Hoard family of local apps: it runs on your PC, keeps its data in `data/`, works on its own in the browser and can be driven by an assistant over MCP.

[Versión en español](README.es.md)

## What it does

- **Reads your mail.** Every 10 minutes it reads new mail through the account configured in Faustus (the password never leaves Faustus). Rules, not a model, decide what is shipping mail: tracking numbers with their check digits, carrier links (also inside click-tracking redirects), status phrases in ES/EN/DE/FR/IT/NL, order numbers, delivery dates and pickup notices. Food delivery, digital purchases, job applications, newsletters and your own replies are left out; doubtful mails wait in a review list.
- **One shipment per parcel.** Mails are linked by tracking number, Amazon package id, order number, the carrier's own notice about the parcel you are waiting for, or the shop's earlier mail. An order confirmation and the "shipped with UPS" mail days later end up as one shipment; two packages of one Amazon order stay apart.
- **Asks the carriers.** UPS (official API with your free developer keys, or its public tracking page read in an off-screen Edge window), Correos (its public locator), DHL (official API with a free key), and 17TRACK for everything else (one key, 100 new numbers a month free). Amazon Logistics has no public tracking, so Amazon parcels are followed from Amazon's own mails.
- **Estimates the arrival, with reasons.** The estimate combines the carrier's date (corrected by how that carrier's dates turned out on your past parcels), the shop's date ("Llega el domingo", "Se entrega: 21–24 ago"), your history with similar parcels (same carrier and origin, else same shop), the shop's promise ("al menos 48 horas… hasta 6 días laborables") and typical times. It counts delivery days, not calendar days: weekends, Spanish holidays and your region's holidays are skipped (Amazon delivers every day; Correos and InPost on Saturdays). Every estimate lists the sources it used, the confidence, and flags parcels that are running late.
- **History from day one.** The first mail read goes back 120 days and files past parcels quietly as history, so "similar parcels" and per-carrier statistics work immediately.
- **Tells you what matters.** New shipment, on its way, arriving today, ready for pickup (place, code, deadline, and a reminder two days before), delivered, incidents, a new expected date, and parcels with no news for four delivery days. Channels: Windows toast, the Hoard family bus, ntfy, Telegram and email (sent with the Faustus account). Each notification is sent once.
- **Paced checks.** Out for delivery every 30 minutes, in transit every two hours, nothing at night (23:00–07:00 by default); a source that fails is retried later.

## Screens

- **Envíos** — what arrives today, what needs attention, every parcel on its way with its estimated day, confidence, progress, last scan and the reason for the date; news since your last visit.
- **Detalle** — the estimate and every source behind it, similar past parcels, pickup data, the carrier timeline, the mails that fed it, editing, mute, archive, merge.
- **Correo** — the inbox in use, read now or search back, doubtful mails to accept or ignore, paste a mail from another inbox, detect numbers in any text.
- **Historial** — past parcels and delivery days per carrier and per shop, and how accurate their dates were.
- **Ajustes** — mail, carrier keys, region and holidays, notification channels, language, recent activity.

![Shipments](docs/shipments.png)

## Run it

Requirements: Python 3.11+, Node 22 (only to rebuild the UI), Edge or Chrome for UPS without API keys, Faustus with a mail account for automatic mail reading.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt      # Windows; venv/bin/python elsewhere
venv/Scripts/python -m phileas_hoard                          # http://127.0.0.1:5199
```

The UI is prebuilt in `phileas_hoard/static`. To rebuild it: `npm install && npx vite build`.

Settings → Correo takes the Faustus folder (or set `PHILEAS_FAUSTUS_DIR`). Without Faustus you can still paste mails, add tracking numbers by hand and use every carrier source.

Environment: `PHILEAS_PORT` (5199), `PHILEAS_DATA_DIR`, `PORT_STRICT=1`, `PHILEAS_SCHEDULER=0` (no background work), `PHILEAS_OFFLINE=1` (no network), `PHILEAS_BROWSER=0` (no browser rung). Keys can go in `.env` (see `.env.example`) or in Settings.

## Assistants (MCP)

`mcp_server.py` is a stdio MCP bridge. It never opens the database: it proxies every call to the running app with the token in `data/mcp-token`, and starts the app when it is not answering. `faustus-plugin.json` describes the app, its health check and the bridge for Faustus and the Hoard Hub.

Tools: `phileas_overview`, `phileas_status`, `shipments_list`, `shipment_get`, `shipment_add`, `shipment_update`, `shipment_delete`, `shipment_merge`, `shipment_refresh`, `eta_explain`, `mail_scan`, `mail_list`, `mail_accept`, `mail_ignore`, `mail_paste`, `mail_status`, `detect_numbers`, `track_number`, `delivery_stats`, `carriers_list`, `notifications_list`, `notify_status`, `notify_test`, `telegram_find_chat_id`, `settings_set`, `secret_set`, `scheduler_status`, `runs_list`, `housekeeping_run`. Arguments in [docs/API.md](docs/API.md).

Events on the family bus: `phileas.update` (every notification) and `phileas.status` (every status change).

## How it is built

FastAPI + SQLite (WAL) + a two-lane scheduler; React + Vite UI; carrier adapters in `phileas_hoard/carriers/`; the mail rules in `phileas_hoard/mail/parse.py`; the estimate in `phileas_hoard/eta.py`; delivery days in `phileas_hoard/bizdays.py`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Tests: `python -m pytest -q` (no network; recorded carrier answers and synthetic mails).

## Limits

- Mail is read from the accounts configured in Faustus; other inboxes need pasting.
- DHL's website forbids automated reads: DHL parcels need a DHL key or 17TRACK.
- The UPS page read can stop working if UPS changes its page; the official API is the stable path.
- Rules cover the common Spanish and European shops and carriers; an unusual mail may land in the review list.

## License

MIT
