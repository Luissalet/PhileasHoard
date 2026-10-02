import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { dayLabel, isoDate, locale, money, shortClock, windowLabel } from "../format.js";
import { Busy, Chip, ExtLink, Field, Icon, Modal, useBusy } from "./ui.jsx";

export const KINDS = ["flight", "train", "bus", "ferry", "car", "lodging", "event"];
export const CATEGORIES = ["transport", "lodging", "food", "activities", "shopping", "other"];

export const KIND_ICON = {
  flight: "M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z",
  train: "M7 3h10a2 2 0 012 2v10a3 3 0 01-3 3l2 3h-2l-2-3h-4l-2 3H6l2-3a3 3 0 01-3-3V5a2 2 0 012-2zM5 11h14M8.5 15h.01M15.5 15h.01",
  bus: "M5 4h14a1 1 0 011 1v11a1 1 0 01-1 1H5a1 1 0 01-1-1V5a1 1 0 011-1zM4 11h16M7 20v-3M17 20v-3M8 14h.01M16 14h.01",
  ferry: "M3 17l2 3h14l2-3-9-3zM12 14V5M8 9h8M10 5h4",
  car: "M5 16l1.5-5a2 2 0 011.9-1.5h7.2a2 2 0 011.9 1.5L19 16M3 16h18v3H3zM7 19v1.5M17 19v1.5M7.5 13h.01M16.5 13h.01",
  lodging: "M3 20V8l9-5 9 5v12M3 20h18M9 20v-6h6v6",
  event: "M5 5h14v15H5zM5 10h14M9 3v4M15 3v4",
};

export const TRIP_STATUS_CLASS = { upcoming: "chip-info", ongoing: "chip-accent", past: "", cancelled: "chip-danger" };

export function KindIcon({ kind, size = 16 }) {
  return <Icon d={KIND_ICON[kind] || KIND_ICON.event} size={size} />;
}

// "2026-11-12T09:05" -> "jue 12 nov · 09:05" (the wall-clock time at the place, as the mail gave it).
export function localLabel(iso, lang, { weekday = true } = {}) {
  if (!iso) return "";
  const day = dayLabel(iso.slice(0, 10), lang, { weekday });
  return iso.length > 10 ? `${day} · ${iso.slice(11, 16)}` : day;
}

// A timestamp shown in the time zone of the place it belongs to.
export function tsIn(ts, tz, lang) {
  if (!ts) return "";
  const opts = { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" };
  try {
    return new Date(ts * 1000).toLocaleString(locale(lang), { ...opts, timeZone: tz || undefined }).replace(",", "");
  } catch {
    return shortClock(ts, lang);
  }
}

export const segCount = (t, n) => (n === 1 ? t("trip_segments_1") : t("trip_segments_n", { n }));

export function tripWhen(trip, lang) {
  if (!trip.start_date) return "";
  if (!trip.end_date || trip.end_date === trip.start_date) return dayLabel(trip.start_date, lang, { weekday: false });
  return windowLabel(trip.start_date, trip.end_date || trip.start_date, lang);
}

export function daysToGo(trip, t) {
  const n = trip.days_to_go;
  if (n === null || n === undefined) return "";
  if (n === 0) return t("trip_days_to_go_0");
  if (n === 1) return t("trip_days_to_go_1");
  return t("trip_days_to_go", { n });
}

export function StatusChip({ status }) {
  const { t } = useApp();
  return <Chip className={TRIP_STATUS_CLASS[status] || ""}>{t(`tstatus_${status}`)}</Chip>;
}

export function CheckinChip({ state, className = "" }) {
  const { t } = useApp();
  const cls = { done: "chip-ok", open: "chip-accent", not_open: "chip-info", closed: "chip-danger", unknown_open: "chip-amber" }[state] || "";
  if (!state) return null;
  return <Chip className={`${cls} ${className}`}>{t(`ci_${state}`)}</Chip>;
}

export function TripCard({ trip, today }) {
  const { t, lang } = useApp();
  const first = trip.destination_label || trip.destination || trip.title;
  return (
    <a href={`#/viaje/${encodeURIComponent(trip.id)}`} className="trip-card panel space-y-2" style={{ textDecoration: "none", color: "var(--ink)", display: "block" }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold" style={{ fontSize: 14, overflowWrap: "anywhere" }}>{trip.title || first}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {trip.status === "upcoming" && trip.days_to_go !== null && <Chip className="chip-info">{daysToGo(trip, t)}</Chip>}
          <StatusChip status={trip.status} />
        </span>
      </div>
      <div className="help">{tripWhen(trip, lang)} · {segCount(t, trip.active_segments)}</div>
      <div className="flex flex-wrap items-center gap-1.5">
        {trip.kinds.map((k) => <span key={k} className="chip" title={t(`kind_${k}`)}><KindIcon kind={k} size={13} />{t(`kind_${k}`)}</span>)}
        {trip.needs_review > 0 && <Chip className="chip-amber">{t("trip_review_n", { n: trip.needs_review })}</Chip>}
        {trip.muted && <Chip>{t("trip_muted")}</Chip>}
        {trip.docs?.status === "problem" && <Chip className="chip-danger">{t("docs_status_problem")}</Chip>}
      </div>
      {trip.next && <div className="help trunc">{t("trip_next", { what: `${trip.next.label} · ${localLabel(trip.next.dep_local, lang, { weekday: false })}` })}</div>}
    </a>
  );
}

// ------------------------------------------------------------------ segment card
export function segmentTitle(s) {
  return s.label || s.number || s.kind;
}

export function SegmentSummary({ s }) {
  const { t, lang } = useApp();
  const stay = s.kind === "lodging";
  const car = s.kind === "car";
  const from = s.from_city_label || s.from_name;
  const to = s.to_city_label || s.to_name;
  return (
    <div className="space-y-0.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
        <span className="num">{stay ? t("seg_dep_lodging") : car ? t("seg_dep_car") : t("seg_dep")}: {localLabel(s.dep_local, lang)}{s.dep_tz && !stay ? <span className="help"> {s.dep_tz.split("/").pop().replace("_", " ")}</span> : null}</span>
        {s.arr_local && <span className="num">{stay ? t("seg_arr_lodging") : car ? t("seg_arr_car") : t("seg_arr")}: {localLabel(s.arr_local, lang)}</span>}
      </div>
      {!stay && (from || to) && <div className="help">{[s.from_code && `${s.from_code}`, from].filter(Boolean).join(" ")} → {[s.to_code && `${s.to_code}`, to].filter(Boolean).join(" ")}</div>}
      {stay && s.address && <div className="help" style={{ overflowWrap: "anywhere" }}>{s.address}</div>}
    </div>
  );
}

export function SegmentCard({ s, trip, selectable, selected, onSelect, onEdit, onMove, onDelete, onChanged }) {
  const { t, lang, notify } = useApp();
  const [busy, run] = useBusy();
  const cancelled = s.status === "cancelled";
  const ci = s.checkin;
  const checkinDone = s.checkin_done;
  const toggleDone = () => run("done", async () => {
    await api.call("checkin_done", { segment: s.id, done: !checkinDone });
    await onChanged();
  });
  const toExpense = () => run("exp", async () => {
    await api.call("trip_expense_add", { trip: trip.id, from_segment: s.id });
    notify(t("seg_expense_added"));
    await onChanged();
  });
  const extra = [s.terminal && `${t("seg_terminal")} ${s.terminal}`, s.gate && `Gate ${s.gate}`, s.coach && `${t("seg_coach")} ${s.coach}`, s.seat && `${t("seg_seat")} ${s.seat}`, s.travel_class].filter(Boolean);
  return (
    <article className={`panel space-y-2 seg-card${cancelled ? " seg-cancelled" : ""}`} aria-label={segmentTitle(s)} style={cancelled ? { opacity: 0.7 } : undefined}>
      <div className="flex flex-wrap items-center gap-2">
        {selectable && <input type="checkbox" checked={!!selected} onChange={(e) => onSelect(s.id, e.target.checked)} aria-label={`${t("trip_split")}: ${segmentTitle(s)}`} />}
        <span style={{ color: "var(--accent)" }}><KindIcon kind={s.kind} /></span>
        <span className="font-semibold" style={{ overflowWrap: "anywhere", textDecoration: cancelled ? "line-through" : "none" }}>{segmentTitle(s)}</span>
        <span className="ml-auto flex flex-wrap items-center gap-1.5">
          {cancelled && <Chip className="chip-danger">{t("seg_cancelled")}</Chip>}
          {s.needs_review && <Chip className="chip-amber">{t("seg_review")}</Chip>}
          {s.source === "model" && <Chip className="chip-amber" title={t("seg_model")}>{t("seg_model")}</Chip>}
          {s.edited && <Chip>{t("seg_edited")}</Chip>}
          {s.kind === "flight" && !cancelled && ci?.applies && <CheckinChip state={ci.state} />}
        </span>
      </div>
      <SegmentSummary s={s} />
      <div className="flex flex-wrap items-center gap-1.5">
        {s.booking_ref && <Chip className="mono">{s.booking_ref}</Chip>}
        {extra.map((x) => <Chip key={x}>{x}</Chip>)}
        {s.passengers?.length > 0 && <Chip>{s.passengers.join(", ")}</Chip>}
        {s.price !== null && s.price !== undefined && <Chip>{money(s.price, s.currency || trip.currency, lang)}</Chip>}
      </div>
      {s.kind === "flight" && !cancelled && ci?.applies && (
        <div className="help space-y-0.5">
          {ci.opens_ts ? <div>{t("ci_opens", { when: tsIn(ci.opens_ts, s.dep_tz, lang) })}{ci.closes_ts ? ` · ${t("ci_closes", { when: tsIn(ci.closes_ts, s.dep_tz, lang) })}` : ""}</div> : null}
          <div>{ci.known ? (lang === "en" ? ci.note_en : ci.note_es) : t("ci_unknown_rule")}</div>
        </div>
      )}
      {s.evidence?.length > 0 && (s.source === "model" || s.needs_review) && (
        <details>
          <summary className="help">{t("seg_evidence")} · {t("seg_confidence", { n: s.confidence })}</summary>
          <ul className="help m-0 mt-1 list-disc pl-5">{s.evidence.map((e, i) => <li key={i} className="mono">{e}</li>)}</ul>
        </details>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-0.5">
        {(s.links || []).slice(0, 3).map((l) => <ExtLink key={l.url} href={l.url} className="btn btn-sm"><Icon d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" size={13} />{l.kind === "checkin" ? t("ci_open_link") : l.label || l.kind}</ExtLink>)}
        {s.kind === "flight" && !cancelled && (
          <Busy className="btn btn-sm" busy={busy.done} onClick={toggleDone}>{checkinDone ? t("ci_mark_undone") : t("ci_mark_done")}</Busy>
        )}
        {s.price > 0 && <Busy className="btn btn-sm" busy={busy.exp} onClick={toExpense}>{t("seg_to_expense")}</Busy>}
        <button type="button" className="btn btn-sm" onClick={() => onEdit(s)}>{t("seg_edit")}</button>
        <button type="button" className="btn btn-sm" onClick={() => onMove(s)}>{t("seg_move")}</button>
        <button type="button" className="btn btn-sm btn-danger" onClick={() => onDelete(s)}>{t("delete")}</button>
      </div>
    </article>
  );
}

// ------------------------------------------------------------------ segment editor
const FIELDS = ["carrier", "number", "booking_ref", "provider", "from_code", "from_name", "to_code", "to_name", "dep_local", "arr_local", "terminal", "seat", "coach", "travel_class", "price", "currency", "address", "notes", "status"];

function blank(kind = "flight") {
  return { kind, carrier: "", number: "", booking_ref: "", provider: "", from_code: "", from_name: "", to_code: "", to_name: "", dep_local: "", arr_local: "", terminal: "", seat: "", coach: "", travel_class: "", price: "", currency: "", address: "", notes: "", status: "confirmed" };
}

function fromSegment(s) {
  const draft = blank(s.kind);
  for (const key of FIELDS) draft[key] = s[key] === null || s[key] === undefined ? "" : String(s[key]);
  return draft;
}

export function SegmentEditor({ segment, trips = [], tripId = "", onClose, onSaved }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const editing = !!segment;
  const original = useMemo(() => (segment ? fromSegment(segment) : blank()), [segment]);
  const [draft, setDraft] = useState(original);
  const [trip, setTrip] = useState(tripId);
  const set = (key, value) => setDraft((d) => ({ ...d, [key]: value }));
  const kind = draft.kind;
  const transport = kind === "flight" || kind === "train" || kind === "bus" || kind === "ferry";
  const stay = kind === "lodging";
  const car = kind === "car";
  const depLabel = stay ? t("seg_dep_lodging") : car ? t("seg_dep_car") : t("seg_dep");
  const arrLabel = stay ? t("seg_arr_lodging") : car ? t("seg_arr_car") : t("seg_arr");

  const save = (e) => {
    e.preventDefault();
    run("save", async () => {
      const keys = editing ? FIELDS.filter((k) => String(draft[k]) !== String(original[k])) : FIELDS.filter((k) => String(draft[k]) !== "" && !(k === "status" && draft[k] === "confirmed"));
      const args = {};
      for (const k of keys) args[k] = k === "price" ? (draft[k] === "" ? 0 : Number(draft[k])) : draft[k];
      if (editing) {
        if (!keys.length) { notify(t("seg_nothing_changed")); onClose(); return; }
        await api.call("segment_update", { segment: segment.id, ...args });
        notify(t("seg_saved"));
      } else {
        await api.call("segment_add", { kind, trip, ...args });
        notify(t("seg_added"));
      }
      await onSaved();
      onClose();
    });
  };
  return (
    <Modal title={editing ? t("seg_editor_edit") : t("seg_editor_add")} onClose={onClose} wide>
      <form className="space-y-3" onSubmit={save} noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          {!editing && (
            <Field label={t("seg_kind")}>
              <select className="field" value={kind} onChange={(e) => set("kind", e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{t(`kind_${k}`)}</option>)}</select>
            </Field>
          )}
          {!editing && (
            <Field label={t("seg_trip")}>
              <select className="field" value={trip} onChange={(e) => setTrip(e.target.value)}>
                <option value="">{t("seg_trip_auto")}</option>
                {trips.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
              </select>
            </Field>
          )}
          {transport && <Field label={t("seg_carrier")}><input className="field" value={draft.carrier} onChange={(e) => set("carrier", e.target.value)} /></Field>}
          {transport && <Field label={t("seg_number")}><input className="field" value={draft.number} onChange={(e) => set("number", e.target.value)} placeholder={kind === "flight" ? "IB3166" : ""} /></Field>}
          {(stay || car || kind === "event") && <Field label={t("seg_provider")}><input className="field" value={draft.provider} onChange={(e) => set("provider", e.target.value)} /></Field>}
          <Field label={t("seg_ref")}><input className="field" value={draft.booking_ref} onChange={(e) => set("booking_ref", e.target.value)} /></Field>
          {kind === "flight" && <Field label={t("seg_from_code")}><input className="field" maxLength={3} value={draft.from_code} onChange={(e) => set("from_code", e.target.value.toUpperCase())} placeholder="MAD" /></Field>}
          {kind === "flight" && <Field label={t("seg_to_code")}><input className="field" maxLength={3} value={draft.to_code} onChange={(e) => set("to_code", e.target.value.toUpperCase())} placeholder="LIS" /></Field>}
          {(transport && kind !== "flight") && <Field label={t("seg_from_name")}><input className="field" value={draft.from_name} onChange={(e) => set("from_name", e.target.value)} /></Field>}
          {(transport && kind !== "flight") && <Field label={t("seg_to_name")}><input className="field" value={draft.to_name} onChange={(e) => set("to_name", e.target.value)} /></Field>}
          {car && <Field label={t("seg_from_name")}><input className="field" value={draft.from_name} onChange={(e) => set("from_name", e.target.value)} /></Field>}
          {car && <Field label={t("seg_to_name")}><input className="field" value={draft.to_name} onChange={(e) => set("to_name", e.target.value)} /></Field>}
          {stay && <Field label={t("seg_address")} className="sm:col-span-2"><input className="field" value={draft.address} onChange={(e) => set("address", e.target.value)} /></Field>}
          <Field label={depLabel} hint={t("seg_local_hint")}><input className="field" type="datetime-local" value={draft.dep_local.slice(0, 16)} onChange={(e) => set("dep_local", e.target.value)} /></Field>
          <Field label={arrLabel} hint={t("seg_local_hint")}><input className="field" type="datetime-local" value={draft.arr_local.slice(0, 16)} onChange={(e) => set("arr_local", e.target.value)} /></Field>
          {transport && <Field label={t("seg_terminal")}><input className="field" value={draft.terminal} onChange={(e) => set("terminal", e.target.value)} /></Field>}
          {transport && <Field label={kind === "train" ? `${t("seg_coach")} / ${t("seg_seat")}` : t("seg_seat")}><input className="field" value={draft.seat} onChange={(e) => set("seat", e.target.value)} /></Field>}
          <Field label={t("seg_price")}><input className="field" type="number" min="0" step="0.01" value={draft.price} onChange={(e) => set("price", e.target.value)} /></Field>
          <Field label={t("seg_currency")}><input className="field" maxLength={3} value={draft.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} placeholder="EUR" /></Field>
          {editing && (
            <Field label={t("seg_status")}>
              <select className="field" value={draft.status} onChange={(e) => set("status", e.target.value)}>
                <option value="confirmed">{t("seg_status_confirmed")}</option>
                <option value="cancelled">{t("seg_status_cancelled")}</option>
              </select>
            </Field>
          )}
          <Field label={t("notes")} className="sm:col-span-2"><textarea className="field" rows={2} value={draft.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <Busy type="submit" className="btn btn-primary" busy={busy.save}>{t("save")}</Busy>
        </div>
      </form>
    </Modal>
  );
}

// ------------------------------------------------------------------ paste a booking mail
export function PasteModal({ trips = [], tripId = "", onClose, onDone }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const [subject, setSubject] = useState("");
  const [from, setFrom] = useState("");
  const [text, setText] = useState("");
  const [trip, setTrip] = useState(tripId);
  const [result, setResult] = useState(null);
  const submit = (e) => {
    e.preventDefault();
    run("paste", async () => {
      const r = await api.call("trip_paste", { subject, from_address: from, text, trip });
      setResult(r);
      const n = (r.segments || []).length;
      if (n) {
        notify(t("trip_paste_found", { n }));
        await onDone(r);
      }
    });
  };
  const n = result ? (result.segments || []).length : 0;
  return (
    <Modal title={t("trip_paste_title")} onClose={onClose} wide>
      <form className="space-y-3" onSubmit={submit} noValidate>
        <p className="help">{t("trip_paste_help")}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("trip_paste_subject")}><input className="field" value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
          <Field label={t("trip_paste_from")}><input className="field" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="reservas@…" /></Field>
        </div>
        {trips.length > 0 && (
          <Field label={t("seg_trip")}>
            <select className="field" value={trip} onChange={(e) => setTrip(e.target.value)}>
              <option value="">{t("seg_trip_auto")}</option>
              {trips.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
            </select>
          </Field>
        )}
        <Field label={t("trip_paste_text")}><textarea className="field" rows={9} value={text} onChange={(e) => setText(e.target.value)} required /></Field>
        {result && (
          <div className={`banner ${n ? "banner-info" : "banner-warn"}`} role="status">
            {n ? t("trip_paste_found", { n }) : t("trip_paste_none")}
            {result.model?.status === "no_model" && <div className="help">{t("trip_paste_model")}</div>}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>{result && n ? t("ok") : t("cancel")}</button>
          <Busy type="submit" className="btn btn-primary" busy={busy.paste} disabled={text.trim().length < 10}>{t("trip_paste_go")}</Busy>
        </div>
      </form>
    </Modal>
  );
}

// ------------------------------------------------------------------ new trip
export function NewTripModal({ onClose }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const submit = (e) => {
    e.preventDefault();
    run("create", async () => {
      const r = await api.call("trip_create", { title, start_date: start, end_date: end, currency });
      notify(t("saved"));
      onClose();
      window.location.hash = `#/viaje/${encodeURIComponent(r.trip.id)}`;
    });
  };
  return (
    <Modal title={t("trip_new_title")} onClose={onClose}>
      <form className="space-y-3" onSubmit={submit} noValidate>
        <Field label={t("trip_title")}><input className="field" value={title} onChange={(e) => setTitle(e.target.value)} required /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("trip_start")}><input className="field" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label={t("trip_end")}><input className="field" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        </div>
        <Field label={t("trip_currency")}><input className="field" maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} /></Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <Busy type="submit" className="btn btn-primary" busy={busy.create} disabled={!title.trim()}>{t("trip_create")}</Busy>
        </div>
      </form>
    </Modal>
  );
}

// Trips other than `exceptId`, newest first, for the pickers.
export function useTripChoices(exceptId) {
  const [trips, setTrips] = useState([]);
  useEffect(() => {
    let live = true;
    api.call("trips_list", { filter: "all" }).then((r) => { if (live) setTrips((r.trips || []).filter((x) => x.id !== exceptId)); }).catch(() => {});
    return () => { live = false; };
  }, [exceptId]);
  return trips;
}

export { isoDate };
