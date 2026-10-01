import React, { useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { dayLabel, daysBetween, isoDate, locale, shortClock, windowLabel } from "../format.js";
import { PROBLEM } from "../meta.js";
import { Busy, Chip, Confidence, CopyButton, ExtLink, Icon, ICONS, Modal, Progress, StatusPill, Field, useBusy } from "./ui.jsx";

// What to show as "when": { prefix, main, sub, late } — plus the carrier's time window on the day, when it gave one.
export function etaInfo(s, today, t, lang) {
  const info = etaInfoDay(s, today, t, lang);
  if (s.eta_time && !["delivered", "returned", "available_for_pickup"].includes(s.status) && !info.late) {
    info.sub = [info.sub, s.eta_time].filter(Boolean).join(" · ");
  }
  return info;
}

function etaInfoDay(s, today, t, lang) {
  const status = s.status;
  if (status === "delivered") return { prefix: t("eta_delivered"), main: s.delivered_ts ? dayLabel(new Date(s.delivered_ts * 1000), lang) : t("st_delivered"), sub: "" };
  if (status === "returned") return { prefix: "", main: t("st_returned"), sub: "" };
  if (status === "out_for_delivery") return { prefix: t("eta_arrives"), main: t("today"), sub: "" };
  if (status === "available_for_pickup") {
    const bits = [];
    if (s.pickup_deadline) bits.push(t("pickup_until", { date: dayLabel(s.pickup_deadline, lang) }));
    if (s.pickup_place) bits.push(s.pickup_place);
    return { prefix: t("eta_ready"), main: t("eta_pickup"), sub: bits.join(" · ") };
  }
  const from = s.eta_from;
  const to = s.eta_to || s.eta_from;
  if (!from) return { prefix: "", main: t("eta_none"), sub: t("eta_none_hint") };
  if (from !== to) {
    const dTo = daysBetween(today, to);
    const late = dTo !== null && dTo < 0;
    return { prefix: late ? t("eta_was_due") : t("eta_between"), main: windowLabel(from, to, lang), sub: "", late };
  }
  const d = daysBetween(today, from);
  if (d === null) return { prefix: "", main: from, sub: "" };
  if (d < 0) return { prefix: t("eta_was_due"), main: dayLabel(from, lang), sub: t("eta_days_late", { n: -d }), late: true };
  if (d === 0) return { prefix: t("eta_arrives"), main: t("today"), sub: "" };
  if (d === 1) return { prefix: t("eta_arrives"), main: t("tomorrow"), sub: dayLabel(from, lang) };
  if (d < 7) {
    const long = isoDate(from).toLocaleDateString(locale(lang), { weekday: "long", day: "numeric" }).replace(/[,.]/g, "");
    return { prefix: t("eta_arrives"), main: lang === "en" ? t("eta_on", { date: long }) : t("eta_on", { date: long }), sub: "" };
  }
  return { prefix: t("eta_arrives"), main: dayLabel(from, lang), sub: "" };
}

export function Eta({ shipment, className = "" }) {
  const { t, lang, dash } = useApp();
  const info = etaInfo(shipment, dash?.today || new Date().toISOString().slice(0, 10), t, lang);
  return (
    <div className={`ship-eta ${className}`} style={info.late ? { color: "var(--hoard-danger)" } : undefined}>
      {info.prefix && <small>{info.prefix}</small>}
      {info.main}
      {info.sub && <small>{info.sub}</small>}
    </div>
  );
}

export function useRefresh(shipment, onDone) {
  const { t, notify, refreshDash, toastError } = useApp();
  const [busy, run] = useBusy();
  const refresh = () => run("refresh", async () => {
    const r = await api.call("shipment_refresh", { shipment: shipment.id });
    if (r && r.ok === false && r.error) toastError(new Error(r.error));
    else notify(r && r.changed === false ? t("refresh_nochange") : t("refresh_done"));
    await refreshDash();
    onDone?.();
  });
  return [busy.refresh, refresh];
}

export function TrackingNumber({ shipment }) {
  if (!shipment.tracking_number) return null;
  return (
    <span className="mono inline-flex items-center gap-1">
      {shipment.tracking_number}
      <CopyButton text={shipment.tracking_number} />
    </span>
  );
}

export function ShipmentCard({ shipment: s, onChanged }) {
  const { t, lang } = useApp();
  const [refreshing, refresh] = useRefresh(s, onChanged);
  const basis = (s.eta_basis || []).find((b) => b.used) || (s.eta_basis || [])[0];
  const problem = PROBLEM.has(s.status);
  const link = s.tracking_url || s.merchant_url;
  const lastLine = [s.last_location, s.status_text].filter(Boolean).join(" · ");
  return (
    <article className={`panel ship ${s.late || problem ? "card-late" : ""}`} aria-label={s.label || s.tracking_number}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="clamp2" style={{ fontSize: 14 }}>
            <a href={`#/envio/${encodeURIComponent(s.id)}`} style={{ color: "inherit", textDecoration: "none" }}>{s.label || s.item || s.tracking_number || t("parcel")}</a>
          </h3>
          <div className="help trunc">{[s.merchant, s.carrier_name].filter(Boolean).join(" · ") || "—"}</div>
          <TrackingNumber shipment={s} />
        </div>
        <Eta shipment={s} className="text-right" />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={s.status} label={s.status_label} />
        {s.late && <Chip className="chip-danger">{t("late")}</Chip>}
        {s.muted && <Chip title={t("muted_hint")}><Icon d={ICONS.bellOff} size={12} />{t("muted")}</Chip>}
        <span className="ml-auto"><Confidence value={s.eta_confidence} /></span>
      </div>
      <Progress value={s.progress} />
      {lastLine && <p className="clamp2" style={{ fontSize: 12.5 }} title={lastLine}>{lastLine}{s.status_ts ? <span className="help"> · {shortClock(s.status_ts, lang)}</span> : null}</p>}
      {basis && <p className="help clamp2" title={basis.text}>{basis.text}</p>}
      {s.last_error && <p className="clamp2" style={{ color: "var(--hoard-danger)", fontSize: 12 }} title={s.last_error}>{s.last_error}</p>}
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
        {s.mail_only
          ? <span className="help">{t("mail_only")}</span>
          : <Busy className="btn btn-sm btn-primary" busy={refreshing} onClick={refresh}><Icon d={ICONS.refresh} size={13} />{t("check_now")}</Busy>}
        <ExtLink href={link}><Icon d={ICONS.external} size={13} />{t("open_tracking")}</ExtLink>
        <a className="btn btn-sm" href={`#/envio/${encodeURIComponent(s.id)}`}>{t("detail")}</a>
      </div>
    </article>
  );
}

// A one-line row for "today" and "needs attention".
export function CompactRow({ shipment: s, reason }) {
  const { t, dash, lang } = useApp();
  const info = etaInfo(s, dash?.today || "", t, lang);
  return (
    <a className="panel panel-tight flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 no-underline" href={`#/envio/${encodeURIComponent(s.id)}`} style={{ color: "var(--ink)" }}>
      <div className="min-w-[170px] flex-1">
        <div className="trunc font-semibold">{s.label || s.item || s.tracking_number}</div>
        <div className="help trunc">{[s.merchant, s.carrier_name].filter(Boolean).join(" · ")}</div>
      </div>
      <StatusPill status={s.status} label={s.status_label} />
      {reason && <Chip className="chip-amber">{reason}</Chip>}
      <span className="help">{[info.main, info.sub].filter(Boolean).join(" · ")}</span>
    </a>
  );
}

// Why a parcel is in "needs attention".
export function attentionReason(s, t) {
  if (s.status === "available_for_pickup") return [s.pickup_place, s.pickup_deadline && t("pickup_until", { date: s.pickup_deadline })].filter(Boolean).join(" · ") || t("att_pickup");
  if (s.status === "failed_attempt") return t("att_failed");
  if (s.status === "exception") return t("att_exception");
  if (s.status === "returned") return t("att_returned");
  if (s.late) return t("late");
  return t("att_generic");
}

export function AddNumberModal({ onClose }) {
  const { t, notify, refreshDash, carriers, loadCarriers } = useApp();
  const [busy, run] = useBusy();
  const [form, setForm] = useState({ tracking_number: "", carrier: "", label: "", merchant: "", notes: "" });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  React.useEffect(() => { loadCarriers(); }, [loadCarriers]);
  const submit = (e) => {
    e.preventDefault();
    if (!form.tracking_number.trim()) return;
    run("add", async () => {
      const args = { tracking_number: form.tracking_number.trim(), check_now: true };
      for (const k of ["carrier", "label", "merchant", "notes"]) if (form[k].trim()) args[k] = form[k].trim();
      const r = await api.call("shipment_add", args);
      notify(t("added_ok"));
      await refreshDash();
      onClose();
      const id = r?.shipment?.id || r?.id;
      if (id) window.location.hash = `#/envio/${encodeURIComponent(id)}`;
    });
  };
  return (
    <Modal title={t("add_number")} onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        <Field label={t("tracking_number")}>
          <input className="field mono" value={form.tracking_number} onChange={(e) => set("tracking_number", e.target.value)} placeholder="1Z999AA10123456784" required autoComplete="off" />
        </Field>
        <Field label={t("carrier")}>
          <select className="field" value={form.carrier} onChange={(e) => set("carrier", e.target.value)}>
            <option value="">{t("carrier_guess")}</option>
            {(carriers || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("label_what")}><input className="field" value={form.label} onChange={(e) => set("label", e.target.value)} placeholder={t("label_ph")} /></Field>
          <Field label={t("merchant")}><input className="field" value={form.merchant} onChange={(e) => set("merchant", e.target.value)} /></Field>
        </div>
        <Field label={t("notes")}><textarea className="field" rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <Busy type="submit" className="btn btn-primary" busy={busy.add}>{t("add_follow")}</Busy>
        </div>
      </form>
    </Modal>
  );
}
