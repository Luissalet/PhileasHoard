# Architecture

```
mail (Faustus account) ──► mail/faustus_mail.py (runs under Faustus's Python, IMAP search, HTML → text + links)
                              │ JSON lines
                              ▼
                       mail/parse.py  ── numbers.py (formats, check digits, carrier links, redirects)
                              │ MailFacts: kind, merchant, carrier, numbers, order, status, dates, promise, pickup
                              ▼
 carriers/ ◄──── engine.py ────► store.py / db.py (SQLite WAL: shipments, events, mails, notifications, runs)
 (ups, correos,     │   linking · status rules · check pacing · housekeeping
  dhl, track17,     │
  browser)          ├──► eta.py + bizdays.py (explained estimate, delivery days, holidays)
                    └──► notify/ (toast, family bus, ntfy, Telegram, email via Faustus)

scheduler.py: lane "checks" (carrier checks of due shipments) · lane "mail" (mail scan every N min, housekeeping hourly) · lane "travel" (reminders and document checks, 60 s tick)
services.py: wiring + dashboard/detail/stats views · agent_tools.py: one tool catalogue for the UI, the REST bridge and MCP
```

## Mail

`faustus_mail.py` is stdlib-only and imports nothing from Phileas: Phileas starts it with Faustus's Python inside the Faustus folder, writes one JSON request to stdin and reads one JSON line. It loads Faustus's `mcp_servers/email_server.py` to resolve accounts and connect, so passwords stay in Faustus. On Gmail it searches `[Gmail]/All Mail` with a `X-GM-RAW` query (shipping words, `newer_than:Nd`); elsewhere `SINCE` + `SUBJECT` terms. Already-read Message-IDs are skipped. Each message comes back as subject, sender, date, plain text (the HTML part converted, invisible pre-header padding removed) and its links, plus `from_self` when you sent it.

## Classification and extraction (`mail/parse.py`)

A score from evidence: tracking number (+5), status phrase in the subject or the first lines (+3; the four-step progress bar some shops print is ignored), sent by a carrier (+3), shipping or order words in the subject (+1 each), a delivery date (+1); minus food delivery and other non-parcel senders (−10), your own mail (−8), marketing subjects (−4), replies (−3). Shipping ≥ 4, maybe 2–3. Extraction: merchant from the sender's domain (and the store name for Shopify mail), carrier from the number, the sender or a phrase such as "enviado con UPS" (a bare word like "correos" is not enough), order numbers (Amazon, Google Store, generic), Amazon's package id from the tracking link, item names (quoted in the subject, or the line above a price), delivery dates and windows (relative days, weekdays, day-month, month-day), promises in hours or days (working days or calendar), pickup code, place and deadline.

## Linking (`engine._match`)

1. A tracking number already known. 2. Amazon package id. 3. The order number: the shipment without a package id when the mail brings one (a second package of the order becomes a new shipment); the one without a number when the mail brings a number. 4. A carrier's own mail without numbers: the most recent parcel of that carrier waiting for news. 5. The shop's earlier mail without any identifier. Otherwise a new shipment, except for a "delivered" note or an incident about something never seen.

## Status rules (`engine.apply_status`)

Statuses have a progress order. A status moves forward on any news; it moves back only on newer news from a carrier (not from an older mail); incidents apply when newer; "not found" never hides a known status; a final status (delivered, returned) is never undone automatically. Milestones are kept: ordered, shipped, first scan, out for delivery, delivered.

## Carrier sources (`carriers/`)

| Carrier | Order |
|---|---|
| UPS | official API (`UPS_CLIENT_ID/SECRET`) → public page in the off-screen browser → 17TRACK |
| Correos | public locator JSON → 17TRACK |
| DHL | official API (`DHL_API_KEY`) → 17TRACK |
| Amazon Logistics | mail only |
| others | 17TRACK (`TRACK17_KEY`) |

The browser rung opens a real Edge window placed off-screen (carrier sites refuse headless browsers) with its own profile in `data/browser-profile`, and reads the JSON the page's own script loads. It never solves challenges. Every adapter returns a `TrackResult` (status, events, carrier dates, origin, destination, service) and the last raw answer is kept in `data/raw/<shipment>.json`.

## Estimate (`eta.py`)

Candidates, each a window with a weight: carrier date (shifted by the carrier's average lateness on your past parcels when it is at least half a day), shop date (Amazon's are trusted more), history of similar parcels (20th–85th percentile of delivery days from the shipping day, matched by carrier and origin, then shop and carrier, then shop, then carrier, at least two parcels), the shop's promise, typical times per carrier and origin zone. The heaviest window that is not in the past decides; overlapping windows raise the confidence and the carrier's or shop's date narrows a statistical window. When the carrier's and the shop's dates have all passed, the parcel is marked late and the window restarts today. Delivered, out for delivery today and waiting at a pickup point short-circuit the rest.

## Checks and housekeeping

Next check by status (30 min out for delivery, 1 h incidents or arriving within a day, 2 h in transit, 3 h label or customs, 6 h pickup, 2 h then 6 h not found), at least 1 h for the browser rung, backoff after failures, nothing between 23:00 and 07:00. Hourly housekeeping archives deliveries after five days, assumes delivery of mail-only parcels the day after "out for delivery", gives up numbers the carrier never knew after 14 days, flags parcels with no news for four delivery days and reminds pickup deadlines.

## Travel (`phileas_hoard/travel/`)

```
mail ──► engine.ingest ──► parcel rules (mail/parse.py) ──► shipments
              │
              └─► travel/service.process_mail ──► analyze.py (score: schema 80, known sender 45, booking words 25, reference 15, drafts 20; candidate ≥ 60)
                                                     │
        extract.py (schema.org JSON-LD / microdata) ─┤
        rules.py + scan.py (sender rules, reading-order tokens, leg state machine) ─┤
        llm.py (local model through Hoard Link, JSON schema; evidence quoted from the mail is checked) ─┘
                                                     ▼  SegmentDraft (draft.py: airports, time zones, canonical city names)
        service._file ──► segments.py (match by booking reference + leg, change/cancel/stale, merge fields) ──► store.py (SQLite)
                              └─► trips.regroup (deterministic grouping; locked segments are anchors; trip ids are reused by vote)
```

Tables (migration 2): `trips`, `segments`, `segment_mails`, `trip_people`, `trip_expenses`, plus `notifications.trip_id`. Times are stored as local wall-clock time plus an IANA zone and the derived UTC instants (`dep_ts`, `arr_ts`); duration, check-in windows and the calendar file are computed from the instants, so daylight-saving changes come out right.

- **Live window and history repair (`engine.py`).** A mail older than `mail.history_days` (default 30) is filed the quiet way even when a deep scan (`since_days`, a query) fetches it: a new parcel from it is created as history, and settled (archived, or delivered when it was out for delivery) when nothing newer than the window exists for it (`Engine._settle_if_stale`). A parcel's newest activity is its newest carrier or mail event; bookkeeping times (created, last checked) never count. `Engine.history_repair(dry_run)` applies the same rule to existing parcels that are neither delivered nor archived (parcels added by hand are left alone); it runs once at start (flag `housekeeping.history_repair`) and as the tool `shipments_history_repair`. Surplus-food and meal apps are noise by sender or sender name; `parse.has_price` keeps a price line from becoming an item label.
- **Booking evidence (`analyze.py`).** A mail is a travel candidate only with schema.org reservation markup, or a booking reference found next to a label (locator, PNR, confirmation number) plus an itinerary element (legs read by the rules, a dated line with a time, or a route between two places); a cancellation or change with a reference also counts, and so does a known travel sender whose dated legs were read from a booking-worded mail. A sender, booking words or a score alone never decide, so marketing, preference-centre mails, surveys and generic passenger notices fall through to the parcel pass as noise. Event tickets without markup are not travel; schema.org events count only with a date and a place away from the home city (`Travel._event_not_travel`), and a mail pasted by hand always counts. `Travel.recheck_review` re-runs the gate over the review list (once per database at start, flag `travel.review_gate`; also the tool `travel_mail_recheck`) and moves the rest to `noise`/`skipped`; pasted mails and mails with something read from them stay.
- **Reading order.** The mail helper returns HTML only for mail that carries schema.org reservation markup. Schema markup is read first; sender rules second; the model only for mail already scored as a booking that neither could read, at most 6 per batch. A model result is flagged `source: model`, keeps the quoted lines (an invented segment whose quote is not in the mail is dropped) and goes to the review list. `no_model` is reported, never replaced by a guess.
- **Trips (`trips.py`).** Segments are clustered by start date with a gap in days, and one joins a trip only when it is connected to it: it starts where the traveller is (the last place reached, or a stay covering that day), it is a stay, car or activity in a place the trip visits, or it shares the booking reference. Anything else starts a trip of its own, so trips may overlap. Airports of one metropolitan area (for example MAD and TOJ, BCN and GRO) count as the same place. The trip title uses the place where the traveller stays longest, not a connection at a hub; a cluster that has come back where it began is closed; a long stay's way back joins the trip that left (up to 45 days); cancelled legs still count for where a trip began and ended. Home (city, airports) decides when the cluster touches it; otherwise the cluster's own first place does. Segments you place or edit are locked and anchor their trip.
- **Deleting (`ops.delete_trip`, migration 3).** Deleting a trip deletes its segments and writes each one to `deleted_segments` (key from kind, booking reference and route, else number, route and day, plus the mails it came from); `_file` skips a draft whose key is there, so a re-read, a change or a cancellation mail never recreates it. A paste, accepting a mail from review or adding the segment by hand restores it on purpose. `keep_segments` detaches the segments and marks them `extra.no_trip`; the grouping skips them until one is moved to a trip.
- **Check-in (`checkin.py`).** A table of airline windows with source and date checked; states `not_open`, `open`, `closed`, `done`, `unknown_open`.
- **Reminders (`service.tick`).** Trip tomorrow, check-in opens, check-in closes in 3 h and not done, stay day, departure in N hours, changes, cancellations and document problems go through the notifier with a once-only key per event. During the night silence they wait in a persistent queue and go out in the morning, unless they are urgent.
- **Other Hoards (`hubcalls.py`).** Kafka (`docs_list`, `deadlines_list`) and Ledger (`list_accounts`, `list_categories`, `add_entry`) are called through `family.call`; hub down, app down, missing tool and not authorised are distinct, non-fatal answers.
- **Expenses (`expenses.py`).** Integer cents, largest-remainder apportioning, base currency plus a typed rate per expense; the minimum number of transfers is exact (subsets that balance among themselves, up to 16 people) and greedy beyond.
- **Calendar (`ics.py`).** RFC 5545 with UTC times, all-day stays, line folding and an absolute alarm at check-in opening.
- **Airports (`airports.py`).** `tables/airports.json` from `scripts/gen_airports.py` (airportsdata, MIT).
