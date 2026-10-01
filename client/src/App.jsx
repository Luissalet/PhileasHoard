import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, errorText } from "./api.js";
import { initialLang, makeT, saveLang } from "./i18n.js";
import { AppContext } from "./context.js";
import { ConfirmDialog, Icon, ICONS } from "./components/ui.jsx";
import Envios from "./pages/Envios.jsx";
import Detalle from "./pages/Detalle.jsx";
import Correo from "./pages/Correo.jsx";
import Historial from "./pages/Historial.jsx";
import Ajustes from "./pages/Ajustes.jsx";

export { useApp } from "./context.js";

const PAGES = [
  { path: "", key: "nav_shipments", icon: ICONS.box, component: Envios, badge: "news" },
  { path: "correo", key: "nav_mail", icon: ICONS.mail, component: Correo, badge: "review" },
  { path: "historial", key: "nav_history", icon: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2", component: Historial },
  { path: "ajustes", key: "nav_settings", icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12l2-1-1-3-2 .3-1.4-1.4.3-2-3-1-1 2h-2l-1-2-3 1 .3 2L6.8 7.3 5 7 4 10l2 1v2l-2 1 1 3 2-.3 1.4 1.4-.3 2 3 1 1-2h2l1 2 3-1-.3-2 1.4-1.4 2 .3 1-3-2-1z", component: Ajustes },
];
// Not in the nav: reached from the lists.
const HIDDEN = [{ path: "envio", component: Detalle, parent: "" }];

function useHashRoute() {
  const read = () => {
    const [path, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    return { page: parts[0] || "", param: parts[1] || null, query: new URLSearchParams(query) };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => { setRoute(read()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function Toast({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(onClose, toast.kind === "error" ? 9000 : 4500);
    return () => clearTimeout(timer);
  }, [toast, onClose]);
  if (!toast) return null;
  return (
    <div className={`toast ${toast.kind === "error" ? "toast-error" : "toast-ok"}`} role={toast.kind === "error" ? "alert" : "status"} onClick={onClose}>
      {toast.message}
    </div>
  );
}

function SchedulerLight({ scheduler, t }) {
  if (!scheduler) return null;
  const lanes = Object.values(scheduler.lanes || {});
  const busy = lanes.some((l) => l.current);
  const queue = lanes.reduce((n, l) => n + (l.queue || 0), 0);
  const state = !scheduler.enabled || !scheduler.running ? "off" : scheduler.paused ? "paused" : busy ? "busy" : "idle";
  const color = { off: "var(--muted)", paused: "var(--warn)", busy: "var(--accent)", idle: "var(--ok)" }[state];
  return (
    <div className="space-y-0.5" aria-live="polite">
      <div className="flex items-center gap-2 font-semibold text-[12px]" style={{ color: "var(--ink)" }}>
        <span className="dot" style={{ background: color }} />
        {t(`sched_${state}`)}
      </div>
      <div className="help">{t("sched_queue", { n: queue })} · {t("sched_done", { n: scheduler.jobs_done ?? 0 })}</div>
    </div>
  );
}

export default function App() {
  const route = useHashRoute();
  const [lang, setLang] = useState(initialLang);
  const t = useMemo(() => makeT(lang), [lang]);
  const [health, setHealth] = useState(null);
  const [dash, setDash] = useState(null);
  const [dashError, setDashError] = useState(null);
  const [toast, setToast] = useState(null);
  const [confirmReq, setConfirmReq] = useState(null);
  const [carriers, setCarriers] = useState(null);
  const confirmResolve = useRef(null);
  const carriersLoading = useRef(false);

  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  useEffect(() => {
    const n = dash?.counts?.unseen_notifications || 0;
    document.title = n ? `(${n}) Phileas's Hoard` : "Phileas's Hoard";
  }, [dash]);

  const refreshDash = useCallback(async () => {
    try {
      setDash(await api.dashboard());
      setDashError(null);
    } catch (e) {
      setDashError(e);
    }
  }, []);

  // Refresh every 60 s while the tab is visible, and when it becomes visible again.
  useEffect(() => {
    refreshDash();
    api.health().then(setHealth).catch(() => {});
    const timer = setInterval(() => { if (!document.hidden) refreshDash(); }, 60000);
    const onVisible = () => { if (!document.hidden) refreshDash(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [refreshDash]);

  const notify = useCallback((message, kind = "ok") => setToast({ message, kind, id: Math.random() }), []);
  const toastError = useCallback((error) => setToast({ message: errorText(error), kind: "error", id: Math.random() }), []);
  const confirm = useCallback((request) => new Promise((resolve) => {
    confirmResolve.current = resolve;
    setConfirmReq(request);
  }), []);
  const closeConfirm = useCallback((answer) => {
    setConfirmReq(null);
    if (confirmResolve.current) confirmResolve.current(answer);
    confirmResolve.current = null;
  }, []);
  const loadCarriers = useCallback(async () => {
    if (carriers || carriersLoading.current) return;
    carriersLoading.current = true;
    try {
      const r = await api.call("carriers_list");
      setCarriers(r.carriers || []);
    } catch (e) {
      toastError(e);
    } finally {
      carriersLoading.current = false;
    }
  }, [carriers, toastError]);

  const changeLang = useCallback((next) => {
    saveLang(next);
    setLang(next);
    api.call("settings_set", { values: { "ui.language": next } }).catch(() => {});
  }, []);

  const value = useMemo(() => ({
    t, lang, setLang: changeLang, health, dash, dashError, refreshDash, notify, toastError, confirm, carriers, loadCarriers, route,
  }), [t, lang, changeLang, health, dash, dashError, refreshDash, notify, toastError, confirm, carriers, loadCarriers, route]);

  const hidden = HIDDEN.find((p) => p.path === route.page);
  const page = hidden || PAGES.find((p) => p.path === route.page) || PAGES[0];
  const activePath = hidden ? hidden.parent : page.path;
  const Component = page.component;
  const badges = { news: dash?.counts?.unseen_notifications || 0, review: dash?.counts?.mails_review || 0 };

  return (
    <AppContext.Provider value={value}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 skip-link focus:p-2">{t("skip")}</a>
      <div className="min-h-dvh md:grid md:grid-cols-[210px_minmax(0,1fr)]">
        <aside className="sticky top-0 z-10 border-b md:flex md:h-dvh md:flex-col md:self-start md:border-b-0 md:border-r" style={{ background: "var(--sidebar)", borderColor: "var(--line)" }}>
          <div className="flex items-center gap-3 px-4 py-3 md:py-4">
            <img src="/icon-192.png" alt="" width="30" height="30" className="rounded-lg" />
            <div className="text-[14px] font-semibold leading-tight">Phileas's Hoard</div>
          </div>
          <nav aria-label={t("sections")} className="flex gap-1 overflow-x-auto px-3 pb-2 md:flex-col">
            {PAGES.map((p) => {
              const n = p.badge ? badges[p.badge] : 0;
              return (
                <a key={p.path} href={`#/${p.path}`} className="nav-link shrink-0 text-[13px]" aria-current={p.path === activePath ? "page" : undefined}>
                  <Icon d={p.icon} />
                  {t(p.key)}
                  {n > 0 && <span className="nav-badge" aria-label={t("unseen_n", { n })}>{n > 99 ? "99+" : n}</span>}
                </a>
              );
            })}
          </nav>
          <div className="hidden flex-1 md:block" />
          <div className="hidden space-y-3 border-t px-4 py-3 md:block" style={{ borderColor: "var(--line)" }}>
            <SchedulerLight scheduler={dash?.scheduler} t={t} />
            {health?.offline && <span className="chip chip-amber">{t("offline_on")}</span>}
            <button type="button" className="btn btn-sm" onClick={() => changeLang(lang === "es" ? "en" : "es")}>{t("language")}</button>
          </div>
        </aside>
        <main id="main" className="min-w-0 px-4 py-4 md:px-7 md:py-6">
          {dashError && !dash && (
            <div className="banner banner-danger mb-4" role="alert">
              {t("unreachable")}: {dashError.message}. <button type="button" className="btn-link" onClick={refreshDash}>{t("retry")}</button>
            </div>
          )}
          {dashError && dash && (
            <div className="banner banner-warn mb-4" role="status">
              {t("stale")}: {dashError.message}. <button type="button" className="btn-link" onClick={refreshDash}>{t("retry")}</button>
            </div>
          )}
          <Component key={`${route.page}/${route.param || ""}`} param={route.param} query={route.query} />
          <div className="mt-8 flex flex-wrap items-center gap-3 border-t pt-3 md:hidden" style={{ borderColor: "var(--line)" }}>
            <SchedulerLight scheduler={dash?.scheduler} t={t} />
            <button type="button" className="btn btn-sm" onClick={() => changeLang(lang === "es" ? "en" : "es")}>{t("language")}</button>
          </div>
        </main>
      </div>
      <Toast toast={toast} onClose={() => setToast(null)} />
      <ConfirmDialog request={confirmReq} onClose={closeConfirm} />
    </AppContext.Provider>
  );
}
