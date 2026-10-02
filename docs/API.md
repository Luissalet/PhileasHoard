# Phileas's Hoard — agent tools

Every tool is served by the app at `GET /api/agent/tools` and `POST /api/agent/call` (Bearer token from `data/mcp-token`), by the stdio bridge `mcp_server.py`, and to the bundled UI through `POST /api/ui/call`. The argument tables are generated from the code (`python scripts/gen_api_doc.py`).

## `phileas_overview`

Parcels on their way with estimated arrival, today, needs attention. Mis envíos y cuándo llegan.

Active shipments sorted by estimated day, what arrives today, problems (incidence, failed attempt, pickup waiting, late), deliveries of the last week, notifications since the last visit. Sinónimos: paquetes, pedidos, seguimiento, qué me llega, cuándo llega, envíos pendientes, tracking.

Annotations: readOnlyHint, idempotentHint.

## `phileas_status`

Health: mail source, carrier sources, channels, scheduler, settings. Estado de Phileas.

Sinónimos: configuración, claves, canales de aviso, último escaneo de correo.

Annotations: readOnlyHint, idempotentHint.

## `shipments_list`

List shipments (active, delivered, all, archived, history) with filters. Lista de envíos.

Sinónimos: buscar envío, pedidos de Amazon, paquetes de UPS, historial.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `filter` (active \| delivered \| all \| archived \| history) | no |  |
| `text` (string) | no | Matches label, item, shop, tracking number or order number. |
| `carrier` (string) | no |  |
| `merchant` (string) | no |  |
| `limit` (integer) | no |  |

## `shipment_get`

One shipment: status, estimate, carrier events, mails, similar parcels. Detalle de un envío.

Accepts the id, the tracking number or the order number. Sinónimos: dónde está mi paquete, seguimiento de X.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `shipment` (string) | yes | Shipment id (s_…), tracking number or order number. |

## `shipment_add`

Track a parcel by its tracking number (carrier guessed if empty). Añadir seguimiento a mano.

Sinónimos: sigue este número, añade este envío, tracking.

Annotations: idempotentHint, openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `tracking_number` (string) | yes |  |
| `carrier` (string) | no | ups, correos, dhl, seur, gls, mrw, nacex, ctt, inpost, fedex, yunexpress… Empty = guess. |
| `label` (string) | no | What it is, e.g. «Portátil PCSpecialist». |
| `merchant` (string) | no |  |
| `notes` (string) | no |  |
| `check_now` (boolean) | no |  |

## `shipment_update`

Edit a shipment: label, carrier, number, notes, archive, mute, status. Editar envío.

Sinónimos: renombrar, silenciar avisos, archivar, marcar como entregado.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `shipment` (string) | yes |  |
| `label` (string/null) | no |  |
| `item` (string/null) | no |  |
| `merchant` (string/null) | no |  |
| `carrier` (string/null) | no |  |
| `tracking_number` (string/null) | no |  |
| `origin_country` (string/null) | no | ISO country the parcel leaves from, e.g. NL. |
| `notes` (string/null) | no |  |
| `archived` (boolean/null) | no |  |
| `muted` (boolean/null) | no | No notifications for this parcel. |
| `status` (string/null) | no | Set by hand: ordered, label_created, not_found, in_transit, customs, out_for_delivery, available_for_pickup, failed_attempt, exception, delivered, returned, unknown. |

## `shipment_delete`

Delete a shipment and its events (confirm=true). Borrar envío.

Annotations: destructiveHint.

| Argument | Required | Description |
|---|---|---|
| `shipment` (string) | yes |  |
| `confirm` (boolean) | no |  |

## `shipment_merge`

Merge two shipments that are the same parcel (confirm=true). Fusionar envíos duplicados.

Annotations: destructiveHint.

| Argument | Required | Description |
|---|---|---|
| `keep` (string) | yes |  |
| `drop` (string) | yes |  |
| `confirm` (boolean) | no |  |

## `shipment_refresh`

Ask the carrier now for one shipment. Comprobar ya un envío.

Sinónimos: actualiza, mira cómo va, refresca el seguimiento.

Annotations: idempotentHint, openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `shipment` (string) | yes | Shipment id (s_…), tracking number or order number. |

## `eta_explain`

Why the estimated date: sources used, carrier track record, similar past parcels. Explicar la fecha estimada.

Sinónimos: cuándo llega, por qué esa fecha, envíos parecidos, retraso.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `shipment` (string) | yes | Shipment id (s_…), tracking number or order number. |

## `mail_scan`

Read new shipping mail now (or search back N days / a query). Leer el correo ya.

Sinónimos: revisa el correo, busca el correo de la tienda, importar pedidos.

Annotations: idempotentHint, openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `since_days` (integer/null) | no | How far back to read (default: the configured window). |
| `query` (string) | no | Optional search, e.g. a shop name or a tracking number. |

## `shipments_history_repair`

Move old stuck parcels to the history (dry run first). Limpiar envíos antiguos del listado activo.

Parcels whose newest mail, carrier event and change are older than mail.history_days (default 30) and that are not delivered or archived go to the history quietly. dry_run=true (default) only lists them. Sinónimos: envíos viejos activos, limpiar historial, reparar envíos.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `dry_run` (boolean) | no | Only report what would move to the history (default). Pass false to do it. |

## `mail_list`

Mails Phileas read: to review (maybe), shipping, noise. Correos leídos y dudosos.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `kind` (maybe \| shipping \| noise \| travel \| all) | no |  |
| `state` (new \| linked \| ignored \| skipped \| all) | no |  |
| `limit` (integer) | no |  |

## `mail_accept`

Turn a doubtful mail into a shipment update. Aceptar correo dudoso como envío.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `message_id` (string) | yes |  |

## `mail_ignore`

Ignore a doubtful mail. Ignorar correo dudoso.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `message_id` (string) | yes |  |

## `mail_paste`

File a shipping mail pasted as text (shops outside the inbox). Pegar un correo de envío.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `subject` (string) | no |  |
| `text` (string) | yes | The mail body as plain text. |
| `from_address` (string) | no |  |

## `mail_status`

Which inbox Phileas reads (account in Faustus) and whether it answers. Estado del correo.

Annotations: readOnlyHint, idempotentHint, openWorldHint.

## `detect_numbers`

Find tracking numbers and carriers in any text. Detectar números de seguimiento.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `text` (string) | yes |  |

## `track_number`

One-off lookup of a tracking number without saving it. Consultar un número sin guardarlo.

Annotations: readOnlyHint, idempotentHint, openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `tracking_number` (string) | yes |  |
| `carrier` (string) | no |  |

## `delivery_stats`

Delivery days per carrier and shop on past parcels, and how accurate their dates were. Estadísticas.

Sinónimos: cuánto tarda UPS, qué transportista es más rápido, retrasos habituales.

Annotations: readOnlyHint, idempotentHint.

## `carriers_list`

Known carriers and which source answers for each. Transportistas y fuentes.

Annotations: readOnlyHint, idempotentHint.

## `notifications_list`

Notifications sent (newest first). Avisos enviados.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `limit` (integer) | no |  |

## `notify_status`

Notification channels: toast, hub, ntfy, Telegram, email. Canales de aviso.

Annotations: readOnlyHint, idempotentHint.

## `notify_test`

Send a test notification through one channel or the family hub. Probar un canal de aviso.

Annotations: openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `channel` (toast \| hub \| ntfy \| telegram \| email) | no |  |
| `via` (own \| hub) | no | hub = a sample notification through the family hub's notification centre (it decides the channels); own = test the channel itself. |

## `telegram_find_chat_id`

Find and save the Telegram chat id after writing to the bot. Buscar chat de Telegram.

Annotations: idempotentHint, openWorldHint.

## `settings_set`

Change settings (mail source, alert delivery, mail interval, holidays region, channels…). Cambiar ajustes.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `values` (object) | yes | Setting key -> value. See phileas_status → settings for the keys. |

## `secret_set`

Store a key (17TRACK, UPS, DHL, Telegram, ntfy, SMTP). Guardar una clave.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `name` (TRACK17_KEY \| UPS_CLIENT_ID \| UPS_CLIENT_SECRET \| DHL_API_KEY \| FAUSTUS_DIR \| TELEGRAM_TOKEN \| TELEGRAM_CHAT_ID \| NTFY_TOPIC \| NTFY_TOKEN \| SMTP_HOST \| SMTP_PORT \| SMTP_USER \| SMTP_PASSWORD \| SMTP_FROM \| SMTP_TO) | yes |  |
| `value` (string) | no | Empty clears it. |

## `scheduler_status`

Background jobs: lanes, queue, last mail scan. Estado del planificador.

Annotations: readOnlyHint, idempotentHint.

## `runs_list`

Recent mail scans and carrier checks with their result. Últimas comprobaciones.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `limit` (integer) | no |  |

## `housekeeping_run`

Archive old deliveries, flag stale parcels, pickup reminders, refresh estimates. Mantenimiento.

Annotations: idempotentHint.

## `travel_overview`

Trips on now, next trip, check-ins to do, mails to review. Mis viajes de un vistazo.

What is happening today on a trip in progress, the next trip with days to go, flights whose online check-in is open or about to open, bookings from mail waiting for review and counts. Sinónimos: viajes, qué viaje tengo, mi próximo viaje, qué hago hoy de viaje, check-in pendiente.

Annotations: readOnlyHint, idempotentHint.

## `trips_list`

List trips (upcoming, ongoing, past, cancelled, all). Lista de viajes.

Each trip has title, dates, destination, status, days to go, kinds of segments and what needs review. Sinónimos: mis viajes, viajes pasados, viajes cancelados, cuándo es mi próximo viaje.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `filter` (upcoming \| ongoing \| past \| cancelled \| active \| all) | no |  |

## `trip_get`

One trip: segments, day-by-day timeline, links, people, expenses and balances. Detalle de un viaje.

Takes the trip id or its exact title. Segments carry check-in state, times with their time zone and the mails they came from. Sinónimos: vuelos de mi viaje, dónde me alojo, a qué hora sale, itinerario, enlaces de la reserva.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |

## `trip_create`

Create a trip by hand with a title and dates. Crear un viaje.

Sinónimos: nuevo viaje, apunta un viaje, viaje sin reservas.

Annotations: none.

| Argument | Required | Description |
|---|---|---|
| `title` (string) | yes |  |
| `start_date` (string) | no | YYYY-MM-DD; filled from the segments once there are some. |
| `end_date` (string) | no |  |
| `currency` (string) | no | Base currency of the trip's shared expenses. |
| `notes` (string) | no |  |

## `trip_update`

Rename, mute, cancel, merge, split a trip or move a segment between trips. Editar un viaje.

merge_from (confirm=true) merges another trip into this one; split_segments moves some segments into a new trip; move_segment + to_trip moves one segment ('new' = its own trip, empty = let the grouping place it); delete (confirm=true) removes the trip and its bookings (keep_segments=true keeps them without a trip). Sinónimos: renombrar viaje, unir viajes, separar viaje, mover vuelo a otro viaje, silenciar avisos del viaje.

Annotations: destructiveHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |
| `title` (string/null) | no | Rename. An empty string gives the automatic title back. |
| `notes` (string/null) | no |  |
| `currency` (string/null) | no |  |
| `pinned` (boolean/null) | no | Keep the trip even with no segments. |
| `muted` (boolean/null) | no | No reminders for this trip. |
| `cancelled` (boolean/null) | no | Mark the whole trip cancelled (or not). |
| `merge_from` (string/null) | no | Another trip (id or title) to merge INTO this one; needs confirm=true. |
| `split_segments` (array/null) | no | Segment ids to split off into a new trip (not all of them). |
| `split_title` (string) | no | Title for the trip created by split_segments. |
| `move_segment` (string/null) | no | Segment id to move. |
| `to_trip` (string) | no | With move_segment: target trip id or title, 'new' for a trip of its own, or empty to let the grouping place it again. |
| `delete` (boolean) | no | Delete the trip AND its bookings (they are remembered as deleted, so reading the same mail again does not bring them back); needs confirm=true. |
| `keep_segments` (boolean) | no | With delete: keep the bookings instead, detached and marked 'no trip' (the grouping leaves them alone). |
| `confirm` (boolean) | no |  |

## `segment_add`

Add a flight, train, bus, ferry, car rental, stay or activity by hand. Añadir un tramo o reserva.

Times are local at the place; the airport table fills the city and time zone from IATA codes. Sinónimos: añade un vuelo, apunta un hotel, añadir reserva, he comprado un billete de tren, alquiler de coche.

Annotations: none.

| Argument | Required | Description |
|---|---|---|
| `carrier` (string/null) | no | Airline, rail or bus company. |
| `number` (string/null) | no | Flight number like IB3166, train number or bus line. |
| `booking_ref` (string/null) | no | Booking reference (localizador / PNR). |
| `provider` (string/null) | no | Hotel, rental company or host (stays and cars). |
| `from_code` (string/null) | no | IATA airport code (flights). |
| `from_name` (string/null) | no | Station, port, pick-up point or the stay's name. |
| `to_code` (string/null) | no |  |
| `to_name` (string/null) | no |  |
| `dep_local` (string/null) | no | Departure, check-in or pick-up. Local time at the place, YYYY-MM-DDTHH:MM (or just YYYY-MM-DD). |
| `arr_local` (string/null) | no | Arrival, check-out or drop-off. Local time at the place, YYYY-MM-DDTHH:MM (or just YYYY-MM-DD). |
| `dep_tz` (string/null) | no | IANA zone of the departure place; filled from the airport when empty. |
| `arr_tz` (string/null) | no |  |
| `terminal` (string/null) | no |  |
| `gate` (string/null) | no |  |
| `seat` (string/null) | no |  |
| `coach` (string/null) | no |  |
| `travel_class` (string/null) | no |  |
| `passengers` (array/null) | no | First names only. |
| `price` (number/null) | no | Price of the booking. |
| `currency` (string/null) | no |  |
| `address` (string/null) | no |  |
| `notes` (string/null) | no |  |
| `status` (string/null) | no |  |
| `kind` (flight \| train \| bus \| ferry \| car \| lodging \| event) | yes | flight, train, bus, ferry, car (rental), lodging or event. |
| `trip` (string) | no | Trip id or title to put it in; empty lets the grouping decide. |

## `segment_update`

Edit a segment: times, places, number, seat, terminal, price, status. Editar un tramo.

Sinónimos: cambiar hora del vuelo, cambiar asiento, corregir fecha, el hotel es otro, marcar como cancelado.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `carrier` (string/null) | no | Airline, rail or bus company. |
| `number` (string/null) | no | Flight number like IB3166, train number or bus line. |
| `booking_ref` (string/null) | no | Booking reference (localizador / PNR). |
| `provider` (string/null) | no | Hotel, rental company or host (stays and cars). |
| `from_code` (string/null) | no | IATA airport code (flights). |
| `from_name` (string/null) | no | Station, port, pick-up point or the stay's name. |
| `to_code` (string/null) | no |  |
| `to_name` (string/null) | no |  |
| `dep_local` (string/null) | no | Departure, check-in or pick-up. Local time at the place, YYYY-MM-DDTHH:MM (or just YYYY-MM-DD). |
| `arr_local` (string/null) | no | Arrival, check-out or drop-off. Local time at the place, YYYY-MM-DDTHH:MM (or just YYYY-MM-DD). |
| `dep_tz` (string/null) | no | IANA zone of the departure place; filled from the airport when empty. |
| `arr_tz` (string/null) | no |  |
| `terminal` (string/null) | no |  |
| `gate` (string/null) | no |  |
| `seat` (string/null) | no |  |
| `coach` (string/null) | no |  |
| `travel_class` (string/null) | no |  |
| `passengers` (array/null) | no | First names only. |
| `price` (number/null) | no | Price of the booking. |
| `currency` (string/null) | no |  |
| `address` (string/null) | no |  |
| `notes` (string/null) | no |  |
| `status` (string/null) | no |  |
| `segment` (string) | yes | Segment id (g_…); the ids are in trip_get. |

## `segment_delete`

Delete a segment (confirm=true). Borrar un tramo o reserva.

Annotations: destructiveHint.

| Argument | Required | Description |
|---|---|---|
| `segment` (string) | yes | Segment id (g_…); the ids are in trip_get. |
| `confirm` (boolean) | no |  |

## `checkin_status`

Online check-in window of each flight: opens, closes, link, done or not. Estado del check-in.

Uses the airline table verified 02-10-2026 and says its source; an airline not in the table is reported as unknown. Sinónimos: cuándo abre el check-in, puedo hacer ya el check-in, check-in online, hora límite del check-in.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | no | Only this trip's flights; empty = flights in the next 45 days. |

## `checkin_done`

Mark a flight's check-in as done (or not). Check-in hecho.

Sinónimos: ya hice el check-in, marcar check-in, deshacer check-in.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `segment` (string) | yes | Segment id (g_…); the ids are in trip_get. |
| `done` (boolean) | no |  |

## `trip_documents_check`

Will the ID card or passport in Kafka still be valid when the trip ends? Comprobar documentos.

Asks Kafka through the hub; if Kafka is down the status is unknown, never an error. Document numbers are never shown. Sinónimos: caduca mi pasaporte, DNI en regla para viajar, documentos para el viaje.

Annotations: readOnlyHint, idempotentHint, openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |

## `trip_people`

People sharing the trip's expenses: add, rename, remove, which one is the user. Personas del viaje.

Sinónimos: añade a Marta al viaje, quién viaja, yo soy.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |
| `add` (array) | no | Names to add (first names). |
| `remove` (array) | no | Names to remove (only if they are in no expense). |
| `rename` (object) | no | {old name: new name}. |
| `me` (string) | no | Which of the people is the user. |

## `trip_expenses`

A trip's shared expenses with each person's share, balances and transfers. Gastos del viaje.

Sinónimos: gastos compartidos, cuánto llevamos gastado, quién debe a quién, cuentas del viaje.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |

## `trip_expense_add`

Add a shared expense: who paid, split equal/shares/exact, currency with its rate. Añadir gasto del viaje.

from_segment turns a booking's price into one expense. Another currency than the trip's needs the rate you paid. Sinónimos: he pagado la cena, apunta un gasto del viaje, pagó Marta, dividir a partes iguales.

Annotations: none.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |
| `description` (string) | no |  |
| `amount` (number) | no | Amount paid in `currency` (the trip currency by default). |
| `payer` (string) | no | Who paid (name); default: the user. |
| `currency` (string) | no |  |
| `rate` (number) | no | 1 unit of `currency` in the trip currency; required when they differ (never fetched from the network). |
| `split_mode` (equal \| shares \| exact) | no |  |
| `split` (object) | no | equal: {"people": [names]} (default everybody); shares: {"shares": {name: weight}}; exact: {"amounts": {name: amount}} adding up to the amount. |
| `date` (string) | no | YYYY-MM-DD; default today. |
| `category` (transport \| lodging \| food \| activities \| shopping \| other) | no |  |
| `from_segment` (string) | no | Instead of description/amount: the price found in that segment's mail, as one expense. |

## `trip_expense_update`

Change a shared expense. Editar gasto del viaje.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `expense` (string) | yes | Expense id (x_…). |
| `description` (string/null) | no |  |
| `amount` (number/null) | no |  |
| `payer` (string/null) | no |  |
| `currency` (string/null) | no |  |
| `rate` (number/null) | no |  |
| `split_mode` (string/null) | no |  |
| `split` (object/null) | no |  |
| `date` (string/null) | no |  |
| `category` (string/null) | no |  |

## `trip_expense_delete`

Delete a shared expense (confirm=true). Borrar gasto del viaje.

Annotations: destructiveHint.

| Argument | Required | Description |
|---|---|---|
| `expense` (string) | yes |  |
| `confirm` (boolean) | no |  |

## `trip_settle`

Balances and the fewest transfers that settle a trip's expenses. Saldar cuentas del viaje.

Sinónimos: quién paga a quién, repartir gastos, liquidar el viaje, cuánto me deben.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |

## `trip_to_ledger`

Send my share of each trip expense not yet sent to Ledger. Pasar mi parte a Ledger.

Each expense goes once (remembered); Ledger down or an account in another currency is explained, nothing is invented. dry_run lists what would go. Sinónimos: pasa los gastos del viaje a mis cuentas, apunta mi parte en Ledger, registrar gastos del viaje.

Annotations: idempotentHint, openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | yes | Trip id (t_…) or its exact title. |
| `account` (string) | no | Ledger account; default the travel.ledger_account setting, or the only account. |
| `dry_run` (boolean) | no | Only list what would be sent. |

## `trip_ics`

Export a trip (or every upcoming trip) to a calendar .ics file. Exportar al calendario.

One event per segment with its time zone, and an alarm when online check-in opens. Saved under data/exports. Sinónimos: añadir el viaje al calendario, exportar a ics, calendario de viajes.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `trip` (string) | no | One trip; empty = every upcoming and ongoing trip. |

## `trip_paste`

Read a booking mail pasted as text into segments and trips. Pegar un correo de reserva.

Reads schema.org markup, sender rules or the local model; says what was read and what needs review. Sinónimos: pega este correo de vuelo, lee esta confirmación de hotel, añadir reserva desde un email.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `subject` (string) | no |  |
| `text` (string) | yes | The booking mail as plain text. |
| `from_address` (string) | no | Sender address, when known: it helps pick the right rules. |
| `trip` (string) | no | Put what is read into this trip. |

## `travel_mail_list`

Travel mails read: waiting for review, filed, ignored. Correos de viajes leídos.

Each shows what was read (source schema, rules or model, with evidence lines). Accept with mail_accept, ignore with mail_ignore. Sinónimos: correos de reservas pendientes, qué reservas ha leído.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `state` (new \| linked \| ignored \| skipped \| all) | no |  |
| `limit` (integer) | no |  |

## `travel_mail_read_again`

Ask the local model to read a travel mail from the review list again. Releer reserva con el modelo.

Annotations: idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `message_id` (string) | yes |  |

## `travel_mail_recheck`

Drop non-bookings from the travel review list. Limpiar la lista de revisión de viajes.

Runs the booking-evidence check again over the mails waiting for review and moves marketing, notices and event tickets out of the list. Sinónimos: limpiar correos de viajes, quitar publicidad de la lista de reservas.

Annotations: idempotentHint.

## REST routes for the UI

- `GET /api/health`, `GET /api/status`
- `GET /api/dashboard` — active parcels sorted by estimated day, arriving today, needs attention, delivered this week, notifications since the last visit, mails to review, mail and carrier sources, scheduler, and a `travel` block (trips on now, next trip, check-ins to do, travel mails to review).
- `POST /api/dashboard/visit` — marks notifications seen and records the visit.
- `GET /api/shipments/{id}` — one shipment with events, mails, similar parcels and the sources that answer for it.
- `GET /api/stats` — delivery days per carrier and shop, and how accurate their dates were.
- `GET /api/trips/ics` — calendar file (`text/calendar`) with every upcoming and ongoing trip; `?trip=<id or title>` for one.
- `GET /api/trips/{id}/ics` — calendar file of one trip: a VEVENT per segment, times in UTC, an alarm when check-in opens.
- `GET /api/family/agenda?from=&to=&sphere=` — the family agenda contract (Bearer token of this app): expected deliveries (`delivery`), pickup deadlines (`deadline`), trips and the departures of their flights, trains, buses and ferries (`other`). Nothing that is over is listed; a late parcel stays on its expected day.
- `POST /api/ui/call` `{name, arguments}` — any tool above, uncapped.

## Events on the family bus

Emitted through Hoard Link (`family.emit`); the payload carries ids and short titles only.

| Event | When | Payload |
|---|---|---|
| `phileas.trip.new` | a trip is created from a mail or by hand | `trip_id`, `title`, `start_date`, `end_date` |
| `phileas.trip.changed` | a trip's segments or dates change (a booking changed, cancelled, merged, split or moved) | `trip_id`, `title`, `start_date`, `end_date` |
| `phileas.checkin.open` | a flight's online check-in opens | `trip_id`, `segment_id`, `number`, `from`, `to`, `dep_local` |
| `phileas.trip.update` | every notification about a trip, through the hub channel | `event_id`, `type`, `severity`, `title`, `summary`, `trip_id`, `segment_id`, `trip_title`, `start_date`, `end_date`, `url` |
| `phileas.update` | every notification about a parcel, through the hub channel (unchanged) | `event_id`, `type`, `severity`, `title`, `summary`, `shipment_id`, … |
| `phileas.shipment.new` | a parcel is created from a live mail (never for the first import or old mail) | `shipment_id`, `merchant`, `order_ref`, `message_id`, `items`, `carrier`, `tracking_number` |
| `phileas.shipment.delivered` | a parcel becomes delivered (carrier, mail or by hand; never for history) | the same, plus `delivered_at` (local ISO time) |
| `phileas.status` | a parcel's status really changes (not for its first status, not for history, not when the same status arrives again) | `shipment_id`, `from`, `to`, `label`, `source` |
