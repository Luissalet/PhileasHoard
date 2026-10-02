import React, { useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { useMailScan } from "../components/hooks.js";
import { Busy, Chip, CopyButton, Empty, ErrorBox, ExtLink, Field, Icon, ICONS, Rel, Section, StatusPill, Tabs, useBusy, useLoad } from "../components/ui.jsx";
import { shortClock } from "../format.js";
import { KindIcon, localLabel, segCount } from "../components/travel.jsx";

function StatusCard({ onScan, scanning }) {
  const { t, dash } = useApp();
  const { data, error, loading, reload } = useLoad(() => api.call("mail_status"), []);
  const accounts = data?.accounts || [];
  const label = (a) => (typeof a === "string" ? a : a.account || a.name || a.imap_user || a.user || JSON.stringify(a));
  return (
    <Section id="sec-mailstatus" title={t("mail_status")} actions={<button type="button" className="btn btn-sm" onClick={reload}>{t("recheck")}</button>}>
      <div className="panel space-y-2">
        {loading && !data ? <p className="help">…</p> : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Chip className={data?.ok ? "chip-ok" : "chip-danger"}>{data?.ok ? t("mail_ok") : t("mail_not_ok")}</Chip>
              {dash?.mail?.enabled === false && <Chip className="chip-amber">{t("foot_mail_off")}</Chip>}
              <span className="help">{t("foot_mail")}: {dash?.mail?.last_scan_ts ? <Rel ts={dash.mail.last_scan_ts} /> : t("never")}</span>
            </div>
            {data?.ok === false && data.error && <p style={{ color: "var(--hoard-danger)" }}>{data.error} <a href="#/ajustes">{t("nav_settings")}</a></p>}
            <ErrorBox error={error} />
            {data?.faustus_dir ? <p className="help">{t("faustus_folder")}: <span className="mono">{data.faustus_dir}</span></p> : null}
            {accounts.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                <span className="help">{t("accounts")}:</span>
                {accounts.map((a, i) => <Chip key={i}>{label(a)}</Chip>)}
              </div>
            )}
          </>
        )}
      </div>
    </Section>
  );
}

function ScanForm({ onDone }) {
  const { t } = useApp();
  const [days, setDays] = useState("");
  const [query, setQuery] = useState("");
  const [scanning, scan] = useMailScan(onDone);
  const submit = (e) => {
    e.preventDefault();
    const args = {};
    if (days) args.since_days = Number(days);
    if (query.trim()) args.query = query.trim();
    scan(args);
  };
  return (
    <Section id="sec-scan" title={t("scan_title")}>
      <form className="panel flex flex-wrap items-end gap-3" onSubmit={submit}>
        <Busy type="button" className="btn btn-primary" busy={scanning && !days && !query} onClick={() => scan()}><Icon d={ICONS.mail} size={14} />{t("read_now")}</Busy>
        <Field label={t("scan_days")} className="w-[130px]"><input className="field" type="number" min="1" max="365" value={days} onChange={(e) => setDays(e.target.value)} placeholder="30" /></Field>
        <Field label={t("scan_query")} className="min-w-[180px] flex-1"><input className="field" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("scan_query_ph")} /></Field>
        <Busy type="submit" className="btn" busy={scanning && (!!days || !!query)} disabled={!days && !query.trim()}>{t("scan_back")}</Busy>
      </form>
    </Section>
  );
}

function Facts({ found }) {
  const { t } = useApp();
  if (!found) return null;
  const numbers = (found.numbers || []).map((n) => n.number || n);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {found.merchant && <Chip>{t("merchant")}: {found.merchant}</Chip>}
      {found.carrier && <Chip>{t("carrier")}: {found.carrier}</Chip>}
      {found.status && <StatusPill status={found.status} />}
      {found.order_ref && <Chip>{t("order")}: {found.order_ref}</Chip>}
      {numbers.map((n) => <Chip key={n} className="mono">{n}</Chip>)}
      {found.eta_from && <Chip>{t("eta")}: {found.eta_from}</Chip>}
    </div>
  );
}

function MailRow({ mail: m, review, onChanged }) {
  const { t, lang, notify, refreshDash } = useApp();
  const [busy, run] = useBusy();
  const act = (name, message) => run(name, async () => {
    const r = await api.call(name, { message_id: m.message_id });
    if (r && r.ok === false) throw new Error(r.error || "error");
    notify(message);
    await refreshDash();
    onChanged();
  });
  const reasons = m.found?.reasons || [];
  return (
    <article className="panel space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold" style={{ overflowWrap: "anywhere" }}>{m.subject || t("no_subject")}</span>
        <span className="help ml-auto">{shortClock(m.ts, lang)}</span>
      </div>
      <div className="help" style={{ overflowWrap: "anywhere" }}>{m.from_address}{m.score !== undefined && m.score !== null ? ` · ${t("score")} ${m.score}` : ""}</div>
      {m.snippet && <p className="help clamp2" title={m.snippet}>{m.snippet}</p>}
      <Facts found={m.found} />
      {reasons.length > 0 && <p className="help">{t("reasons")}: {reasons.join(" · ")}</p>}
      <div className="flex flex-wrap items-center gap-2 pt-0.5">
        {review ? (
          <>
            <Busy className="btn btn-sm btn-primary" busy={busy.mail_accept} onClick={() => act("mail_accept", t("accepted"))}>{t("accept")}</Busy>
            <Busy className="btn btn-sm" busy={busy.mail_ignore} onClick={() => act("mail_ignore", t("ignored"))}>{t("ignore")}</Busy>
          </>
        ) : (
          m.shipment_id && <a className="btn btn-sm" href={`#/envio/${encodeURIComponent(m.shipment_id)}`}>{t("see_parcel")}</a>
        )}
        {!review && m.state && <Chip>{t(`mstate_${m.state}`) === `mstate_${m.state}` ? m.state : t(`mstate_${m.state}`)}</Chip>}
      </div>
    </article>
  );
}

function TravelMailRow({ mail: m, onChanged }) {
  const { t, lang, notify, refreshDash } = useApp();
  const [busy, run] = useBusy();
  const after = async (message) => { if (message) notify(message); await refreshDash(); onChanged(); };
  const accept = () => run("accept", async () => { await api.call("mail_accept", { message_id: m.message_id }); await after(t("mail_trips_accepted")); });
  const ignore = () => run("ignore", async () => { await api.call("mail_ignore", { message_id: m.message_id }); await after(t("ignored")); });
  const again = () => run("again", async () => {
    const r = await api.call("travel_mail_read_again", { message_id: m.message_id });
    if (r.status === "no_model") notify(t("mail_trips_no_model"), "error");
    else await after(t("mail_trips_read_n", { n: (r.read || r.segments || []).length }));
  });
  const read = m.read || [];
  return (
    <article className="panel space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold" style={{ overflowWrap: "anywhere" }}>{m.subject || t("no_subject")}</span>
        <span className="help ml-auto">{shortClock(m.ts, lang)}</span>
      </div>
      <div className="help" style={{ overflowWrap: "anywhere" }}>{m.from_address}{m.score !== undefined && m.score !== null ? ` · ${t("score")} ${m.score}` : ""}</div>
      <div className="flex flex-wrap items-center gap-1.5">
        {m.change && m.change !== "new" && <Chip className="chip-amber">{t(`mail_trips_change_${m.change}`)}</Chip>}
        {m.source === "model" && <Chip className="chip-amber">{t("seg_model")}</Chip>}
        {m.ref && <Chip className="mono">{m.ref}</Chip>}
      </div>
      {read.length === 0 ? <p className="help">{t("mail_trips_nothing")}</p> : (
        <ul className="m-0 list-none space-y-1.5 p-0">
          {read.map((d, i) => (
            <li key={i} className="space-y-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <span style={{ color: "var(--accent)" }}><KindIcon kind={d.kind} /></span>
                <span className="font-semibold">{[d.number, [d.from_code || d.from_name, d.to_code || d.to_name].filter(Boolean).join(" → ")].filter(Boolean).join(" ")}</span>
                <span className="help">{localLabel(d.dep_local, lang)}</span>
                {d.source === "model" && <Chip className="chip-amber">{d.confidence} %</Chip>}
              </div>
              {(d.evidence || []).length > 0 && <ul className="help m-0 list-disc pl-5">{d.evidence.map((x, j) => <li key={j} className="mono">{x}</li>)}</ul>}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-0.5">
        <Busy className="btn btn-sm btn-primary" busy={busy.accept} disabled={read.length === 0} onClick={accept}>{t("mail_trips_accept")}</Busy>
        <Busy className="btn btn-sm" busy={busy.again} onClick={again}>{t("mail_trips_read_again")}</Busy>
        <Busy className="btn btn-sm" busy={busy.ignore} onClick={ignore}>{t("ignore")}</Busy>
        {(m.segments || []).length > 0 && <Chip className="chip-ok">{segCount(t, m.segments.length)}</Chip>}
      </div>
    </article>
  );
}

function MailTabs({ initialTab }) {
  const { t, dash } = useApp();
  const [tab, setTab] = useState(initialTab === "viajes" ? "viajes" : "maybe");
  const args = { maybe: { kind: "maybe", state: "new" }, shipping: { kind: "shipping", state: "all" }, noise: { kind: "noise", state: "all" } }[tab];
  const { data, error, loading, reload } = useLoad(() => (tab === "viajes" ? api.call("travel_mail_list", { state: "new", limit: 100 }) : api.call("mail_list", { ...args, limit: 100 })), [tab]);
  const counts = dash?.counts || {};
  const tabs = [
    { key: "maybe", label: t("tab_maybe"), count: counts.mails_review },
    { key: "shipping", label: t("tab_shipping") },
    { key: "noise", label: t("tab_noise") },
    { key: "viajes", label: t("mail_tab_trips"), count: dash?.travel?.needs_review?.mails || null },
  ];
  const mails = data?.mails || [];
  return (
    <section className="space-y-3" aria-label={t("mails_title")}>
      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      <p className="help">{tab === "viajes" ? t("mail_trips_help") : t(`tab_${tab}_hint`)}</p>
      <ErrorBox error={error} />
      {loading && !data ? <p className="help">…</p> : mails.length === 0 ? <Empty>{tab === "viajes" ? t("mail_trips_empty") : t(`tab_${tab}_empty`)}</Empty> : (
        <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(420px, 100%), 1fr))" }}>
          {mails.map((m) => (tab === "viajes"
            ? <TravelMailRow key={m.message_id} mail={m} onChanged={reload} />
            : <MailRow key={m.message_id} mail={m} review={tab === "maybe"} onChanged={reload} />))}
        </div>
      )}
    </section>
  );
}

function PasteMail() {
  const { t, notify, refreshDash } = useApp();
  const [busy, run] = useBusy();
  const [f, setF] = useState({ subject: "", from_address: "", text: "" });
  const [result, setResult] = useState(null);
  const set = (k, v) => setF((o) => ({ ...o, [k]: v }));
  const submit = (e) => {
    e.preventDefault();
    if (!f.text.trim()) return;
    run("paste", async () => {
      const args = { text: f.text };
      if (f.subject.trim()) args.subject = f.subject.trim();
      if (f.from_address.trim()) args.from_address = f.from_address.trim();
      const r = await api.call("mail_paste", args);
      setResult(r);
      notify(r.created ? t("paste_created") : r.linked ? t("paste_linked") : t("paste_nothing"));
      await refreshDash();
    });
  };
  const facts = result?.facts;
  return (
    <Section id="sec-paste" title={t("paste_title")}>
      <form className="panel space-y-3" onSubmit={submit}>
        <p className="help">{t("paste_help")}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("subject")}><input className="field" value={f.subject} onChange={(e) => set("subject", e.target.value)} /></Field>
          <Field label={t("from")}><input className="field" value={f.from_address} onChange={(e) => set("from_address", e.target.value)} placeholder="pedidos@tienda.es" /></Field>
        </div>
        <Field label={t("mail_body")}><textarea className="field" rows={5} value={f.text} onChange={(e) => set("text", e.target.value)} required /></Field>
        <Busy type="submit" className="btn btn-primary btn-sm" busy={busy.paste} disabled={!f.text.trim()}>{t("paste_go")}</Busy>
        {result && (
          <div className="space-y-2 border-t pt-3" style={{ borderColor: "var(--line)" }} role="status">
            <div className="flex flex-wrap items-center gap-2">
              <Chip className={facts?.kind === "shipping" ? "chip-ok" : "chip-amber"}>{t(`kind_${facts?.kind || "noise"}`)}</Chip>
              <span className="help">{t("paste_counts", { c: result.created || 0, l: result.linked || 0 })}</span>
            </div>
            <Facts found={facts} />
            {(facts?.reasons || []).length > 0 && <p className="help">{t("reasons")}: {facts.reasons.join(" · ")}</p>}
            <div className="flex flex-wrap gap-2">
              {(result.shipments || []).map((s) => <a key={s.id} className="btn btn-sm" href={`#/envio/${encodeURIComponent(s.id)}`}>{s.label || s.tracking_number}</a>)}
            </div>
          </div>
        )}
      </form>
    </Section>
  );
}

function DetectNumbers() {
  const { t, notify, refreshDash } = useApp();
  const [busy, run] = useBusy();
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [added, setAdded] = useState({});
  const submit = (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    run("detect", async () => { setResult(await api.call("detect_numbers", { text })); setAdded({}); });
  };
  const add = (n) => run(`add-${n.number}`, async () => {
    await api.call("shipment_add", { tracking_number: n.number, carrier: n.carrier || undefined, check_now: true });
    setAdded((a) => ({ ...a, [n.number]: true }));
    notify(t("added_ok"));
    await refreshDash();
  });
  const numbers = result?.numbers || [];
  return (
    <Section id="sec-detect" title={t("detect_title")}>
      <form className="panel space-y-3" onSubmit={submit}>
        <p className="help">{t("detect_help")}</p>
        <textarea className="field" rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label={t("detect_title")} placeholder="1Z999AA10123456784" />
        <Busy type="submit" className="btn btn-sm" busy={busy.detect} disabled={!text.trim()}>{t("detect_go")}</Busy>
        {result && (numbers.length === 0 ? <p className="help" role="status">{t("detect_none")}</p> : (
          <div className="overflow-x-auto" role="status">
            <table>
              <thead><tr><th>{t("tracking_number")}</th><th>{t("carrier")}</th><th className="r">{t("confidence")}</th><th /></tr></thead>
              <tbody>
                {numbers.map((n) => (
                  <tr key={n.number}>
                    <td className="mono">{n.number} <CopyButton text={n.number} /></td>
                    <td>{n.carrier_name || n.carrier || "—"}</td>
                    <td className="r num">{n.confidence} %</td>
                    <td className="r">
                      <div className="flex justify-end gap-1.5">
                        <ExtLink href={n.url}>{t("open_tracking")}</ExtLink>
                        <Busy className="btn btn-sm" busy={busy[`add-${n.number}`]} disabled={added[n.number]} onClick={() => add(n)}>{added[n.number] ? t("added") : t("add_follow")}</Busy>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </form>
    </Section>
  );
}

export default function Correo({ query }) {
  const { t } = useApp();
  const [tick, setTick] = useState(0);
  return (
    <div className="space-y-6">
      <header>
        <h1>{t("nav_mail")}</h1>
        <p className="help">{t("mail_intro")}</p>
      </header>
      <StatusCard key={`s${tick}`} />
      <ScanForm onDone={() => setTick((n) => n + 1)} />
      <MailTabs key={`m${tick}`} initialTab={query?.get("tab")} />
      <div className="grid gap-6 xl:grid-cols-2">
        <PasteMail />
        <DetectNumbers />
      </div>
    </div>
  );
}
