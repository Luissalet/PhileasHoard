import React, { useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { Empty, ErrorBox, Icon, ICONS, Section, useLoad } from "../components/ui.jsx";
import { KindIcon, NewTripModal, segCount, PasteModal, StatusChip, TripCard, localLabel, tripWhen, useTripChoices } from "../components/travel.jsx";
import { dayLabel } from "../format.js";

const ICS_ICON = "M5 5h14v15H5zM5 10h14M9 3v4M15 3v4M12 13v5M9.5 15.5L12 18l2.5-2.5";

// "Hoy": what is planned today in each trip that is on now.
function TodayView({ items }) {
  const { t, lang } = useApp();
  return (
    <div className="space-y-3">
      {items.map((trip) => (
        <div key={trip.trip_id} className="panel space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <a href={`#/viaje/${encodeURIComponent(trip.trip_id)}`} className="font-semibold" style={{ fontSize: 14 }}>{trip.title}</a>
            <StatusChip status="ongoing" />
          </div>
          {trip.items.length === 0 ? <p className="help">{t("trips_today_none")}</p> : (
            <ul className="m-0 list-none space-y-1 p-0">
              {trip.items.map((it, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span style={{ color: "var(--accent)" }}><KindIcon kind={it.kind} /></span>
                  <span className="num" style={{ minWidth: 42 }}>{it.time || "—"}</span>
                  <span className="help" style={{ minWidth: 70 }}>{t(`role_${it.role}`)}</span>
                  <span style={{ textDecoration: it.cancelled ? "line-through" : "none", overflowWrap: "anywhere" }}>{it.label}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Viajes() {
  const { t, lang, dash, refreshDash } = useApp();
  const list = useLoad(() => api.call("trips_list", { filter: "all" }), []);
  const overview = useLoad(() => api.call("travel_overview"), []);
  const trips = useTripChoices("");
  const [adding, setAdding] = useState(false);
  const [pasting, setPasting] = useState(false);
  const reload = async () => { await Promise.all([list.reload(), overview.reload()]); refreshDash(); };
  const all = list.data?.trips || [];
  const ov = overview.data;
  const ongoing = all.filter((x) => x.status === "ongoing");
  const upcoming = all.filter((x) => x.status === "upcoming");
  const past = all.filter((x) => x.status === "past");
  const cancelled = all.filter((x) => x.status === "cancelled");
  const review = ov?.needs_review?.mails || 0;
  const checkins = ov?.checkins || [];
  const loading = (list.loading && !list.data) || (overview.loading && !overview.data);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <div className="min-w-[240px] flex-1">
          <h1>{t("nav_trips")}</h1>
          <p className="help">{t("trips_intro")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn" onClick={() => setPasting(true)}>{t("trip_paste")}</button>
          {upcoming.length + ongoing.length > 0 && <a className="btn" href="/api/trips/ics" download><Icon d={ICS_ICON} size={15} />{t("trip_ics_all")}</a>}
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}><Icon d={ICONS.plus} size={15} />{t("trip_new")}</button>
        </div>
      </header>

      <ErrorBox error={list.error || overview.error} />

      {ov && ov.enabled === false && (
        <div className="banner banner-warn" role="status">{t("trips_off")} <a href="#/ajustes" className="font-semibold">{t("trips_off_go")}</a></div>
      )}
      {review > 0 && (
        <div className="banner banner-info" role="status">{t("trips_review_banner", { n: review })} <a href="#/correo?tab=viajes" className="font-semibold">{t("trips_review_go")}</a></div>
      )}

      {!loading && all.length === 0 && (
        <Empty>
          <div className="mx-auto max-w-[520px] space-y-2 py-4 text-left">
            <h2 style={{ color: "var(--ink)" }}>{t("trips_empty_title")}</h2>
            <p>{t("trips_empty_body")}</p>
            <div className="flex flex-wrap gap-2 pt-2">
              <button type="button" className="btn" onClick={() => setPasting(true)}>{t("trip_paste")}</button>
              <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>{t("trip_new")}</button>
            </div>
          </div>
        </Empty>
      )}

      {ongoing.length > 0 && (
        <Section id="sec-ongoing" title={t("trips_now")} count={ongoing.length}>
          <TodayView items={(ov?.today_items || []).length ? ov.today_items : ongoing.map((x) => ({ trip_id: x.id, title: x.title, items: [] }))} />
          <div className="card-grid">{ongoing.map((x) => <TripCard key={x.id} trip={x} />)}</div>
        </Section>
      )}

      {checkins.length > 0 && (
        <Section id="sec-checkins" title={t("sec_checkin")} count={checkins.length}>
          <div className="panel p-0">
            <ul className="m-0 list-none p-0">
              {checkins.map((c) => (
                <li key={c.segment_id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-b px-3 py-2 last:border-b-0" style={{ borderColor: "var(--line)" }}>
                  <KindIcon kind="flight" />
                  <a href={`#/viaje/${encodeURIComponent(c.trip_id)}`} className="font-semibold" style={{ color: "var(--ink)", textDecoration: "none" }}>{c.label}</a>
                  <span className="help">{localLabel(c.dep_local, lang)}</span>
                  <span className="ml-auto"><span className={`chip ${c.state === "open" ? "chip-accent" : c.state === "unknown_open" ? "chip-amber" : "chip-info"}`}>{t(`ci_${c.state}`)}</span></span>
                </li>
              ))}
            </ul>
          </div>
        </Section>
      )}

      {upcoming.length > 0 && (
        <Section id="sec-upcoming" title={t("trips_upcoming")} count={upcoming.length}>
          <div className="card-grid">{upcoming.map((x) => <TripCard key={x.id} trip={x} />)}</div>
        </Section>
      )}

      {past.length > 0 && (
        <details className="panel">
          <summary className="flex flex-wrap items-center gap-2 font-semibold">{t("trips_past")} <span className="chip">{past.length}</span></summary>
          <div className="mt-2 overflow-x-auto">
            <table>
              <tbody>
                {past.map((x) => (
                  <tr key={x.id}>
                    <td><a href={`#/viaje/${encodeURIComponent(x.id)}`}>{x.title}</a><div className="help">{segCount(t, x.active_segments)}</div></td>
                    <td className="r">{tripWhen(x, lang)}</td>
                    <td className="r"><StatusChip status="past" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {cancelled.length > 0 && (
        <details className="panel">
          <summary className="flex flex-wrap items-center gap-2 font-semibold">{t("trips_cancelled")} <span className="chip">{cancelled.length}</span></summary>
          <div className="mt-2 card-grid">{cancelled.map((x) => <TripCard key={x.id} trip={x} />)}</div>
        </details>
      )}

      {adding && <NewTripModal onClose={() => setAdding(false)} />}
      {pasting && <PasteModal trips={trips} onClose={() => setPasting(false)} onDone={reload} />}
    </div>
  );
}
