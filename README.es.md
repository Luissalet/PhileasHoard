# Phileas's Hoard

Seguimiento local de envíos y viajes. Lee los correos de envío de tu bandeja (tiendas, Amazon, transportistas), los convierte en envíos, sigue cada paquete con su transportista y te dice cuándo debería llegar y por qué: con la fecha del transportista, la fecha y la promesa de la tienda, y lo que tardaron de verdad tus paquetes anteriores. En la misma lectura de correo recoge las reservas de viaje (vuelos, trenes, autobuses, barcos, coche de alquiler, alojamientos), las agrupa en viajes, te avisa del check-in y reparte los gastos del viaje.

Es de la familia de apps locales Hoard: corre en tu PC, guarda sus datos en `data/`, funciona sola en el navegador y la puede manejar un asistente por MCP.

[English version](README.md)

## Qué hace

- **Lee tu correo.** Cada 10 minutos lee el correo nuevo con la cuenta configurada en Faustus (la contraseña no sale de Faustus). Deciden reglas, no un modelo: números de seguimiento con su dígito de control, enlaces de transportistas (también dentro de redirecciones de seguimiento de clics), frases de estado en ES/EN/DE/FR/IT/NL, números de pedido, fechas de entrega y avisos de recogida. Comida a domicilio, compras digitales, candidaturas, boletines y tus propias respuestas se quedan fuera; los correos dudosos esperan en una lista para revisar.
- **Un envío por paquete.** Los correos se enlazan por número de seguimiento, identificador de paquete de Amazon, número de pedido, el aviso del propio transportista sobre el paquete que esperas, o el correo anterior de la tienda. La confirmación del pedido y el «enviado con UPS» de días después acaban en un solo envío; dos paquetes de un mismo pedido de Amazon quedan separados.
- **Pregunta a los transportistas.** UPS (API oficial con tus claves gratuitas de desarrollador, o su página pública de seguimiento leída en una ventana de Edge fuera de pantalla), Correos (su localizador público), DHL (API oficial con clave gratuita) y 17TRACK para el resto (una clave, 100 números nuevos al mes gratis). Amazon Logistics no tiene seguimiento público, así que los paquetes de Amazon se siguen por los correos de Amazon.
- **Estima la llegada, con motivos.** Junta la fecha del transportista (corregida según cómo le salieron sus fechas en tus envíos anteriores), la fecha de la tienda («Llega el domingo», «Se entrega: 21–24 ago»), tu historial con envíos parecidos (mismo transportista y origen, si no la misma tienda), la promesa de la tienda («al menos 48 horas… hasta 6 días laborables») y los plazos habituales. Cuenta días de reparto, no de calendario: salta fines de semana, festivos nacionales y los de tu comunidad (Amazon reparte todos los días; Correos e InPost también los sábados). Cada estimación enseña las fuentes que usó y la confianza, y marca los envíos que van con retraso.
- **Historial desde el primer día.** La primera lectura del correo va 120 días atrás y guarda los envíos pasados sin avisar, como historial, para que «envíos parecidos» y las estadísticas por transportista funcionen desde el principio.
- **Te avisa de lo que importa.** Envío nuevo, en camino, llega hoy, listo para recoger (sitio, código, plazo y recordatorio dos días antes), entregado, incidencias, nueva fecha estimada y paquetes sin noticias en cuatro días de reparto. Canales: notificación de Windows, el bus de la familia Hoard, ntfy, Telegram y correo (enviado con la cuenta de Faustus). Cada aviso se manda una vez.
- **Lee reservas de viaje.** En la misma pasada, los correos de reservas se convierten en *tramos*: vuelo, tren, autobús, barco, coche de alquiler, alojamiento, actividad. Orden de lectura: marcado schema.org de reservas dentro del correo (JSON-LD y microdatos), después reglas para los remitentes habituales (Iberia, Iberia Express, Vueling, Air Europa, Ryanair, easyJet, Volotea, Binter, TAP, Lufthansa, British Airways, Air France y KLM, Renfe, Iryo, Ouigo, Alsa, FlixBus, Baleària, confirmaciones de hoteles y alquileres vacacionales, coche de alquiler, agencias de viajes) y, solo para correos que ya se sabe que son una reserva y que las reglas no leen, el modelo local por Hoard Link. Lo que lee el modelo se marca como *leído por el modelo local*, guarda las líneas del correo en que se basa, nunca se archiva solo y espera en la lista de revisión (Correo → Viajes). Sin modelo, el correo se queda en revisión y no se inventa nada. Un correo de cambio o cancelación actualiza o cancela el tramo al que se refiere; un correo antiguo nunca pisa a uno más nuevo. Los aeropuertos salen de una tabla IATA local (nombre, ciudad, país, zona horaria), de modo que las horas de salida y llegada conservan su zona horaria, también con el cambio de hora.
- **Los agrupa en viajes.** Ida, alojamientos, coche y vuelta se agrupan según la ciudad y los aeropuertos de casa de Ajustes y los días de separación entre tramos, con títulos como «Lisboa · 12–15 nov 2026». Un viaje que no pasa por casa se agrupa por su primer lugar. Puedes renombrar un viaje (o volver al título automático), fusionar dos, separar tramos, mover un tramo, añadir tramos a mano o pegar un correo. Estados: próximo, en curso, pasado, cancelado. Los tramos que editas o colocas a mano se quedan donde los pones.
- **Check-in y avisos del viaje.** Para los vuelos conoce la ventana de check-in online de Ryanair, easyJet, Vueling, Iberia y Air Europa (tabla en `phileas_hoard/travel/checkin.py`, con la fuente y la fecha de comprobación, 2026-10-02; también en Ajustes). Cualquier otra aerolínea es «desconocida»: aviso 24 h antes diciendo que compruebes en la aerolínea cuándo abre. Avisos, cada uno una sola vez y con el silencio nocturno de las comprobaciones de envíos: mañana viajas, se abre el check-in (con el enlace), el check-in cierra en 3 horas y no lo has marcado como hecho, día de entrada al alojamiento, salida en N horas (configurable), un tramo cambiado o cancelado, problema con un documento.
- **Documentos desde Kafka.** A través del concentrador de Hoards lista los documentos de identidad y sus caducidades y avisa si el DNI o el pasaporte caducan antes del último día del viaje (se pide pasaporte cuando el viaje sale del espacio Schengen). Nunca lee ni muestra números de documento. Con Kafka o el concentrador caídos la respuesta es «no se pudo comprobar», no un error.
- **Gastos compartidos por viaje.** Personas, gastos (quién pagó, reparto a partes iguales, por partes o importes exactos, fecha, categoría), saldos y el mínimo de transferencias para saldarlos (exacto hasta 16 personas con saldo). Cada viaje tiene una moneda base; un gasto en otra moneda lleva el cambio que escribes (no se consulta ningún cambio en internet). El precio de una reserva se convierte en gasto con un clic. «Pasar mi parte a Ledger» envía mi parte de cada gasto aún no enviado al Hoard de Ledger por el concentrador, recuerda lo enviado y nunca lo manda dos veces; con Ledger caído explica por qué.
- **Calendario.** Un archivo `.ics` por viaje o con todos los viajes próximos: un evento por tramo con su zona horaria, evento de día completo para los alojamientos y una alarma cuando se abre el check-in.
- **Comprobaciones con ritmo.** En reparto cada 30 minutos, en tránsito cada dos horas, nada de noche (23:00–07:00 por defecto); una fuente que falla se reintenta más tarde.

## Pantallas

- **Envíos**: lo que llega hoy, lo que necesita atención, cada paquete en camino con su día estimado, la confianza, el avance, el último escaneo y el motivo de la fecha; las novedades desde tu última visita.
- **Detalle**: la estimación con todas sus fuentes, envíos parecidos anteriores, datos de recogida, la línea de tiempo del transportista, los correos que lo alimentan, edición, silenciar, archivar, fusionar.
- **Correo**: la bandeja que se usa, leer ya o buscar hacia atrás, correos dudosos para aceptar o ignorar, pegar un correo de otra bandeja, detectar números en cualquier texto.
- **Historial**: envíos pasados y días de reparto por transportista y por tienda, y lo acertadas que fueron sus fechas.
- **Ajustes**: correo, viajes, claves de transportistas, comunidad y festivos, canales de aviso, idioma, actividad reciente.
- **Viajes**: viajes en curso con la vista «hoy», check-ins pendientes, próximos viajes, pasados y cancelados; pegar una reserva, nuevo viaje, descarga del calendario.
- **Viaje**: un viaje: estado del check-in de cada vuelo, comprobación de documentos, línea de tiempo día a día, cada reserva con sus enlaces, correos y líneas de evidencia, editor de tramos, fusionar, separar y mover, y la pestaña Gastos con personas, gastos, saldos, saldar cuentas y el botón de Ledger. En Correo hay una pestaña Viajes con las reservas que esperan revisión.

## Arrancarlo

Requisitos: Python 3.11+, Node 22 (solo para recompilar la interfaz), Edge o Chrome para UPS sin claves de API, y Faustus con una cuenta de correo para leer el correo solo.

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt      # Windows; venv/bin/python en el resto
venv/Scripts/python -m phileas_hoard                          # http://127.0.0.1:5199
```

La interfaz viene compilada en `phileas_hoard/static`. Para recompilarla: `npm install && npx vite build`.

En Ajustes → Correo va la carpeta de Faustus (o `PHILEAS_FAUSTUS_DIR`). Sin Faustus puedes pegar correos, añadir números a mano y usar todas las fuentes de transportistas.

## Asistentes (MCP)

`mcp_server.py` es un puente MCP por stdio. No abre la base de datos: pasa cada llamada a la app con el token de `data/mcp-token` y arranca la app si no responde. `faustus-plugin.json` describe la app, su comprobación de salud y el puente para Faustus y el Hoard Hub. Las herramientas y sus argumentos están en [docs/API.md](docs/API.md). Herramientas de viajes: `travel_overview`, `trips_list`, `trip_get`, `trip_create`, `trip_update` (renombrar, silenciar, cancelar, fusionar, separar, mover un tramo, borrar), `segment_add`, `segment_update`, `segment_delete`, `checkin_status`, `checkin_done`, `trip_documents_check`, `trip_people`, `trip_expenses`, `trip_expense_add`, `trip_expense_update`, `trip_expense_delete`, `trip_settle`, `trip_to_ledger`, `trip_ics`, `trip_paste`, `travel_mail_list`, `travel_mail_read_again`.

Eventos en el bus de la familia: `phileas.update` (cada aviso de envío) y `phileas.status` (cada cambio de estado de un envío); de viajes, `phileas.trip.new` (se crea un viaje), `phileas.trip.changed` (cambian sus tramos o fechas), `phileas.checkin.open` (se abre el check-in de un vuelo) y `phileas.trip.update` (cada aviso de viaje, por el canal del concentrador). Las cargas llevan solo ids, títulos y fechas.

## Ajustes de viajes

En Ajustes → Viajes: activar la lectura (`travel.enabled`), ciudad, aeropuertos y zona horaria de casa, días entre tramos de un mismo viaje, tipos de reserva que se leen (`travel.kinds`), horas del aviso de salida, hora del aviso «mañana viajas», mi nombre en los gastos, uso del modelo local, comprobación de documentos y su antelación, cuenta de Ledger por defecto. Los viajes se leen de la misma ventana de correo que los envíos; la primera lectura guarda las reservas pasadas en silencio, como historial.

## Datos de aeropuertos

`phileas_hoard/travel/tables/airports.json` lo genera `scripts/gen_airports.py` a partir del paquete `airportsdata` (licencia MIT; deriva de la lista pública de aeropuertos de mwgg, copyright 2014 mwgg, MIT). Solo se guardan código IATA, nombre, ciudad, país y zona horaria; el paquete no hace falta al ejecutar.

## Límites

- El correo se lee de las cuentas configuradas en Faustus; otras bandejas, pegando el correo.
- La web de DHL prohíbe lecturas automáticas: los envíos de DHL necesitan clave de DHL o 17TRACK.
- La lectura de la página de UPS puede dejar de funcionar si UPS cambia su página; la API oficial es el camino estable.
- Las reglas cubren las tiendas y transportistas habituales en España y Europa; un correo raro puede acabar en la lista de revisión.
- Viajes: no hay estado de vuelo en directo (retrasos, puertas y cancelaciones solo se saben por correo) ni se usa ninguna cuenta de aerolínea o de tren. Las reglas por remitente y los formatos que leen se hicieron con correos de ejemplo inventados: un correo real con otro formato acaba en revisión, y el modelo lo lee solo si hay un modelo local. El precio se lee solo cuando el correo da un total.
- Las ventanas de check-in son las que publicaban las aerolíneas al comprobarlas (2026-10-02) y pueden cambiar; el cierre de Vueling fuera de Schengen no está en la tabla (no hay aviso de cierre para esos vuelos) y Iberia Express se trata como aerolínea de regla desconocida. El cierre de Air Europa se fija en 60 minutos, el extremo prudente de 45–60.
- Los gastos usan el cambio que escribes; pasar a Ledger necesita el concentrador, Ledger en marcha y una cuenta en la moneda del viaje. Los títulos de los viajes se escriben en el idioma activo al crearlos.

## Licencia

MIT
