import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { AddNumberModal, CompactRow, ShipmentCard, attentionReason } from "../components/cards.jsx";
import { useMailScan } from "../components/hooks.js";
import { Busy, Chip, Empty, ErrorBox, Icon, ICONS, Rel, Section, StatusPill } from "../components/ui.jsx";
import { clock, dayLabel } from "../format.js";

function NewsList({ items, onClear }) {
  const { t, lang } = useApp();
  const tone = { high: "chip-danger", medium: "chip-amber", low: "" };
  return (
    <Section id="sec-news" title={t("sec_news")} count={items.length} actions={<button type="button" className="btn btn-sm" onClick={onClear}>{t("mark_seen")}</button>}>
      <div className="panel p-0">
        <ul className="m-0 list-none p-0">
          {items.map((n) => (
            <li key={n.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b px-3 py-2 last:border-b-0" style={{ borderColor: "var(--line)" }}>
              <Chip className={tone[n.severity] || ""}>{t(`sev_${n.severity}`)}</Chip>
              <div className="min-w-[200px] flex-1">
                {n.shipment_id
                  ? <a href={`#/envio/${encodeURIComponent(n.shipment_id)}`} className="font-semibold" style={{ color: "var(--ink)", textDecoration: "none" }}>{n.title}</a>
                  : <span className="font-semibold">{n.title}</span>}
                {n.body && <div className="help">{n.body}</div>}
              </div>
              <span className="help" title={clock(n.ts, lang)}><Rel ts={n.ts} /></span>
            </li>
          ))}
        </ul>
      </div>
    </Section>
  );
}

function SourcesLine({ dash }) {
  const { t, lang } = useApp();
  const s = dash.sources || {};
  const yn = (v) => (v ? t("yes") : t("no"));
  const browser = s.browser || {};
  return (
    <footer className="help space-y-1 border-t pt-3" style={{ borderColor: "var(--line)" }}>
      <div>
        {t("foot_mail")}: {dash.mail?.last_scan_ts ? <Rel ts={dash.mail.last_scan_ts} /> : t("never")}
        {dash.mail?.enabled === false && ` · ${t("foot_mail_off")}`}
        {dash.mail?.last_error ? <span style={{ color: "var(--hoard-danger)" }}> · {dash.mail.last_error}</span> : null}
      </div>
      <div>
        {t("foot_sources")}: 17TRACK {yn(s.track17)} · {t("foot_ups_api")} {yn(s.ups_api)} · {t("foot_dhl_api")} {yn(s.dhl_api)} · Correos {yn(s.correos)} · {t("foot_browser")} {browser.available ? t("available") : `${t("unavailable")}${browser.reason ? ` (${browser.reason})` : ""}`}
      </div>
    </footer>
  );
}

export default function Envios() {
  const { t, lang, dash, dashError, refreshDash } = useApp();
  const [adding, setAdding] = useState(false);
  const [scanning, scan] = useMailScan();
  const [newsShown, setNewsShown] = useState([]);
  const visited = useRef(false);

  // Keep the news visible while this page is open, even after they are marked as seen on the server.
  useEffect(() => {
    if (!dash?.news?.length) return;
    setNewsShown((old) => {
      const seen = new Set(old.map((n) => n.id));
      const add = dash.news.filter((n) => !seen.has(n.id));
      return add.length ? [...add, ...old] : old;
    });
  }, [dash]);
  useEffect(() => {
    if (!dash || visited.current) return undefined;
    visited.current = true;
    const timer = setTimeout(() => { api.visit().then(() => {}).catch(() => {}); }, 4000);
    return () => clearTimeout(timer);
  }, [dash]);

  if (!dash) return <div className="space-y-3"><h1>{t("nav_shipments")}</h1>{dashError ? <ErrorBox error={dashError} /> : <p className="help">…</p>}</div>;

  const active = dash.active || [];
  const today = dash.today_list || [];
  const attention = dash.attention || [];
  const delivered = dash.delivered || [];
  const review = dash.counts?.mails_review || 0;
  const empty = !active.length && !delivered.length;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <div className="min-w-[240px] flex-1">
          <h1>{t("nav_shipments")}</h1>
          <p className="help">{t("home_intro")} {dash.today ? `· ${dayLabel(dash.today, lang, { year: false })}` : ""}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Busy className="btn" busy={scanning} onClick={() => scan()}><Icon d={ICONS.mail} size={15} />{t("read_mail_now")}</Busy>
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}><Icon d={ICONS.plus} size={15} />{t("add_number")}</button>
        </div>
      </header>

      {review > 0 && (
        <div className="banner banner-info" role="status">
          {t("review_banner", { n: review })} <a href="#/correo" className="font-semibold">{t("review_go")}</a>
        </div>
      )}

      {newsShown.length > 0 && <NewsList items={newsShown} onClear={() => setNewsShown([])} />}

      {empty && (
        <Empty>
          <div className="mx-auto max-w-[520px] space-y-2 py-4 text-left">
            <h2 style={{ color: "var(--ink)" }}>{t("empty_title")}</h2>
            <p>{t("empty_body")}</p>
            <div className="flex flex-wrap gap-2 pt-2">
              <Busy className="btn" busy={scanning} onClick={() => scan()}>{t("read_mail_now")}</Busy>
              <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>{t("add_number")}</button>
              <a className="btn" href="#/ajustes">{t("nav_settings")}</a>
            </div>
          </div>
        </Empty>
      )}

      {today.length > 0 && (
        <Section id="sec-today" title={t("sec_today")} count={today.length}>
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">{today.map((s) => <CompactRow key={s.id} shipment={s} />)}</div>
        </Section>
      )}

      {attention.length > 0 && (
        <Section id="sec-attention" title={t("sec_attention")} count={attention.length}>
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">{attention.map((s) => <CompactRow key={s.id} shipment={s} reason={attentionReason(s, t)} />)}</div>
        </Section>
      )}

      {active.length > 0 && (
        <Section id="sec-active" title={t("sec_active")} count={active.length}>
          <div className="card-grid">{active.map((s) => <ShipmentCard key={s.id} shipment={s} onChanged={refreshDash} />)}</div>
        </Section>
      )}

      {delivered.length > 0 && (
        <details className="panel">
          <summary className="flex flex-wrap items-center gap-2 font-semibold">
            {t("sec_delivered")} <span className="chip">{delivered.length}</span>
          </summary>
          <div className="mt-2 overflow-x-auto">
            <table>
              <tbody>
                {delivered.map((s) => (
                  <tr key={s.id}>
                    <td><a href={`#/envio/${encodeURIComponent(s.id)}`}>{s.label || s.item || s.tracking_number}</a><div className="help">{[s.merchant, s.carrier_name].filter(Boolean).join(" · ")}</div></td>
                    <td className="r">{s.delivered_ts ? dayLabel(new Date(s.delivered_ts * 1000), lang) : ""}</td>
                    <td className="r"><StatusPill status={s.status} label={s.status_label} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      <SourcesLine dash={dash} />
      {adding && <AddNumberModal onClose={() => setAdding(false)} />}
    </div>
  );
}
