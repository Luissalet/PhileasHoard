"""Synthetic shipping mails shaped like the real ones (shops, Amazon, carriers, noise). Names, addresses and numbers are invented."""

from __future__ import annotations

from datetime import datetime

T0 = datetime(2026, 10, 1, 15, 0).timestamp()        # Thursday 1 October 2026, 15:00 local time
H = 3600.0
D = 86400.0
UPS = "1Z999AA10123456784"                              # valid UPS check digit, invented
S10 = "RR123456785ES"
CORREOS_CODE = "PK7ZXQ1234567890128013X"
DHL = "JJD0000999000111222333444"
YUN = "YT2600000000000001"

PAD = "\u034f \u200c \u2007 \u00ad" * 30                # the invisible pre-header padding Amazon adds


def msg(mid: str, ts: float, sender: str, subject: str, text: str, links: list[dict] | None = None, name: str = "", **extra) -> dict:
    return {"message_id": f"<{mid}@test>", "ts": ts, "from_address": sender, "from_name": name, "subject": subject, "text": text,
            "links": links or [], "account": "test", **extra}


def amazon_links(order: str, shipment: str) -> list[dict]:
    wrapped = ("https://www.amazon.es/gp/r.html?C=X&K=Y&U=https%3A%2F%2Fwww.amazon.es%2Fprogress-tracker%2Fpackage%3F_encoding%3DUTF8"
               f"%26orderId%3D{order}%26packageIndex%3D0%26shipmentId%3D{shipment}")
    return [{"url": wrapped, "label": "Seguimiento del envío"},
            {"url": f"https://www.amazon.es/progress-tracker/package?_encoding=UTF8&orderId={order}&packageIndex=0&shipmentId={shipment}",
             "label": ""}]


def amazon(mid: str, ts: float, kind: str, item: str, order: str, shipment: str = "", eta: str = "Llega mañana") -> dict:
    subject = {"pedido": f"Pedido: “{item}...”", "enviado": f"Enviado: \"{item}...\"", "reparto": f"En reparto: “{item}...”"}[kind]
    head = {"pedido": "¡Gracias por tu pedido!", "enviado": "¡Tu paquete se ha enviado!", "reparto": "¡Tu paquete está en reparto!"}[kind]
    sender = {"pedido": "auto-confirm@amazon.es", "enviado": "confirmar-envio@amazon.es", "reparto": "shipment-tracking@amazon.es"}[kind]
    text = (f"{subject}{PAD}\n\nMis pedidos Mi cuenta Volver a comprar\n\n{head}\n\nPedido\n\nEnviado\n\nEn reparto\n\nEntregado\n\n{eta}\n\n"
            f"Ana - Madrid\n\nPedido n.º «{order}\n\nSeguimiento del envío")
    return msg(mid, ts, sender, subject, text, amazon_links(order, shipment) if shipment else [])


PCS_ORDER = msg("pcs-order", T0 - 1.5 * D, "consultas@pcspecialist.es", "Gracias por realizar su pedido en pcspecialist.es",
                "Estimada Ana Pérez:\n\nGracias por realizar su pedido. Recibirá un correo cuando se fabrique y se envíe.\n"
                "Le mantendremos informada del estado del pedido.")
PCS_SHIPPED = msg("pcs-shipped", T0 - 2 * H, "consultas@pcspecialist.es", "¡Pedido 3400001 enviado!",
                  f"Estimada Ana Pérez:\n\nSe ha enviado su pedido (número 3400001) con UPS. Su número de envío es {UPS} (puede encontrar a "
                  "continuación los datos de seguimiento).\n\nSe ha enviado el pedido a la siguiente dirección:\n\nCalle Mayor 1\nMadrid\n28013\n\n"
                  "Se ha enviado el pedido utilizando el servicio de entrega de UPS. Debido a su ubicación, es probable que la entrega de su "
                  "pedido tarde al menos 48 horas, pero dependiendo del país puede tardar hasta 6 días. Si no recibe su pedido en seis días "
                  f"laborables, compruebe el siguiente enlace.\n\nhttps://www.ups.com/track?loc=es_es&tracknum={UPS}")
GOOGLE_READY = msg("gs-ready", T0 - 40 * D, "googlestore-noreply@google.com", "Tu pedido de Google Store (GS.1111-2222-3333) está listo para enviarse",
                   "Tu pedido está listo para enviarse\n\n¡Buenas noticias! Tu pedido está pendiente de recogida por parte de la empresa de "
                   f"transporte.\n\nSe entraga: 21 de ago \u2011 24 de ago\n\nSeguimiento: {DHL}\n\nSeguir el paquete\n\nTeléfono de prueba 8 GB\n\n"
                   "Número de ID:\n354534423335363\n\n499,00 €\n\nNúmero de pedido\n\nGS.1111-2222-3333")
GOOGLE_DELIVERED = msg("gs-done", T0 - 39 * D, "googlestore-noreply@google.com", "Tu pedido de Google Store se encuentra en nuestras instalaciones",
                       f"¡A celebrar!\n\nSe acaba de entregar tu paquete.\n\nEntregado 21 de ago\n\nSeguimiento: {DHL}\n\nNúmero de pedido\n\nGS.1111-2222-3333")
WALLAPOP = msg("wp-correos", T0 - 3 * H, "info@wallapop.com", "Wallapop Envíos: Tu paquete te está esperando en Correos",
               "Tu paquete te está esperando en el punto de recogida de Correos.\n\nDispones de 15 días para recoger el paquete. "
               f"Simplemente muestra el código de recogida ¡y listo!\n\nVendido por:\n\nJuan R.\n\nCódigo de recogida\n\n{CORREOS_CODE}\n\n"
               "Consola portátil de prueba\n\n120.00€\n\nEnvío\n\n0.00€\n\nTotal\n125.69€")
INPOST_READY = msg("inpost-ready", T0 - 5 * H, "no_reply@info.inpost.es", "¡Ya puedes recoger tu paquete!",
                   "¡Buenas noticias! Tu pedido 70000001 de ha llegado al Punto Pack.\n\nPuedes recogerlo con total seguridad utilizando el "
                   "siguiente código:\n\n123456\n\nTu paquete te está esperando en:\n\npapelería de prueba\n\nCalle Falsa 3\n\n28001 Madrid\n\n"
                   "Información práctica:")
INPOST_SURVEY = msg("inpost-survey", T0 + 20 * H, "no_reply@inpost.es", "¡Paquete entregado! Cuéntanos qué te ha parecido InPost",
                    "Solo te llevará unos segundos.\n\nHola,\n\nTu paquete ha sido entregado con éxito.")
WALLAPOP_INPOST = msg("wp-inpost", T0 - 6 * H, "info@wallapop.com", "Wallapop Envíos: Tu paquete te está esperando en InPost",
                      "Tu paquete te está esperando en el punto de recogida de InPost.\n\nDispones de 8 días para recoger el paquete.\n\n"
                      "Teclado de prueba\n\n40.00€")
SHOPIFY = msg("shopify", T0 - 4 * D, "store+1234@t.shopifyemail.com", "A shipment from order F2026000001 is on the way",
              "Your order is on the way\n\n*****\nTestShop\n( https://shop.testshop.com )\n\nOrder F2026000001\n\nYunExpress tracking number: "
              f"{YUN}\n( http://www.yuntrack.com/Track/Detail/{YUN} )\n\nItems in this shipment\n----------------------\n\nMini keyboard × 1",
              [{"url": f"http://www.yuntrack.com/Track/Detail/{YUN}", "label": ""}])
NOISE = [
    msg("je", T0 - 2 * D, "no-reply@order.just-eat.es", "Ana, pedido confirmado", "Tu pedido de comida llega en 30 minutos. Pedido 123456789"),
    msg("li", T0 - 2 * D, "jobs-noreply@linkedin.com", "Ana, se ha enviado tu solicitud a Empresa", "Se ha enviado tu solicitud. 4430881610"),
    msg("self", T0 - 1 * D, "ana@example.com", "Re: Gracias por realizar su pedido", "¿Cuándo se envía mi pedido? Gracias", from_self=True),
    msg("ali", T0 - 3 * D, "aeug-member-benefits05@deals.aliexpress.com", "Ana, alegría en camino", "-50% 2,47€ Consigue envío gratis"),
]
