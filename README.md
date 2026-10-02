# Phileas's Hoard

A local shipment and trip tracker. It reads the shipping mail in your inbox (shops, Amazon, carriers), turns it into shipments, follows each parcel with its carrier, and tells you when it should arrive and why — from the carrier's own date, the shop's date and promise, and how long your past parcels actually took. The same mail pass reads travel bookings (flights, trains, buses, ferries, car rental, stays), groups them into trips, reminds you about check-in and shares the trip's expenses.

Part of the Hoard family of local apps: it runs on your PC, keeps its data in `data/`, works on its own in the browser and can be driven by an assistant over MCP.

[Versión en español](README.es.md)

## What it does

- **Reads your mail.** Every 10 minutes it reads new mail through the account configured in Faustus (the password never leaves Faustus). Rules, not a model, decide what is shipping mail: tracking numbers with their check digits, carrier links (also inside click-tracking redirects), status phrases in ES/EN/DE/FR/IT/NL, order numbers, delivery dates and pickup notices. Food delivery, digital purchases, job applications, newsletters and your own replies are left out; doubtful mails wait in a review list.
- **One shipment per parcel.** Mails are linked by tracking number, Amazon package id, order number, the carrier's own notice about the parcel you are waiting for, or the shop's earlier mail. An order confirmation and the "shipped with UPS" mail days later end up as one shipment; two packages of one Amazon order stay apart.
- **Asks the carriers.** UPS (official API with your free developer keys, or its public tracking page read in an off-screen Edge window), Correos (its public locator), DHL (official API with a free key), and 17TRACK for everything else (one key, 100 new numbers a month free). Amazon Logistics has no public tracking, so Amazon parcels are followed from Amazon's own mails.
- **Estimates the arrival, with reasons.** The estimate combines the carrier's date (corrected by how that carrier's dates turned out on your past parcels), the shop's date ("Llega el domingo", "Se entrega: 21–24 ago"), your history with similar parcels (same carrier and origin, else same shop), the shop's promise ("al menos 48 horas… hasta 6 días laborables") and typical times. It counts delivery days, not calendar days: weekends, Spanish holidays and your region's holidays are skipped (Amazon delivers every day; Correos and InPost on Saturdays). Every estimate lists the sources it used, the confidence, and flags parcels that are running late.
- **History from day one.** The first mail read goes back 120 days and files past parcels quietly as history, so "similar parcels" and per-carrier statistics work immediately. The same rule holds for any later deep scan (`since_days` or a query): a mail older than `mail.history_days` (default 30) only ever feeds the history, never an active parcel, and never notifies. Parcels already stuck as active with nothing newer than that window are moved to the history once at start, or on demand with `shipments_history_repair` (dry run by default). Surplus-food and meal apps (Too Good To Go, meal boxes, food platforms) are left out like food delivery, and a line that states an amount is never used as the item label.
- **Tells you what matters.** New shipment, on its way, arriving today, ready for pickup (place, code, deadline, and a reminder two days before), delivered, incidents, a new expected date, and parcels with no news for four delivery days. Channels: Windows toast, the Hoard family bus, ntfy, Telegram and email (sent with the Faustus account). Each notification is sent once.
- **Reads travel bookings.** In the same pass, booking mail becomes *segments*: flight, train, bus, ferry, car rental, stay, activity. Only mail with real booking evidence counts: reservation markup, or a booking reference (locator, PNR, confirmation number) together with something concrete to travel (a dated departure or check-in with a time, or a route between two places). Marketing from airlines and agencies, loyalty and preference mails, surveys and notices to every passenger are left out and never reach the review list; tickets for a show or a film are left out unless they carry a place away from home (or you add them to a trip by hand). Mails already waiting in the review list are checked again once on start (and with `travel_mail_recheck`) and the ones that were never bookings are dropped. Order of reading: schema.org reservation markup in the mail (JSON-LD and microdata), then rules for the common senders (Iberia, Iberia Express, Vueling, Air Europa, Ryanair, easyJet, Volotea, Binter, TAP, Lufthansa, British Airways, Air France and KLM, Renfe, Iryo, Ouigo, Alsa, FlixBus, Baleària, hotel and holiday-rental confirmations, car rental, online travel agencies), then — only for mail already known to be a booking that the rules cannot read — the local model through Hoard Link. Whatever the model reads is marked *leído por el modelo local*, keeps the lines of the mail it is based on, never files itself and waits in the review list (Correo → Viajes). With no model available the mail stays in review and nothing is invented. A change or cancellation mail updates or cancels the segment it refers to; an older mail never overwrites a newer one. Airports come from a local IATA table (name, city, country, time zone), so departure and arrival times keep their own time zone, including across daylight-saving changes.
- **Groups them into trips.** Outbound, stays, car and return are grouped by the home city and airports in Settings and the gap in days between segments, with titles like “Lisboa · 12–15 nov 2026”. A segment joins a trip only when it is connected to it (it starts where you are, is a stay or car in a place the trip visits, or shares the booking reference); otherwise it starts its own trip, so two people’s bookings or a separate business trip can overlap. Airports of the same area (MAD/TOJ, BCN/GRO) count as one place. A trip that never touches home is grouped by its own first place. You can rename a trip (or go back to the automatic title), merge two, split segments off, move one segment, delete a trip (its bookings go too and are remembered as deleted, so reading the same mail again does not bring them back; `keep_segments` keeps them without a trip), add segments by hand or paste a mail. Statuses: upcoming, ongoing, past, cancelled. Segments you edit or place by hand stay where you put them.
- **Check-in and trip reminders.** For flights it knows the online check-in window of Ryanair, easyJet, Vueling, Iberia and Air Europa (table in `phileas_hoard/travel/checkin.py`, with source and the date it was checked, 2026-10-02; also shown in Settings). Any other airline is “unknown”: a reminder 24 h before saying to check with the airline. Notifications, each sent once, with the night silence of the parcel checks: trip tomorrow, check-in opens (with the link), check-in closes in 3 hours and you have not marked it done, stay check-in day, departure in N hours (configurable), a segment changed or cancelled, a document problem.
- **Documents from Kafka.** Through the Hoard hub it lists the identity documents and their expiry deadlines and warns when an ID card or passport expires before the trip's last day (a passport is asked for when the trip leaves the Schengen area). Document numbers are never read or shown. With Kafka or the hub down the answer is “no se pudo comprobar”, not an error.
- **Shared expenses per trip.** People, expenses (who paid, split equally, by shares or exact amounts, date, category), balances and the fewest transfers that settle them (exact up to 16 people with a balance). Each trip has a base currency; an expense in another currency carries the rate you type (no rates are fetched). A booking's price becomes an expense with one click. “Pasar mi parte a Ledger” sends my share of each expense not yet sent to Ledger's Hoard through the hub, remembers what was sent and never sends it twice; with Ledger down it says why.
- **Calendar.** A `.ics` file per trip or for every upcoming trip: one event per segment with the right time zone, an all-day event for stays, and an alarm when check-in opens.
- **Works with the family hub.** *Alerts:* with `notify.via` = `auto` (default) every parcel and trip alert goes out as one notification to the hub, which decides the channels, the quiet hours and the work/personal sphere; if the hub does not answer, Phileas uses its own channels (toast, ntfy, Telegram, email) as before. `hub` uses only the hub, `own` never calls it; the family bus event stays separate. *Mail:* with `mail.source` = `auto` (default) shipping and booking mail is read from the hub's mail gateway when it is ready (Phileas registers an interest: the shipping and booking words and the sender domains of the shops and carriers it knows, and reads from a stored position), otherwise through Faustus as before; `hub` and `faustus` force one. Every mail that becomes a parcel or a trip is claimed in the hub (`hoard://phileas/shipment/<id>`, `hoard://phileas/trip/<id>`). A deep read (another day range, or a search) still goes to the Faustus reader when there is one; the hub does not carry the structured booking markup (JSON-LD), so trips from hub mail are read from the text. *Agenda:* `GET /api/family/agenda` lists expected delivery days, pickup deadlines, trips and the departures of their flights, trains, buses and ferries; nothing that is over is listed, and a late parcel stays on its expected day. *Events:* `phileas.shipment.new` and `phileas.shipment.delivered` carry the purchase data other apps use (see below); `phileas.status` is sent only for a real change of a live parcel.
- **Paced checks.** Out for delivery every 30 minutes, in transit every two hours, nothing at night (23:00–07:00 by default); a source that fails is retried later.

## Screens

- **Envíos** — what arrives today, what needs attention, every parcel on its way with its estimated day, confidence, progress, last scan and the reason for the date; news since your last visit.
- **Detalle** — the estimate and every source behind it, similar past parcels, pickup data, the carrier timeline, the mails that fed it, editing, mute, archive, merge.
- **Correo** — the inbox in use, read now or search back, doubtful mails to accept or ignore, paste a mail from another inbox, detect numbers in any text.
- **Historial** — past parcels and delivery days per carrier and per shop, and how accurate their dates were.
- **Ajustes** — mail, trips, carrier keys, region and holidays, notification channels, language, recent activity.
- **Viajes** — trips on now with the “today” view, check-ins to do, upcoming trips, past and cancelled ones; paste a booking, new trip, calendar download.
- **Viaje** — one trip: check-in state of each flight, documents check, day-by-day timeline, every booking with its links, mails and evidence, segment editor, merge/split/move, and the Gastos tab with people, expenses, balances, settle-up and the Ledger button. The Correo screen has a Viajes tab for the bookings that wait for review.

![Shipments](docs/shipments.png)

## Run it

Requirements: Python 3.11+, Node 22 (only to rebuild the UI), Edge or Chrome for UPS without API keys, Faustus with a mail account for automatic mail reading.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt      # Windows; venv/bin/python elsewhere
venv/Scripts/python -m phileas_hoard                          # http://127.0.0.1:5199
```

The UI is prebuilt in `phileas_hoard/static`. To rebuild it: `npm install && npx vite build`.

Settings → Correo takes the Faustus folder (or set `PHILEAS_FAUSTUS_DIR`) and where mail is read (`mail.source`); Settings → Notifications has the alert delivery (`notify.via`) with a test button for the hub. Without Faustus you can still paste mails, add tracking numbers by hand and use every carrier source.

Travel settings (Settings → Viajes): `travel.enabled`, home city, home airports and time zone, days between segments of one trip, which kinds are read (`travel.kinds`), departure reminder hours, hour of the “trip tomorrow” reminder, my name in expenses, model fallback, documents check and its lead days, default Ledger account. Trips are read from the same mail window as parcels; the first read files past bookings quietly as history.

Environment: `PHILEAS_PORT` (5199), `PHILEAS_DATA_DIR`, `PORT_STRICT=1`, `PHILEAS_SCHEDULER=0` (no background work), `PHILEAS_OFFLINE=1` (no network), `PHILEAS_BROWSER=0` (no browser rung). Keys can go in `.env` (see `.env.example`) or in Settings.

## Assistants (MCP)

`mcp_server.py` is a stdio MCP bridge. It never opens the database: it proxies every call to the running app with the token in `data/mcp-token`, and starts the app when it is not answering. `faustus-plugin.json` describes the app, its health check and the bridge for Faustus and the Hoard Hub.

Parcel tools: `phileas_overview`, `phileas_status`, `shipments_list`, `shipment_get`, `shipment_add`, `shipment_update`, `shipment_delete`, `shipment_merge`, `shipment_refresh`, `eta_explain`, `mail_scan`, `mail_list`, `mail_accept`, `mail_ignore`, `mail_paste`, `mail_status`, `shipments_history_repair`, `detect_numbers`, `track_number`, `delivery_stats`, `carriers_list`, `notifications_list`, `notify_status` (also says whether alerts go through the hub now), `notify_test` (`via: hub` tests the hub), `telegram_find_chat_id`, `settings_set`, `secret_set`, `scheduler_status`, `runs_list`, `housekeeping_run`.

Travel tools: `travel_overview`, `trips_list`, `trip_get`, `trip_create`, `trip_update` (rename, mute, cancel, merge, split, move a segment, delete), `segment_add`, `segment_update`, `segment_delete`, `checkin_status`, `checkin_done`, `trip_documents_check`, `trip_people`, `trip_expenses`, `trip_expense_add`, `trip_expense_update`, `trip_expense_delete`, `trip_settle`, `trip_to_ledger`, `trip_ics`, `trip_paste`, `travel_mail_list`, `travel_mail_read_again`, `travel_mail_recheck`. Arguments in [docs/API.md](docs/API.md).

Events on the family bus: `phileas.update` (every parcel notification), `phileas.status` (`shipment_id, from, to, label, source`: a real status change of a live parcel; not its first status, not the history, not the same status again), `phileas.shipment.new` and `phileas.shipment.delivered` (`shipment_id, merchant, order_ref, message_id, items, carrier, tracking_number`, plus `delivered_at` on delivery; sent for live mail only, never for the first import or old mail); for trips, `phileas.trip.new` (a trip is created), `phileas.trip.changed` (its segments or dates changed), `phileas.checkin.open` (a flight's check-in opens) and `phileas.trip.update` (every trip notification, through the hub channel). Payloads carry ids, titles and dates only.

## Airport data

`phileas_hoard/travel/tables/airports.json` is generated by `scripts/gen_airports.py` from the `airportsdata` package (MIT licence; it derives from the public airport list by mwgg, copyright 2014 mwgg, MIT). Only IATA code, name, city, country and time zone are kept; the package is not needed at run time.

## How it is built

FastAPI + SQLite (WAL) + a three-lane scheduler (checks, mail, travel); React + Vite UI; carrier adapters in `phileas_hoard/carriers/`; the travel facet in `phileas_hoard/travel/` (reading, trips, check-in, expenses, calendar) with its tools in `phileas_hoard/travel_tools.py`; the mail rules in `phileas_hoard/mail/parse.py`; the estimate in `phileas_hoard/eta.py`; delivery days in `phileas_hoard/bizdays.py`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Tests: `python -m pytest -q` (no network; recorded carrier answers and synthetic mails).

## Limits

- Mail is read from the accounts configured in Faustus, directly or through the hub's mail gateway; other inboxes need pasting. The hub only holds the mail it was set to read (its window and retention), so a deep read of older mail needs the Faustus reader.
- DHL's website forbids automated reads: DHL parcels need a DHL key or 17TRACK.
- The UPS page read can stop working if UPS changes its page; the official API is the stable path.
- Rules cover the common Spanish and European shops and carriers; an unusual mail may land in the review list.
- Travel: there is no live flight status (delays, gates and cancellations are known only from mail), and no airline or rail account is used. The sender rules and the layouts they read were built from invented sample mails: a real mail with another layout lands in the review list, and the model pass reads it only when a local model is available. Prices are read only when the mail states a total.
- Check-in windows are the ones the airlines published when checked (2026-10-02) and may change; Vueling's closing time outside the Schengen area is not published in the table (no closing reminder for those flights), and Iberia Express is treated as an airline whose rule is unknown. Air Europa's closing time is set to 60 minutes, the conservative end of 45–60.
- Expenses use the rate you type; the Ledger transfer needs the hub, Ledger running, and an account in the trip's currency. Trip titles are written in the language that was active when the trip was created.

## License

MIT
