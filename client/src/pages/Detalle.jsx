import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { Eta, TrackingNumber, useRefresh } from "../components/cards.jsx";
import { Busy, Chip, Confidence, CopyButton, Empty, ErrorBox, ExtLink, Field, Icon, ICONS, Progress, Rel, Section, StatusPill, useBusy, useLoad } from "../components/ui.jsx";
import { clock, dayLabel, shortClock, windowLabel } from "../format.js";
import { BASIS_ICON, STATUS_META } from "../meta.js";

function Header({ s, onChanged }) {
  const { t, notify, refreshDash, confirm } = useApp();
  const [busy, run] = useBusy();
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(s.label || "");
  const [refreshing, refresh] = useRefresh(s, onChanged);
  useEffect(() => setLabel(s.label || ""), [s.label]);

  const update = (key, values, message) => run(key, async () => {
    await api.call("shipment_update", { shipment: s.id, ...values });
    if (message) notify(message);
    await refreshDash();
    await onChanged();
  });
  const saveLabel = (e) => {
    e.preventDefault();
    update("label", { label: label.trim() }, t("saved")).then(() => setEditing(false));
  };
  const markDelivered = async () => {
    const ok = await confirm({ title: t("mark_delivered"), message: t("mark_delivered_msg"), confirmLabel: t("mark_delivered"), danger: false });
    if (ok) update("delivered", { status: "delivered" }, t("saved"));
  };
  const remove = async () => {
    const ok = await confirm({ title: t("delete_shipment"), message: t("delete_shipment_msg", { name: s.label || s.tracking_number }), confirmLabel: t("delete") });
    if (!ok) return;
    run("delete", async () => {
      await api.call("shipment_delete", { shipment: s.id, confirm: true });
      notify(t("deleted"));
      await refreshDash();
      window.location.hash = "#/";
    });
  };
  const link = s.tracking_url || s.merchant_url;
  return (
    <header className="space-y-3">
      <a href="#/" className="btn-link inline-flex items-center gap-1 no-underline"><Icon d={ICONS.back} size={14} />{t("back_to_list")}</a>
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          {editing ? (
            <form className="flex flex-wrap items-center gap-2" onSubmit={saveLabel}>
              <input className="field" style={{ maxWidth: 420, fontSize: 18 }} value={label} onChange={(e) => setLabel(e.target.value)} aria-label={t("label_what")} autoFocus />
              <Busy type="submit" className="btn btn-primary btn-sm" busy={busy.label}>{t("save")}</Busy>
              <button type="button" className="btn btn-sm" onClick={() => { setEditing(false); setLabel(s.label || ""); }}>{t("cancel")}</button>
            </form>
          ) : (
            <h1 className="flex flex-wrap items-center gap-2" style={{ overflowWrap: "anywhere" }}>
              {s.label || s.item || s.tracking_number || t("parcel")}
              <button type="button" className="copy-btn" onClick={() => setEditing(true)} title={t("rename")} aria-label={t("rename")}><Icon d={ICONS.pencil} size={16} /></button>
            </h1>
          )}
          <div className="help mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
            {s.merchant && <span>{s.merchant}</span>}
            {s.order_ref && <span>{t("order")} <span className="mono">{s.order_ref}</span></span>}
            <span>{s.carrier_name || s.carrier || "—"}</span>
            <TrackingNumber shipment={s} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={s.status} label={s.status_label} />
          {s.muted && <Chip><Icon d={ICONS.bellOff} size={12} />{t("muted")}</Chip>}
          {s.archived && <Chip>{t("archived")}</Chip>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {!s.mail_only && <Busy className="btn btn-primary" busy={refreshing} onClick={refresh}><Icon d={ICONS.refresh} size={14} />{t("check_now")}</Busy>}
        <ExtLink href={link} className="btn"><Icon d={ICONS.external} size={14} />{t("open_tracking")}</ExtLink>
        <Busy className="btn" busy={busy.mute} onClick={() => update("mute", { muted: !s.muted })}><Icon d={s.muted ? ICONS.bell : ICONS.bellOff} size={14} />{s.muted ? t("unmute") : t("mute")}</Busy>
        <Busy className="btn" busy={busy.archive} onClick={() => update("archive", { archived: !s.archived }, t("saved"))}><Icon d={ICONS.archive} size={14} />{s.archived ? t("unarchive") : t("archive")}</Busy>
        {s.status !== "delivered" && <Busy className="btn" busy={busy.delivered} onClick={markDelivered}><Icon d={ICONS.check} size={14} />{t("mark_delivered")}</Busy>}
        <Busy className="btn btn-danger" busy={busy.delete} onClick={remove}><Icon d={ICONS.trash} size={14} />{t("delete")}</Busy>
      </div>
      {s.mail_only && <p className="help">{t("mail_only")}</p>}
      {s.last_error && <div className="banner banner-danger">{s.last_error}</div>}
    </header>
  );
}

function EtaPanel({ s, similar, onChanged }) {
  const { t, lang } = useApp();
  const [busy, run] = useBusy();
  const recompute = () => run("eta", async () => { await api.call("eta_explain", { shipment: s.id }); await onChanged(); });
  const basis = s.eta_basis || [];
  const carrierWin = s.carrier_eta_from ? (s.carrier_eta_to && s.carrier_eta_to !== s.carrier_eta_from ? windowLabel(s.carrier_eta_from, s.carrier_eta_to, lang) : dayLabel(s.carrier_eta_from, lang)) : "";
  const shopWin = s.merchant_eta_from ? (s.merchant_eta_to && s.merchant_eta_to !== s.merchant_eta_from ? windowLabel(s.merchant_eta_from, s.merchant_eta_to, lang) : dayLabel(s.merchant_eta_from, lang)) : "";
  return (
    <Section id="sec-eta" title={t("when_arrives")} actions={<Busy className="btn btn-sm" busy={busy.eta} onClick={recompute}>{t("recompute")}</Busy>}>
      <div className="panel space-y-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <Eta shipment={s} />
          <div className="space-y-1">
            <Confidence value={s.eta_confidence} />
            {s.late && <div><Chip className="chip-danger">{t("late")}</Chip></div>}
          </div>
          <div className="min-w-[160px] flex-1"><Progress value={s.progress} /><div className="help mt-1">{s.status_label} · {s.progress}%</div></div>
        </div>
        {(carrierWin || shopWin || s.promise_min_days) && (
          <div className="help flex flex-wrap gap-x-4 gap-y-1">
            {carrierWin && <span>{t("basis_carrier")}: <b style={{ color: "var(--ink)" }}>{carrierWin}</b></span>}
            {shopWin && <span>{t("basis_shop")}: <b style={{ color: "var(--ink)" }}>{shopWin}</b>{s.merchant_eta_text ? ` («${s.merchant_eta_text}»)` : ""}</span>}
            {s.promise_min_days ? <span>{t("basis_promise")}: <b style={{ color: "var(--ink)" }}>{t(s.promise_business ? "promise_biz" : "promise_days", { a: s.promise_min_days, b: s.promise_max_days })}</b></span> : null}
          </div>
        )}
        <div>
          <h3 className="mb-1">{t("eta_basis")}</h3>
          {basis.length === 0 ? <p className="help">{t("eta_basis_none")}</p> : (
            <ul className="m-0 list-none space-y-1.5 p-0">
              {basis.map((b, i) => (
                <li key={i} className="flex gap-2" style={{ opacity: b.used ? 1 : 0.65 }}>
                  <span title={b.used ? t("basis_used") : t("basis_not_used")} style={{ width: 16, flex: "none", color: b.used ? "var(--hoard-success)" : "var(--hoard-text-dim)" }}>{b.used ? "✓" : "·"}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Chip><Icon d={BASIS_ICON[b.source] || BASIS_ICON.typical} size={12} />{t(`basis_${b.source}`)}</Chip>
                      <span className="help">{b.eta_from ? (b.eta_to && b.eta_to !== b.eta_from ? windowLabel(b.eta_from, b.eta_to, lang) : dayLabel(b.eta_from, lang)) : ""}</span>
                      <span className="help ml-auto">{t("weight")} {b.weight}</span>
                    </div>
                    <div style={{ overflowWrap: "anywhere" }}>{b.text}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="mb-1">{t("similar")}</h3>
          {similar.length === 0 ? <p className="help">{t("similar_none")}</p> : (
            <div className="overflow-x-auto">
              <table>
                <thead><tr><th>{t("label")}</th><th>{t("carrier")}</th><th className="r">{t("days")}</th><th>{t("shipped_delivered")}</th></tr></thead>
                <tbody>
                  {similar.map((x, i) => (
                    <tr key={i}>
                      <td>{x.label}{x.merchant ? <span className="help"> · {x.merchant}</span> : null}</td>
                      <td>{x.carrier}</td>
                      <td className="r num">{x.days}</td>
                      <td className="whitespace-nowrap">{[x.shipped && dayLabel(x.shipped, lang, { weekday: false }), x.delivered && dayLabel(x.delivered, lang, { weekday: false })].filter(Boolean).join(" → ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

function PickupPanel({ s }) {
  const { t, lang } = useApp();
  const [shown, setShown] = useState(false);
  if (!s.pickup_code && !s.pickup_place && !s.pickup_deadline) return null;
  return (
    <Section id="sec-pickup" title={t("pickup")}>
      <div className="panel space-y-2">
        <dl className="m-0 grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
          {s.pickup_place && <><dt className="help">{t("pickup_place")}</dt><dd className="m-0">{s.pickup_place}</dd></>}
          {s.pickup_deadline && <><dt className="help">{t("pickup_deadline")}</dt><dd className="m-0">{dayLabel(s.pickup_deadline, lang, { year: true })}</dd></>}
          {s.pickup_code && (
            <>
              <dt className="help">{t("pickup_code")}</dt>
              <dd className="m-0">
                {shown
                  ? <span className="mono inline-flex items-center gap-1" style={{ fontSize: 15 }}>{s.pickup_code}<CopyButton text={s.pickup_code} /></span>
                  : <button type="button" className="btn btn-sm" onClick={() => setShown(true)}>{t("show_code")}</button>}
              </dd>
            </>
          )}
        </dl>
      </div>
    </Section>
  );
}

function Timeline({ events }) {
  const { t, lang } = useApp();
  const sorted = [...events].sort((a, b) => b.ts - a.ts);
  return (
    <Section id="sec-events" title={t("timeline")} count={events.length}>
      {sorted.length === 0 ? <p className="help">{t("timeline_none")}</p> : (
        <div className="panel">
          <ul className="tl">
            {sorted.map((e) => {
              const meta = STATUS_META[e.status] || STATUS_META.unknown;
              return (
                <li key={e.id ?? `${e.ts}-${e.description}`} style={{ "--c": meta.color }}>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusPill status={e.status} />
                    <Chip>{t(`src_${e.source}`) === `src_${e.source}` ? e.source : t(`src_${e.source}`)}</Chip>
                    <span className="help ml-auto" title={clock(e.ts, lang)}>{shortClock(e.ts, lang)}</span>
                  </div>
                  <div style={{ overflowWrap: "anywhere" }}>{e.description}</div>
                  {e.location && <div className="help">{e.location}</div>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Section>
  );
}

function MailsPanel({ mails }) {
  const { t, lang } = useApp();
  if (!mails.length) return null;
  return (
    <Section id="sec-mails" title={t("mails_fed")} count={mails.length}>
      <div className="space-y-2">
        {mails.map((m) => (
          <article key={m.message_id} className="panel panel-tight space-y-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold" style={{ overflowWrap: "anywhere" }}>{m.subject || t("no_subject")}</span>
              <span className="help ml-auto">{shortClock(m.ts, lang)}</span>
            </div>
            <div className="help" style={{ overflowWrap: "anywhere" }}>{m.from_address}</div>
            {m.snippet && <p className="help clamp2" title={m.snippet}>{m.snippet}</p>}
          </article>
        ))}
      </div>
    </Section>
  );
}

function EditForm({ s, onChanged }) {
  const { t, notify, refreshDash, carriers, loadCarriers } = useApp();
  const [busy, run] = useBusy();
  const init = () => ({ merchant: s.merchant || "", item: s.item || "", carrier: s.carrier || "", tracking_number: s.tracking_number || "", origin_country: s.origin_country || "", notes: s.notes || "" });
  const [f, setF] = useState(init);
  useEffect(() => { loadCarriers(); }, [loadCarriers]);
  useEffect(() => setF(init()), [s.id, s.merchant, s.item, s.carrier, s.tracking_number, s.origin_country, s.notes]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k, v) => setF((o) => ({ ...o, [k]: v }));
  const base = init();
  const changed = Object.keys(f).filter((k) => f[k] !== base[k]);
  const submit = (e) => {
    e.preventDefault();
    if (!changed.length) return;
    run("save", async () => {
      const values = {};
      for (const k of changed) values[k] = k === "origin_country" ? f[k].trim().toUpperCase() : f[k].trim();
      await api.call("shipment_update", { shipment: s.id, ...values });
      notify(t("saved"));
      await refreshDash();
      await onChanged();
    });
  };
  return (
    <Section id="sec-edit" title={t("edit_data")}>
      <form className="panel space-y-3" onSubmit={submit}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("merchant")}><input className="field" value={f.merchant} onChange={(e) => set("merchant", e.target.value)} /></Field>
          <Field label={t("item")}><input className="field" value={f.item} onChange={(e) => set("item", e.target.value)} /></Field>
          <Field label={t("carrier")}>
            <select className="field" value={f.carrier} onChange={(e) => set("carrier", e.target.value)}>
              <option value="">{t("carrier_guess")}</option>
              {(carriers || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              {f.carrier && !(carriers || []).some((c) => c.id === f.carrier) && <option value={f.carrier}>{f.carrier}</option>}
            </select>
          </Field>
          <Field label={t("tracking_number")}><input className="field mono" value={f.tracking_number} onChange={(e) => set("tracking_number", e.target.value)} autoComplete="off" /></Field>
          <Field label={t("origin_country")} hint={t("origin_country_hint")}><input className="field" maxLength={2} style={{ textTransform: "uppercase", maxWidth: 100 }} value={f.origin_country} onChange={(e) => set("origin_country", e.target.value)} placeholder="NL" /></Field>
        </div>
        <Field label={t("notes")}><textarea className="field" rows={2} value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
        <Busy type="submit" className="btn btn-primary btn-sm" busy={busy.save} disabled={!changed.length}>{t("save")}</Busy>
      </form>
    </Section>
  );
}

function SourcesPanel({ s, sources }) {
  const { t } = useApp();
  const name = (x) => (typeof x === "string" ? x : x?.name || x?.id || x?.source || JSON.stringify(x));
  return (
    <Section id="sec-sources" title={t("sources_title")}>
      <div className="panel space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {sources.length ? sources.map((x, i) => <Chip key={i} className="chip-ok">{name(x)}</Chip>) : <span className="help">{t("sources_none")}</span>}
        </div>
        <dl className="m-0 grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
          <dt className="help">{t("last_check")}</dt><dd className="m-0">{s.last_check_ts ? <Rel ts={s.last_check_ts} /> : t("never")}{s.check_count ? <span className="help"> · {t("n_checks", { n: s.check_count, f: s.fail_count || 0 })}</span> : null}</dd>
          <dt className="help">{t("next_check")}</dt><dd className="m-0">{s.next_check_ts ? <Rel ts={s.next_check_ts} /> : "—"}</dd>
          {s.last_error && <><dt className="help">{t("last_error")}</dt><dd className="m-0" style={{ color: "var(--hoard-danger)", overflowWrap: "anywhere" }}>{s.last_error}</dd></>}
        </dl>
      </div>
    </Section>
  );
}

export default function Detalle({ param }) {
  const { t } = useApp();
  const { data, error, loading, reload } = useLoad(() => api.shipment(param), [param]);
  if (loading && !data) return <div className="space-y-3"><a href="#/" className="btn-link">{t("back_to_list")}</a><p className="help">…</p></div>;
  if (!data) {
    return (
      <div className="space-y-3">
        <a href="#/" className="btn-link">{t("back_to_list")}</a>
        <ErrorBox error={error} />
        <Empty>{t("not_found")}</Empty>
      </div>
    );
  }
  const s = data.shipment;
  return (
    <div className="space-y-6">
      <Header s={s} onChanged={reload} />
      <ErrorBox error={error} />
      <EtaPanel s={s} similar={data.similar || []} onChanged={reload} />
      <PickupPanel s={s} />
      <div className="grid gap-6 xl:grid-cols-2">
        <Timeline events={data.events || []} />
        <div className="space-y-6">
          <MailsPanel mails={data.mails || []} />
          <SourcesPanel s={s} sources={data.sources || []} />
        </div>
      </div>
      <EditForm s={s} onChanged={reload} />
    </div>
  );
}
