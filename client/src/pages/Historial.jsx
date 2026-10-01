import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { Empty, ErrorBox, Section, StatusPill, useLoad } from "../components/ui.jsx";
import { dayLabel, num } from "../format.js";

function BarRows({ rows, max }) {
  const { t, lang } = useApp();
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.key} className="bar-row" title={t("stat_title", { n: r.n, min: r.min, med: r.median, max: r.max })}>
          <span className="trunc">{r.name}</span>
          <div className="bar-track" aria-hidden="true">
            <span className="bar-range" style={{ left: `${(r.min / max) * 100}%`, width: `${Math.max(((r.max - r.min) / max) * 100, 1.5)}%` }} />
            <span className="bar-median" style={{ left: `calc(${(r.median / max) * 100}% - 1px)` }} />
          </div>
          <span className="help num whitespace-nowrap">{r.min}–{r.max} {t("d")} · {t("median")} {num(r.median, 0, lang)} · n={r.n}</span>
        </div>
      ))}
    </div>
  );
}

function Stats() {
  const { t, lang } = useApp();
  const { data, error } = useLoad(() => api.stats(), []);
  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return null;
  const toRows = (obj, nameOf) => Object.entries(obj || {}).map(([key, v]) => ({ key, name: nameOf(key, v), ...v })).sort((a, b) => b.n - a.n);
  const carriers = toRows(data.by_carrier, (k, v) => v.name || k);
  const merchants = toRows(data.by_merchant, (k) => k);
  const accuracy = Object.entries(data.promise_accuracy || {}).map(([key, v]) => ({ key, name: key.replace(/^(merchant|carrier):/, ""), kind: key.split(":")[0], ...v }));
  const max = Math.max(1, ...carriers.map((r) => r.max), ...merchants.map((r) => r.max));
  const empty = !carriers.length && !merchants.length && !accuracy.length;
  return (
    <Section id="sec-stats" title={t("stats_title")}>
      {empty ? <Empty>{t("stats_empty")}</Empty> : (
        <div className="grid gap-4 xl:grid-cols-2">
          {carriers.length > 0 && <div className="panel space-y-2"><h3>{t("by_carrier")}</h3><BarRows rows={carriers} max={max} /></div>}
          {merchants.length > 0 && <div className="panel space-y-2"><h3>{t("by_merchant")}</h3><BarRows rows={merchants} max={max} /></div>}
          {accuracy.length > 0 && (
            <div className="panel space-y-2 xl:col-span-2">
              <h3>{t("promise_title")}</h3>
              <p className="help">{t("promise_help")}</p>
              <div className="overflow-x-auto">
                <table>
                  <thead><tr><th>{t("who")}</th><th className="r">n</th><th className="r">{t("avg_late")}</th><th className="r">{t("on_time")}</th></tr></thead>
                  <tbody>
                    {accuracy.map((a) => (
                      <tr key={a.key}>
                        <td>{a.name} <span className="help">· {t(a.kind === "carrier" ? "carrier" : "merchant")}</span></td>
                        <td className="r num">{a.n}</td>
                        <td className="r num" style={{ color: a.avg_days_late > 0.5 ? "var(--hoard-warning)" : "var(--hoard-success)" }}>
                          {a.avg_days_late > 0.05 ? t("days_late", { n: num(a.avg_days_late, 1, lang) }) : a.avg_days_late < -0.05 ? t("days_early", { n: num(-a.avg_days_late, 1, lang) }) : t("on_time")}
                        </td>
                        <td className="r num">{a.on_time_or_early} / {a.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

export default function Historial() {
  const { t, lang } = useApp();
  const [filter, setFilter] = useState("delivered");
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const id = setTimeout(() => setQ(text.trim()), 300); return () => clearTimeout(id); }, [text]);
  const { data, error, loading } = useLoad(() => api.call("shipments_list", { filter, text: q || undefined, limit: 200 }), [filter, q]);
  const rows = data?.shipments || [];
  const open = (id) => { window.location.hash = `#/envio/${encodeURIComponent(id)}`; };
  const filters = ["delivered", "all", "archived", "history"];
  return (
    <div className="space-y-6">
      <header>
        <h1>{t("nav_history")}</h1>
        <p className="help">{t("history_intro")}</p>
      </header>
      <section className="space-y-3" aria-label={t("nav_history")}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="label">{t("filter")}</span>
            <select className="field" style={{ width: "auto" }} value={filter} onChange={(e) => setFilter(e.target.value)}>
              {filters.map((f) => <option key={f} value={f}>{t(`filter_${f}`)}</option>)}
            </select>
          </label>
          <label className="block min-w-[200px] flex-1">
            <span className="label">{t("search")}</span>
            <input className="field" type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder={t("search_ph")} />
          </label>
        </div>
        <p className="help">{t(`filter_${filter}_hint`)}</p>
        <ErrorBox error={error} />
        {loading && !data ? <p className="help">…</p> : rows.length === 0 ? <Empty>{t("history_empty")}</Empty> : (
          <div className="panel overflow-x-auto p-0">
            <table className="grid" style={{ minWidth: 640 }}>
              <thead><tr><th>{t("parcel")}</th><th>{t("merchant")}</th><th>{t("carrier")}</th><th>{t("status")}</th><th className="r">{t("date")}</th></tr></thead>
              <tbody>
                {rows.map((s) => {
                  const d = s.delivered_ts ? dayLabel(new Date(s.delivered_ts * 1000), lang, { year: true }) : s.eta_from ? `${t("eta_short")} ${dayLabel(s.eta_from, lang)}` : "—";
                  return (
                    <tr key={s.id} className="row-link" tabIndex={0} onClick={() => open(s.id)} onKeyDown={(e) => { if (e.key === "Enter") open(s.id); }}>
                      <td style={{ minWidth: 180 }}><a href={`#/envio/${encodeURIComponent(s.id)}`} onClick={(e) => e.stopPropagation()} style={{ color: "var(--ink)" }}>{s.label || s.item || s.tracking_number}</a>{s.tracking_number ? <div className="help mono">{s.tracking_number}</div> : null}</td>
                      <td>{s.merchant || "—"}</td>
                      <td>{s.carrier_name || s.carrier || "—"}</td>
                      <td><StatusPill status={s.status} label={s.status_label} /></td>
                      <td className="r">{d}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Stats />
    </div>
  );
}
