"""The travel tools: trips, segments, check-in, documents, shared expenses, calendar. Registered in ``agent_tools.TOOLS``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .agent_tools import Empty, Tool, _ann, _confirm, cap_result
from .errors import PhileasError
from .services import Services
from .travel.model import EXPENSE_CATEGORIES, KINDS, SPLIT_MODES

TRIP = Field(..., min_length=1, max_length=120, description="Trip id (t_…) or its exact title.")
SEG = Field(..., min_length=1, max_length=60, description="Segment id (g_…); the ids are in trip_get.")
LOCAL = "Local time at the place, YYYY-MM-DDTHH:MM (or just YYYY-MM-DD)."


class TripArg(BaseModel):
    trip: str = TRIP


class TripsListArgs(BaseModel):
    filter: Literal["upcoming", "ongoing", "past", "cancelled", "active", "all"] = "upcoming"


class TripCreateArgs(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    start_date: str = Field("", max_length=10, description="YYYY-MM-DD; filled from the segments once there are some.")
    end_date: str = Field("", max_length=10)
    currency: str = Field("EUR", min_length=3, max_length=3, description="Base currency of the trip's shared expenses.")
    notes: str = Field("", max_length=4000)


class TripUpdateArgs(BaseModel):
    trip: str = TRIP
    title: Optional[str] = Field(None, max_length=120, description="Rename. An empty string gives the automatic title back.")
    notes: Optional[str] = Field(None, max_length=4000)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    pinned: Optional[bool] = Field(None, description="Keep the trip even with no segments.")
    muted: Optional[bool] = Field(None, description="No reminders for this trip.")
    cancelled: Optional[bool] = Field(None, description="Mark the whole trip cancelled (or not).")
    merge_from: Optional[str] = Field(None, max_length=120, description="Another trip (id or title) to merge INTO this one; needs confirm=true.")
    split_segments: Optional[list[str]] = Field(None, max_length=60, description="Segment ids to split off into a new trip (not all of them).")
    split_title: str = Field("", max_length=120, description="Title for the trip created by split_segments.")
    move_segment: Optional[str] = Field(None, max_length=60, description="Segment id to move.")
    to_trip: str = Field("", max_length=120, description="With move_segment: target trip id or title, 'new' for a trip of its own, or empty to let the grouping place it again.")
    delete: bool = Field(False, description="Delete the trip AND its bookings (they are remembered as deleted, so reading the same mail again does not bring them back); needs confirm=true.")
    keep_segments: bool = Field(False, description="With delete: keep the bookings instead, detached and marked 'no trip' (the grouping leaves them alone).")
    confirm: bool = False


class SegmentFields(BaseModel):
    carrier: Optional[str] = Field(None, max_length=60, description="Airline, rail or bus company.")
    number: Optional[str] = Field(None, max_length=12, description="Flight number like IB3166, train number or bus line.")
    booking_ref: Optional[str] = Field(None, max_length=20, description="Booking reference (localizador / PNR).")
    provider: Optional[str] = Field(None, max_length=80, description="Hotel, rental company or host (stays and cars).")
    from_code: Optional[str] = Field(None, max_length=3, description="IATA airport code (flights).")
    from_name: Optional[str] = Field(None, max_length=80, description="Station, port, pick-up point or the stay's name.")
    to_code: Optional[str] = Field(None, max_length=3)
    to_name: Optional[str] = Field(None, max_length=80)
    dep_local: Optional[str] = Field(None, max_length=16, description="Departure, check-in or pick-up. " + LOCAL)
    arr_local: Optional[str] = Field(None, max_length=16, description="Arrival, check-out or drop-off. " + LOCAL)
    dep_tz: Optional[str] = Field(None, max_length=40, description="IANA zone of the departure place; filled from the airport when empty.")
    arr_tz: Optional[str] = Field(None, max_length=40)
    terminal: Optional[str] = Field(None, max_length=8)
    gate: Optional[str] = Field(None, max_length=8)
    seat: Optional[str] = Field(None, max_length=8)
    coach: Optional[str] = Field(None, max_length=8)
    travel_class: Optional[str] = Field(None, max_length=30)
    passengers: Optional[list[str]] = Field(None, max_length=9, description="First names only.")
    price: Optional[float] = Field(None, ge=0, description="Price of the booking.")
    currency: Optional[str] = Field(None, max_length=3)
    address: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)
    status: Optional[Literal["confirmed", "cancelled"]] = None


class SegmentAddArgs(SegmentFields):
    kind: Literal[KINDS] = Field(..., description="flight, train, bus, ferry, car (rental), lodging or event.")  # type: ignore[valid-type]
    trip: str = Field("", max_length=120, description="Trip id or title to put it in; empty lets the grouping decide.")


class SegmentUpdateArgs(SegmentFields):
    segment: str = SEG


class SegmentRef(BaseModel):
    segment: str = SEG


class SegmentDeleteArgs(BaseModel):
    segment: str = SEG
    confirm: bool = False


class CheckinStatusArgs(BaseModel):
    trip: str = Field("", max_length=120, description="Only this trip's flights; empty = flights in the next 45 days.")


class CheckinDoneArgs(BaseModel):
    segment: str = SEG
    done: bool = True


class PeopleArgs(BaseModel):
    trip: str = TRIP
    add: list[str] = Field(default_factory=list, max_length=20, description="Names to add (first names).")
    remove: list[str] = Field(default_factory=list, max_length=20, description="Names to remove (only if they are in no expense).")
    rename: dict[str, str] = Field(default_factory=dict, description="{old name: new name}.")
    me: str = Field("", max_length=40, description="Which of the people is the user.")


class ExpenseAddArgs(BaseModel):
    trip: str = TRIP
    description: str = Field("", max_length=200)
    amount: float = Field(0, ge=0, description="Amount paid in `currency` (the trip currency by default).")
    payer: str = Field("", max_length=40, description="Who paid (name); default: the user.")
    currency: str = Field("", max_length=3)
    rate: float = Field(1.0, gt=0, description="1 unit of `currency` in the trip currency; required when they differ (never fetched from the network).")
    split_mode: Literal[SPLIT_MODES] = "equal"  # type: ignore[valid-type]
    split: dict[str, Any] = Field(default_factory=dict, description="equal: {\"people\": [names]} (default everybody); shares: {\"shares\": {name: weight}}; "
                                  "exact: {\"amounts\": {name: amount}} adding up to the amount.")
    date: str = Field("", max_length=10, description="YYYY-MM-DD; default today.")
    category: Literal[EXPENSE_CATEGORIES] = "other"  # type: ignore[valid-type]
    from_segment: str = Field("", max_length=60, description="Instead of description/amount: the price found in that segment's mail, as one expense.")


class ExpenseUpdateArgs(BaseModel):
    expense: str = Field(..., min_length=1, max_length=60, description="Expense id (x_…).")
    description: Optional[str] = Field(None, max_length=200)
    amount: Optional[float] = Field(None, gt=0)
    payer: Optional[str] = Field(None, max_length=40)
    currency: Optional[str] = Field(None, max_length=3)
    rate: Optional[float] = Field(None, gt=0)
    split_mode: Optional[Literal[SPLIT_MODES]] = None  # type: ignore[valid-type]
    split: Optional[dict[str, Any]] = None
    date: Optional[str] = Field(None, max_length=10)
    category: Optional[Literal[EXPENSE_CATEGORIES]] = None  # type: ignore[valid-type]


class ExpenseDeleteArgs(BaseModel):
    expense: str = Field(..., min_length=1, max_length=60)
    confirm: bool = False


class ToLedgerArgs(BaseModel):
    trip: str = TRIP
    account: str = Field("", max_length=80, description="Ledger account; default the travel.ledger_account setting, or the only account.")
    dry_run: bool = Field(False, description="Only list what would be sent.")


class IcsArgs(BaseModel):
    trip: str = Field("", max_length=120, description="One trip; empty = every upcoming and ongoing trip.")


class TripPasteArgs(BaseModel):
    subject: str = Field("", max_length=300)
    text: str = Field(..., min_length=10, max_length=60_000, description="The booking mail as plain text.")
    from_address: str = Field("", max_length=200, description="Sender address, when known: it helps pick the right rules.")
    trip: str = Field("", max_length=120, description="Put what is read into this trip.")


class TravelMailListArgs(BaseModel):
    state: Literal["new", "linked", "ignored", "skipped", "all"] = "new"
    limit: int = Field(30, ge=1, le=200)


class MailIdArg(BaseModel):
    message_id: str = Field(..., min_length=3, max_length=300)


# ================================================================================ handlers
def _tv(svc: Services):
    return svc.travel


def _fields(a: BaseModel, exclude: set[str]) -> dict[str, Any]:
    return a.model_dump(exclude=exclude, exclude_none=True)


def run_overview(svc: Services, _: Empty) -> dict[str, Any]:
    return cap_result(_tv(svc).overview())


def run_list(svc: Services, a: TripsListArgs) -> dict[str, Any]:
    rows = _tv(svc).trips_list(a.filter)
    return cap_result({"trips": rows, "count": len(rows), "today": _tv(svc).today().isoformat()})


def run_get(svc: Services, a: TripArg) -> dict[str, Any]:
    return cap_result(_tv(svc).trip_detail(a.trip))


def run_create(svc: Services, a: TripCreateArgs) -> dict[str, Any]:
    return cap_result(_tv(svc).create_trip(a.title, a.start_date, a.end_date, a.currency, a.notes))


def run_update(svc: Services, a: TripUpdateArgs) -> dict[str, Any]:
    tv = _tv(svc)
    trip = tv.t.find_trip(a.trip)
    done: list[str] = []
    if a.delete:
        _confirm(a.confirm, f"trip {trip.get('title')}")
        out = tv.delete_trip(trip["id"], keep_segments=a.keep_segments)
        return {**out, "done": ["deleted"]}
    if a.merge_from:
        other = tv.t.find_trip(a.merge_from)
        _confirm(a.confirm, f"trip {other.get('title')} (merged into {trip.get('title')})")
        tv.merge_trips(trip["id"], other["id"])
        done.append(f"merged {other['id']}")
    if a.split_segments:
        out = tv.split_trip(trip["id"], a.split_segments, a.split_title)
        return cap_result({"done": done + ["split"], **out})
    if a.move_segment:
        tv.move_segment(a.move_segment, a.to_trip.strip() or None)
        done.append(f"moved {a.move_segment}")
    fields = {k: getattr(a, k) for k in ("title", "notes", "currency", "pinned", "muted", "cancelled") if getattr(a, k) is not None}
    if fields:
        tv.update_trip(trip["id"], **fields)
        done.append("updated " + ", ".join(fields))
    if not done:
        raise PhileasError("invalid", "Nothing to do.", "Give title, notes, merge_from, split_segments, move_segment, pinned, muted, cancelled or delete.")
    return cap_result({"done": done, **_tv(svc).trip_detail(trip["id"])})


def run_segment_add(svc: Services, a: SegmentAddArgs) -> dict[str, Any]:
    return _tv(svc).add_segment(trip=a.trip, **_fields(a, {"trip"}))


def run_segment_update(svc: Services, a: SegmentUpdateArgs) -> dict[str, Any]:
    return _tv(svc).update_segment(a.segment, **_fields(a, {"segment"}))


def run_segment_delete(svc: Services, a: SegmentDeleteArgs) -> dict[str, Any]:
    seg = _tv(svc).t.segment(a.segment)
    _confirm(a.confirm, f"segment {seg.get('number') or seg['kind']} {seg.get('start_date')}")
    return _tv(svc).delete_segment(a.segment)


def run_checkin_status(svc: Services, a: CheckinStatusArgs) -> dict[str, Any]:
    return cap_result(_tv(svc).checkin_status(a.trip))


def run_checkin_done(svc: Services, a: CheckinDoneArgs) -> dict[str, Any]:
    return _tv(svc).set_checkin_done(a.segment, a.done)


def run_docs(svc: Services, a: TripArg) -> dict[str, Any]:
    return _tv(svc).docs_check(a.trip)


def run_people(svc: Services, a: PeopleArgs) -> dict[str, Any]:
    tv = _tv(svc)
    trip = tv.t.find_trip(a.trip)
    tv.ensure_people(trip["id"])
    if a.add:
        tv.add_people(trip["id"], a.add)
    for old, new in a.rename.items():
        tv.rename_person(trip["id"], old, name=new)
    if a.me:
        tv.rename_person(trip["id"], a.me, is_me=True)
    for name in a.remove:
        tv.remove_person(trip["id"], name)
    return {"people": tv.t.people(trip["id"])}


def run_expenses(svc: Services, a: TripArg) -> dict[str, Any]:
    tv = _tv(svc)
    return cap_result(tv.expenses_view(tv.t.find_trip(a.trip)["id"]))


def run_expense_add(svc: Services, a: ExpenseAddArgs) -> dict[str, Any]:
    tv = _tv(svc)
    if a.from_segment:
        return tv.expense_from_segment(a.from_segment, payer=a.payer)
    if not a.description.strip() or a.amount <= 0:
        raise PhileasError("invalid", "An expense needs a description and an amount above zero.", "Or give from_segment to use a booking's price.")
    return tv.add_expense(a.trip, description=a.description, amount=a.amount, payer=a.payer, currency=a.currency, rate=a.rate, split_mode=a.split_mode,
                          split=a.split, day=a.date, category=a.category)


def run_expense_update(svc: Services, a: ExpenseUpdateArgs) -> dict[str, Any]:
    f = a.model_dump(exclude={"expense"}, exclude_none=True)
    if "date" in f:
        f["day"] = f.pop("date")
    return _tv(svc).update_expense(a.expense, **f)


def run_expense_delete(svc: Services, a: ExpenseDeleteArgs) -> dict[str, Any]:
    _confirm(a.confirm, f"expense {a.expense}")
    return _tv(svc).delete_expense(a.expense)


def run_settle(svc: Services, a: TripArg) -> dict[str, Any]:
    tv = _tv(svc)
    view = tv.expenses_view(tv.t.find_trip(a.trip)["id"])
    return {"trip": a.trip, "people": [p["name"] for p in view["people"]], **view["summary"]}


def run_to_ledger(svc: Services, a: ToLedgerArgs) -> dict[str, Any]:
    return cap_result(_tv(svc).to_ledger(a.trip, account=a.account, dry_run=a.dry_run))


def run_ics(svc: Services, a: IcsArgs) -> dict[str, Any]:
    out = _tv(svc).ics(a.trip)
    folder = svc.config.data_dir / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / out["filename"]
    path.write_bytes(out["ics"].encode("utf-8"))
    result = {"filename": out["filename"], "events": out["events"], "saved_to": str(path), "download": "/api/trips/ics" + (f"?trip={a.trip}" if a.trip else "")}
    if len(out["ics"]) <= 12_000:
        result["ics"] = out["ics"]
    return result


def run_paste(svc: Services, a: TripPasteArgs) -> dict[str, Any]:
    return cap_result(_tv(svc).paste(subject=a.subject, text=a.text, from_address=a.from_address, trip=a.trip))


def run_mail_list(svc: Services, a: TravelMailListArgs) -> dict[str, Any]:
    rows = _tv(svc).mails_list(a.state, a.limit)
    return cap_result({"mails": rows, "count": len(rows)})


def run_read_again(svc: Services, a: MailIdArg) -> dict[str, Any]:
    return cap_result(_tv(svc).read_again(a.message_id))


def run_recheck(svc: Services, a: BaseModel) -> dict[str, Any]:
    return cap_result(_tv(svc).recheck_review())


SIN = "Sinónimos:"
TRAVEL_TOOLS: list[Tool] = [
    Tool("travel_overview", "Trips on now, next trip, check-ins to do, mails to review. Mis viajes de un vistazo.\n"
         "What is happening today on a trip in progress, the next trip with days to go, flights whose online check-in is open or about to open, "
         "bookings from mail waiting for review and counts. " + SIN + " viajes, qué viaje tengo, mi próximo viaje, qué hago hoy de viaje, check-in pendiente.",
         Empty, _ann(True), run_overview),
    Tool("trips_list", "List trips (upcoming, ongoing, past, cancelled, all). Lista de viajes.\n"
         "Each trip has title, dates, destination, status, days to go, kinds of segments and what needs review. " + SIN + " mis viajes, viajes pasados, "
         "viajes cancelados, cuándo es mi próximo viaje.", TripsListArgs, _ann(True), run_list),
    Tool("trip_get", "One trip: segments, day-by-day timeline, links, people, expenses and balances. Detalle de un viaje.\n"
         "Takes the trip id or its exact title. Segments carry check-in state, times with their time zone and the mails they came from. " + SIN +
         " vuelos de mi viaje, dónde me alojo, a qué hora sale, itinerario, enlaces de la reserva.", TripArg, _ann(True), run_get),
    Tool("trip_create", "Create a trip by hand with a title and dates. Crear un viaje.\n" + SIN + " nuevo viaje, apunta un viaje, viaje sin reservas.",
         TripCreateArgs, _ann(False), run_create),
    Tool("trip_update", "Rename, mute, cancel, merge, split a trip or move a segment between trips. Editar un viaje.\n"
         "merge_from (confirm=true) merges another trip into this one; split_segments moves some segments into a new trip; move_segment + to_trip "
         "moves one segment ('new' = its own trip, empty = let the grouping place it); delete (confirm=true) removes the trip and its bookings (keep_segments=true keeps them without a trip). "
         + SIN + " renombrar viaje, unir viajes, separar viaje, mover vuelo a otro viaje, silenciar avisos del viaje.", TripUpdateArgs,
         _ann(False, destructive=True, idempotent=False), run_update),
    Tool("segment_add", "Add a flight, train, bus, ferry, car rental, stay or activity by hand. Añadir un tramo o reserva.\n"
         "Times are local at the place; the airport table fills the city and time zone from IATA codes. " + SIN + " añade un vuelo, apunta un hotel, "
         "añadir reserva, he comprado un billete de tren, alquiler de coche.", SegmentAddArgs, _ann(False, idempotent=False), run_segment_add),
    Tool("segment_update", "Edit a segment: times, places, number, seat, terminal, price, status. Editar un tramo.\n"
         + SIN + " cambiar hora del vuelo, cambiar asiento, corregir fecha, el hotel es otro, marcar como cancelado.", SegmentUpdateArgs,
         _ann(False, idempotent=True), run_segment_update),
    Tool("segment_delete", "Delete a segment (confirm=true). Borrar un tramo o reserva.", SegmentDeleteArgs, _ann(False, destructive=True), run_segment_delete),
    Tool("checkin_status", "Online check-in window of each flight: opens, closes, link, done or not. Estado del check-in.\n"
         "Uses the airline table verified 02-10-2026 and says its source; an airline not in the table is reported as unknown. " + SIN +
         " cuándo abre el check-in, puedo hacer ya el check-in, check-in online, hora límite del check-in.", CheckinStatusArgs, _ann(True), run_checkin_status),
    Tool("checkin_done", "Mark a flight's check-in as done (or not). Check-in hecho.\n" + SIN + " ya hice el check-in, marcar check-in, deshacer check-in.",
         CheckinDoneArgs, _ann(False, idempotent=True), run_checkin_done),
    Tool("trip_documents_check", "Will the ID card or passport in Kafka still be valid when the trip ends? Comprobar documentos.\n"
         "Asks Kafka through the hub; if Kafka is down the status is unknown, never an error. Document numbers are never shown. " + SIN +
         " caduca mi pasaporte, DNI en regla para viajar, documentos para el viaje.", TripArg, _ann(True, open_world=True), run_docs),
    Tool("trip_people", "People sharing the trip's expenses: add, rename, remove, which one is the user. Personas del viaje.\n" + SIN +
         " añade a Marta al viaje, quién viaja, yo soy.", PeopleArgs, _ann(False, idempotent=True), run_people),
    Tool("trip_expenses", "A trip's shared expenses with each person's share, balances and transfers. Gastos del viaje.\n" + SIN +
         " gastos compartidos, cuánto llevamos gastado, quién debe a quién, cuentas del viaje.", TripArg, _ann(True), run_expenses),
    Tool("trip_expense_add", "Add a shared expense: who paid, split equal/shares/exact, currency with its rate. Añadir gasto del viaje.\n"
         "from_segment turns a booking's price into one expense. Another currency than the trip's needs the rate you paid. " + SIN +
         " he pagado la cena, apunta un gasto del viaje, pagó Marta, dividir a partes iguales.", ExpenseAddArgs, _ann(False, idempotent=False), run_expense_add),
    Tool("trip_expense_update", "Change a shared expense. Editar gasto del viaje.", ExpenseUpdateArgs, _ann(False, idempotent=True), run_expense_update),
    Tool("trip_expense_delete", "Delete a shared expense (confirm=true). Borrar gasto del viaje.", ExpenseDeleteArgs, _ann(False, destructive=True),
         run_expense_delete),
    Tool("trip_settle", "Balances and the fewest transfers that settle a trip's expenses. Saldar cuentas del viaje.\n" + SIN +
         " quién paga a quién, repartir gastos, liquidar el viaje, cuánto me deben.", TripArg, _ann(True), run_settle),
    Tool("trip_to_ledger", "Send my share of each trip expense not yet sent to Ledger. Pasar mi parte a Ledger.\n"
         "Each expense goes once (remembered); Ledger down or an account in another currency is explained, nothing is invented. dry_run lists what would go. "
         + SIN + " pasa los gastos del viaje a mis cuentas, apunta mi parte en Ledger, registrar gastos del viaje.", ToLedgerArgs,
         _ann(False, idempotent=True, open_world=True), run_to_ledger),
    Tool("trip_ics", "Export a trip (or every upcoming trip) to a calendar .ics file. Exportar al calendario.\n"
         "One event per segment with its time zone, and an alarm when online check-in opens. Saved under data/exports. " + SIN +
         " añadir el viaje al calendario, exportar a ics, calendario de viajes.", IcsArgs, _ann(False, idempotent=True), run_ics),
    Tool("trip_paste", "Read a booking mail pasted as text into segments and trips. Pegar un correo de reserva.\n"
         "Reads schema.org markup, sender rules or the local model; says what was read and what needs review. " + SIN +
         " pega este correo de vuelo, lee esta confirmación de hotel, añadir reserva desde un email.", TripPasteArgs, _ann(False, idempotent=True), run_paste),
    Tool("travel_mail_list", "Travel mails read: waiting for review, filed, ignored. Correos de viajes leídos.\n"
         "Each shows what was read (source schema, rules or model, with evidence lines). Accept with mail_accept, ignore with mail_ignore. " + SIN +
         " correos de reservas pendientes, qué reservas ha leído.", TravelMailListArgs, _ann(True), run_mail_list),
    Tool("travel_mail_read_again", "Ask the local model to read a travel mail from the review list again. Releer reserva con el modelo.",
         MailIdArg, _ann(False, idempotent=True), run_read_again),
    Tool("travel_mail_recheck", "Drop non-bookings from the travel review list. Limpiar la lista de revisión de viajes.\n"
         "Runs the booking-evidence check again over the mails waiting for review and moves marketing, notices and event tickets out of the list. "
         + SIN + " limpiar correos de viajes, quitar publicidad de la lista de reservas.", Empty, _ann(False, idempotent=True), run_recheck),
]
