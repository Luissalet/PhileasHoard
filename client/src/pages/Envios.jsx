import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { AddNumberModal, ShipmentCard } from "../components/cards.jsx";
import { useMailScan } from "../components/hooks.js";
import { Busy, Chip, Empty, ErrorBox, Icon, ICONS, Rel, Section } from "../components/ui.jsx";
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
  const [view, setView] = useState("all");
  const [reconciling, setReconciling] = useState(false);
  const { notify, toastError } = useApp();
  const reconcile = async () => {
    setReconciling(true);
    try {
      await api.call("mail_scan", { since_days: 120, reprocess: true });
      await refreshDash();
      notify(t("reconciliation_done"));
    } catch (error) { toastError(error); }
    finally { setReconciling(false); }
  };
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
  const empty = !active.length;
  const hasHistory = !!(dash.counts?.delivered || dash.counts?.history || dash.counts?.archived);
  const visible = view === "today" ? today : view === "attention" ? attention : active;
  const activeIds = new Set(active.map((s) => s.id));

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

      {dash.travel?.enabled && (dash.travel.ongoing?.length > 0 || (dash.travel.next_trip && dash.travel.next_trip.days_to_go <= 7)) && (
        <div className="banner banner-info" role="status">
          {dash.travel.ongoing?.length > 0
            ? t("home_trip_now", { name: dash.travel.ongoing[0].title })
            : t("home_trip_soon", { name: dash.travel.next_trip.title, when: dash.travel.next_trip.days_to_go === 0 ? t("trip_days_to_go_0") : dash.travel.next_trip.days_to_go === 1 ? t("trip_days_to_go_1") : t("trip_days_to_go", { n: dash.travel.next_trip.days_to_go }) })}
          {" "}<a href={`#/viaje/${encodeURIComponent((dash.travel.ongoing?.[0] || dash.travel.next_trip).id)}`} className="font-semibold">{t("home_trip_go")}</a>
        </div>
      )}



      {empty && (
        <Empty>
          <div className="mx-auto max-w-[520px] space-y-2 py-4 text-left">
            <h2 style={{ color: "var(--ink)" }}>{t(hasHistory ? "no_active_title" : "empty_title")}</h2>
            <p>{t(hasHistory ? "no_active_body" : "empty_body")}</p>
            <div className="flex flex-wrap gap-2 pt-2">
              {hasHistory && <a className="btn" href="#/historial">{t("see_history")}</a>}
              <Busy className="btn" busy={scanning} onClick={() => scan()}>{t("read_mail_now")}</Busy>
              <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>{t("add_number")}</button>
              <a className="btn" href="#/ajustes">{t("nav_settings")}</a>
            </div>
          </div>
        </Empty>
      )}

      {active.length > 0 && (
        <Section id="sec-active" title={t("sec_active")} count={active.length} actions={<a href="#/historial" className="btn btn-sm">{t("see_history")}</a>}>
          <div className="flex flex-wrap gap-2 mb-3" role="group" aria-label={t("filter")}>
            {[["all", t("filter_all"), active.length], ["today", t("sec_today"), today.length], ["attention", t("sec_attention"), attention.length]].map(([key, label, count]) => (
              <button type="button" key={key} aria-pressed={view === key} className={`btn btn-sm ${view === key ? "btn-primary" : ""}`} onClick={() => setView(key)}>{label} · {count}</button>
            ))}
          </div>
          {visible.length ? <div className="card-grid">{visible.map((s) => <ShipmentCard key={s.id} shipment={s} />)}</div> : <Empty>{t("history_empty")}</Empty>}
        </Section>
      )}

      {newsShown.some((n) => !n.shipment_id || activeIds.has(n.shipment_id)) && <NewsList items={newsShown.filter((n) => !n.shipment_id || activeIds.has(n.shipment_id))} onClear={async () => { await api.visit(); setNewsShown([]); await refreshDash(); }} />}

      <div className="flex flex-wrap gap-3 items-center">
        <a href="#/historial" className="btn">{t("see_history")}{delivered.length ? ` · ${delivered.length} ${t("sec_delivered").toLowerCase()}` : ""}</a>
        <Busy className="btn" busy={reconciling} onClick={reconcile}>{t("reconcile_deliveries")}</Busy>
      </div>

      <SourcesLine dash={dash} />
      {adding && <AddNumberModal onClose={() => setAdding(false)} />}
    </div>
  );
}
