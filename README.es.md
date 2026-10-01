# Phileas's Hoard

Seguimiento de envíos en local. Lee los correos de envío de tu bandeja (tiendas, Amazon, transportistas), los convierte en envíos, sigue cada paquete con su transportista y te dice cuándo debería llegar y por qué: con la fecha del transportista, la fecha y la promesa de la tienda, y lo que tardaron de verdad tus paquetes anteriores.

Es de la familia de apps locales Hoard: corre en tu PC, guarda sus datos en `data/`, funciona sola en el navegador y la puede manejar un asistente por MCP.

[English version](README.md)

## Qué hace

- **Lee tu correo.** Cada 10 minutos lee el correo nuevo con la cuenta configurada en Faustus (la contraseña no sale de Faustus). Deciden reglas, no un modelo: números de seguimiento con su dígito de control, enlaces de transportistas (también dentro de redirecciones de seguimiento de clics), frases de estado en ES/EN/DE/FR/IT/NL, números de pedido, fechas de entrega y avisos de recogida. Comida a domicilio, compras digitales, candidaturas, boletines y tus propias respuestas se quedan fuera; los correos dudosos esperan en una lista para revisar.
- **Un envío por paquete.** Los correos se enlazan por número de seguimiento, identificador de paquete de Amazon, número de pedido, el aviso del propio transportista sobre el paquete que esperas, o el correo anterior de la tienda. La confirmación del pedido y el «enviado con UPS» de días después acaban en un solo envío; dos paquetes de un mismo pedido de Amazon quedan separados.
- **Pregunta a los transportistas.** UPS (API oficial con tus claves gratuitas de desarrollador, o su página pública de seguimiento leída en una ventana de Edge fuera de pantalla), Correos (su localizador público), DHL (API oficial con clave gratuita) y 17TRACK para el resto (una clave, 100 números nuevos al mes gratis). Amazon Logistics no tiene seguimiento público, así que los paquetes de Amazon se siguen por los correos de Amazon.
- **Estima la llegada, con motivos.** Junta la fecha del transportista (corregida según cómo le salieron sus fechas en tus envíos anteriores), la fecha de la tienda («Llega el domingo», «Se entrega: 21–24 ago»), tu historial con envíos parecidos (mismo transportista y origen, si no la misma tienda), la promesa de la tienda («al menos 48 horas… hasta 6 días laborables») y los plazos habituales. Cuenta días de reparto, no de calendario: salta fines de semana, festivos nacionales y los de tu comunidad (Amazon reparte todos los días; Correos e InPost también los sábados). Cada estimación enseña las fuentes que usó y la confianza, y marca los envíos que van con retraso.
- **Historial desde el primer día.** La primera lectura del correo va 120 días atrás y guarda los envíos pasados sin avisar, como historial, para que «envíos parecidos» y las estadísticas por transportista funcionen desde el principio.
- **Te avisa de lo que importa.** Envío nuevo, en camino, llega hoy, listo para recoger (sitio, código, plazo y recordatorio dos días antes), entregado, incidencias, nueva fecha estimada y paquetes sin noticias en cuatro días de reparto. Canales: notificación de Windows, el bus de la familia Hoard, ntfy, Telegram y correo (enviado con la cuenta de Faustus). Cada aviso se manda una vez.
- **Comprobaciones con ritmo.** En reparto cada 30 minutos, en tránsito cada dos horas, nada de noche (23:00–07:00 por defecto); una fuente que falla se reintenta más tarde.

## Pantallas

- **Envíos**: lo que llega hoy, lo que necesita atención, cada paquete en camino con su día estimado, la confianza, el avance, el último escaneo y el motivo de la fecha; las novedades desde tu última visita.
- **Detalle**: la estimación con todas sus fuentes, envíos parecidos anteriores, datos de recogida, la línea de tiempo del transportista, los correos que lo alimentan, edición, silenciar, archivar, fusionar.
- **Correo**: la bandeja que se usa, leer ya o buscar hacia atrás, correos dudosos para aceptar o ignorar, pegar un correo de otra bandeja, detectar números en cualquier texto.
- **Historial**: envíos pasados y días de reparto por transportista y por tienda, y lo acertadas que fueron sus fechas.
- **Ajustes**: correo, claves de transportistas, comunidad y festivos, canales de aviso, idioma, actividad reciente.

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

`mcp_server.py` es un puente MCP por stdio. No abre la base de datos: pasa cada llamada a la app con el token de `data/mcp-token` y arranca la app si no responde. `faustus-plugin.json` describe la app, su comprobación de salud y el puente para Faustus y el Hoard Hub. Las herramientas y sus argumentos están en [docs/API.md](docs/API.md).

## Límites

- El correo se lee de las cuentas configuradas en Faustus; otras bandejas, pegando el correo.
- La web de DHL prohíbe lecturas automáticas: los envíos de DHL necesitan clave de DHL o 17TRACK.
- La lectura de la página de UPS puede dejar de funcionar si UPS cambia su página; la API oficial es el camino estable.
- Las reglas cubren las tiendas y transportistas habituales en España y Europa; un correo raro puede acabar en la lista de revisión.

## Licencia

MIT
