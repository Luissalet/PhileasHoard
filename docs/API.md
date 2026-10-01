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

## `mail_list`

Mails Phileas read: to review (maybe), shipping, noise. Correos leídos y dudosos.

Annotations: readOnlyHint, idempotentHint.

| Argument | Required | Description |
|---|---|---|
| `kind` (maybe \| shipping \| noise \| all) | no |  |
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

Send a test notification through one channel. Probar un canal de aviso.

Annotations: openWorldHint.

| Argument | Required | Description |
|---|---|---|
| `channel` (toast \| hub \| ntfy \| telegram \| email) | yes |  |

## `telegram_find_chat_id`

Find and save the Telegram chat id after writing to the bot. Buscar chat de Telegram.

Annotations: idempotentHint, openWorldHint.

## `settings_set`

Change settings (mail interval, region for holidays, channels…). Cambiar ajustes.

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

## REST routes for the UI

- `GET /api/health`, `GET /api/status`
- `GET /api/dashboard` — active parcels sorted by estimated day, arriving today, needs attention, delivered this week, notifications since the last visit, mails to review, mail and carrier sources, scheduler.
- `POST /api/dashboard/visit` — marks notifications seen and records the visit.
- `GET /api/shipments/{id}` — one shipment with events, mails, similar parcels and the sources that answer for it.
- `GET /api/stats` — delivery days per carrier and shop, and how accurate their dates were.
- `POST /api/ui/call` `{name, arguments}` — any tool above, uncapped.
