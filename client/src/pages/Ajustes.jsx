import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { Busy, Chip, ErrorBox, Field, Rel, Section, Switch, useBusy, useLoad } from "../components/ui.jsx";
import { duration } from "../format.js";
import { CHANNELS, REGIONS, SEVERITIES } from "../meta.js";

const CHANNEL_SECRETS = {
  telegram: [
    { name: "TELEGRAM_TOKEN", label: "telegram_token", secret: true },
    { name: "TELEGRAM_CHAT_ID", label: "telegram_chat_id" },
  ],
  ntfy: [
    { name: "NTFY_TOPIC", label: "ntfy_topic", secret: true },
    { name: "NTFY_TOKEN", label: "ntfy_token", secret: true },
  ],
  email: [
    { name: "SMTP_HOST", label: "smtp_host", placeholder: "smtp.ejemplo.com" },
    { name: "SMTP_PORT", label: "smtp_port", placeholder: "587" },
    { name: "SMTP_USER", label: "smtp_user", secret: true },
    { name: "SMTP_PASSWORD", label: "smtp_password", secret: true },
    { name: "SMTP_FROM", label: "smtp_from" },
    { name: "SMTP_TO", label: "smtp_to" },
  ],
};
const CARRIER_SECRETS = [
  { name: "TRACK17_KEY", label: "track17_key", secret: true },
  { name: "UPS_CLIENT_ID", label: "ups_client_id", secret: true },
  { name: "UPS_CLIENT_SECRET", label: "ups_client_secret", secret: true },
  { name: "DHL_API_KEY", label: "dhl_api_key", secret: true },
];

// A group of settings with one Save button. fields: [{ key, type: text|number|switch|select, label, hint, options:[[value,label]] }]
function SettingsForm({ fields, settings, onSaved, children }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const original = (f) => settings[f.key] ?? "";
  const [draft, setDraft] = useState(() => Object.fromEntries(fields.map((f) => [f.key, original(f)])));
  useEffect(() => setDraft(Object.fromEntries(fields.map((f) => [f.key, original(f)]))), [settings]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = fields.filter((f) => String(draft[f.key]) !== String(original(f)));
  const set = (key, value) => setDraft((d) => ({ ...d, [key]: value }));
  const save = (e) => {
    e.preventDefault();
    if (!dirty.length) return;
    run("save", async () => {
      await api.call("settings_set", { values: Object.fromEntries(dirty.map((f) => [f.key, String(draft[f.key])])) });
      notify(t("saved"));
      await onSaved();
    });
  };
  return (
    <form className="space-y-3" onSubmit={save} noValidate>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((f) => (
          <div key={f.key} className={f.wide ? "sm:col-span-2" : ""}>
            {f.type === "switch" ? (
              <div className="flex items-start gap-3">
                <Switch checked={draft[f.key] === "1"} onChange={(v) => set(f.key, v ? "1" : "0")} label={f.label} />
                <div><div className="font-semibold">{f.label}</div>{f.hint && <div className="help">{f.hint}</div>}</div>
              </div>
            ) : (
              <Field label={f.label} hint={f.hint}>
                {f.type === "select" ? (
                  <select className="field" value={draft[f.key]} onChange={(e) => set(f.key, e.target.value)}>
                    {f.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                ) : (
                  <input className="field" type={f.type === "number" ? "number" : "text"} min={f.type === "number" ? 0 : undefined} value={draft[f.key]} onChange={(e) => set(f.key, e.target.value)} placeholder={f.placeholder || ""} />
                )}
              </Field>
            )}
          </div>
        ))}
      </div>
      {children}
      <Busy type="submit" className="btn btn-primary btn-sm" busy={busy.save} disabled={!dirty.length}>{t("save")}</Busy>
    </form>
  );
}

// Write-only credentials: the backend only says whether each is set, where from and a masked value.
function SecretsForm({ fields, secrets, onSaved, extra }) {
  const { t, notify, confirm } = useApp();
  const [busy, run] = useBusy();
  const [draft, setDraft] = useState({});
  const dirty = fields.filter((f) => (draft[f.name] || "") !== "");
  const set = (name, value) => setDraft((d) => ({ ...d, [name]: value }));
  const save = (e) => {
    e.preventDefault();
    if (!dirty.length) return;
    run("save", async () => {
      for (const f of dirty) await api.call("secret_set", { name: f.name, value: draft[f.name].trim() });
      notify(t("secrets_saved"));
      setDraft({});
      await onSaved();
    });
  };
  const remove = async (f) => {
    const ok = await confirm({ title: t("remove_secret"), message: t("remove_secret_msg", { name: t(f.label) }), confirmLabel: t("remove") });
    if (!ok) return;
    run(`rm-${f.name}`, async () => {
      await api.call("secret_set", { name: f.name, value: "" });
      notify(t("secret_removed"));
      await onSaved();
    });
  };
  return (
    <form className="space-y-3" onSubmit={save} noValidate autoComplete="off">
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((f) => {
          const s = secrets[f.name] || {};
          return (
            <div key={f.name} className="space-y-1">
              <Field label={t(f.label)}>
                <input className="field" type={f.secret ? "password" : "text"} autoComplete="new-password" value={draft[f.name] || ""} onChange={(e) => set(f.name, e.target.value)}
                  placeholder={s.configured ? `${t("configured")}${s.value ? ` ${s.value}` : ""}` : f.placeholder || ""} />
              </Field>
              <div className="flex flex-wrap items-center gap-1.5">
                <Chip className={s.configured ? "chip-ok" : "chip-amber"}>{s.configured ? t("configured") : t("not_configured")}</Chip>
                {s.configured && s.source && <Chip title={t("secret_source")}>{s.source}</Chip>}
                {s.configured && s.source === "settings" && <button type="button" className="btn-link text-[11.5px]" onClick={() => remove(f)}>{t("remove")}</button>}
              </div>
            </div>
          );
        })}
      </div>
      {extra}
      <Busy type="submit" className="btn btn-primary btn-sm" busy={busy.save} disabled={!dirty.length}>{t("save")}</Busy>
    </form>
  );
}

function ChannelCard({ channel, info, secrets, settings, onChanged }) {
  const { t, notify, toastError } = useApp();
  const [busy, run] = useBusy();
  const [result, setResult] = useState(null);
  const setSetting = (key, value) => run(key, async () => {
    await api.call("settings_set", { values: { [key]: value } });
    notify(t("saved"));
    await onChanged();
  });
  const enabled = settings[`notify.${channel}.enabled`] === "1";
  const severity = settings[`notify.${channel}.min_severity`] || "low";
  const test = () => run("test", async () => setResult(await api.call("notify_test", { channel })));
  const findChat = () => run("chat", async () => {
    const r = await api.call("telegram_find_chat_id");
    if (r.ok) { notify(t("chat_found", { id: r.chat_id })); await onChanged(); } else toastError(new Error(r.error || t("chat_not_found")));
  });
  const fields = CHANNEL_SECRETS[channel];
  return (
    <article className="panel space-y-3" aria-label={t(`ch_${channel}`)}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 style={{ fontSize: 14 }}>{t(`ch_${channel}`)}</h3>
        <Chip className={info?.configured ? "chip-ok" : "chip-amber"}>{info?.configured ? t("configured") : t("not_configured")}</Chip>
        <label className="ml-auto inline-flex items-center gap-2">
          <span className="help">{enabled ? t("enabled") : t("disabled")}</span>
          <Switch checked={enabled} disabled={busy[`notify.${channel}.enabled`]} onChange={(v) => setSetting(`notify.${channel}.enabled`, v ? "1" : "0")} label={`${t("enabled")}: ${t(`ch_${channel}`)}`} />
        </label>
      </div>
      <p className="help">{t(`ch_${channel}_hint`)}</p>
      {info?.detail && !info.configured && <p className="help" style={{ overflowWrap: "anywhere" }}>{info.detail}</p>}
      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="label">{t("min_severity")}</span>
          <select className="field" style={{ width: "auto" }} value={severity} onChange={(e) => setSetting(`notify.${channel}.min_severity`, e.target.value)}>
            {SEVERITIES.map((s) => <option key={s} value={s}>{t(`sev_${s}`)}</option>)}
          </select>
        </label>
        <Busy className="btn btn-sm" busy={busy.test} onClick={test}>{t("test")}</Busy>
        {channel === "telegram" && <Busy className="btn btn-sm" busy={busy.chat} onClick={findChat}>{t("find_chat")}</Busy>}
        {result && <span className={`chip ${result.ok ? "chip-ok" : "chip-danger"}`} role="status" style={{ whiteSpace: "normal" }}>{result.ok ? t("test_ok") : `${t("test_failed")}: ${result.error || ""}`}</span>}
      </div>
      {channel === "telegram" && <p className="help">{t("telegram_help")}</p>}
      {channel === "ntfy" && (
        <SettingsForm fields={[{ key: "notify.ntfy.server", type: "text", label: t("ntfy_server"), placeholder: "https://ntfy.sh" }]} settings={settings} onSaved={onChanged} />
      )}
      {channel === "email" && (
        <Field label={t("email_backend")} hint={t("email_backend_hint")}>
          <select className="field" style={{ maxWidth: 320 }} value={settings["notify.email.backend"] || "auto"} onChange={(e) => setSetting("notify.email.backend", e.target.value)}>
            {["auto", "faustus", "smtp"].map((b) => <option key={b} value={b}>{t(`backend_${b}`)}</option>)}
          </select>
        </Field>
      )}
      {fields && (
        <details open={!info?.configured}>
          <summary className="font-semibold">{t("credentials")}</summary>
          <div className="mt-2"><SecretsForm fields={fields} secrets={secrets} onSaved={onChanged} /></div>
        </details>
      )}
    </article>
  );
}

function CarriersTable() {
  const { t, carriers, loadCarriers } = useApp();
  useEffect(() => { loadCarriers(); }, [loadCarriers]);
  if (!carriers) return null;
  return (
    <details>
      <summary className="font-semibold">{t("carriers_table")} <span className="chip">{carriers.length}</span></summary>
      <div className="mt-2 overflow-x-auto">
        <table>
          <thead><tr><th>{t("carrier")}</th><th>{t("sources")}</th></tr></thead>
          <tbody>
            {carriers.map((c) => (
              <tr key={c.id}>
                <td>{c.name} <span className="help mono">{c.id}</span></td>
                <td>{c.sources?.length ? c.sources.map((s) => <Chip key={s} className="chip-ok">{s}</Chip>) : <span className="help">{t("carrier_no_source")}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function CheckinTable() {
  const { t, lang } = useApp();
  const { data } = useLoad(() => api.call("checkin_status"), []);
  const rows = data?.table || [];
  if (!rows.length) return null;
  return (
    <details>
      <summary className="font-semibold">{t("tset_checkin_table")} <span className="chip">{rows.length}</span></summary>
      <div className="mt-2 overflow-x-auto">
        <table>
          <thead><tr><th>{t("carrier")}</th><th>{t("ci_rule")}</th><th>{t("ci_source")}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code}>
                <td>{r.airline} <span className="help mono">{r.code}</span></td>
                <td>{lang === "en" ? r.note_en : r.note_es}</td>
                <td className="help">{r.source} · {r.checked}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Runs() {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const { data, error, reload } = useLoad(() => api.call("runs_list", { limit: 30 }), []);
  const runs = data?.runs || [];
  const housekeeping = () => run("hk", async () => { await api.call("housekeeping_run"); notify(t("housekeeping_done")); await reload(); });
  return (
    <Section id="sec-runs" title={t("runs_title")} actions={<><button type="button" className="btn btn-sm" onClick={reload}>{t("reload")}</button><Busy className="btn btn-sm" busy={busy.hk} onClick={housekeeping} title={t("housekeeping_hint")}>{t("housekeeping")}</Busy></>}>
      <ErrorBox error={error} />
      {runs.length === 0 ? <div className="panel help text-center">{t("runs_empty")}</div> : (
        <div className="panel overflow-x-auto p-0">
          <table className="grid">
            <thead><tr><th>{t("time")}</th><th>{t("kind")}</th><th>{t("result")}</th><th className="r">{t("duration")}</th><th>{t("detail")}</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="whitespace-nowrap"><Rel ts={r.ts} /></td>
                  <td>{t(`run_${r.kind}`) === `run_${r.kind}` ? r.kind : t(`run_${r.kind}`)}{r.ref ? <span className="help mono"> {r.ref}</span> : null}</td>
                  <td><Chip className={r.ok ? "chip-ok" : "chip-danger"}>{r.ok ? t("ok") : t("failed")}</Chip></td>
                  <td className="r num">{duration(r.duration_ms)}</td>
                  <td style={{ overflowWrap: "anywhere", minWidth: 180 }}>{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

export default function Ajustes() {
  const { t, lang, setLang, refreshDash } = useApp();
  const status = useLoad(() => api.call("phileas_status"), []);
  const notifyStatus = useLoad(() => api.call("notify_status"), []);
  const data = status.data;
  const reload = async () => { await Promise.all([status.reload(), notifyStatus.reload()]); refreshDash(); };
  if (!data) return <div className="space-y-3"><h1>{t("nav_settings")}</h1>{status.error ? <ErrorBox error={status.error} /> : <p className="help">…</p>}</div>;
  const settings = data.settings || {};
  const secrets = data.secrets || {};
  const channels = notifyStatus.data?.channels || data.channels || {};
  const regionOptions = REGIONS.map((r) => [r, t(`region_${r || "none"}`)]);

  return (
    <div className="space-y-6">
      <header>
        <h1>{t("nav_settings")}</h1>
        <p className="help">{t("settings_intro")}</p>
      </header>

      <Section id="sec-mail" title={t("set_mail")}>
        <div className="panel space-y-3">
          <p className="help">{t("set_mail_help")}</p>
          <SettingsForm settings={settings} onSaved={reload} fields={[
            { key: "mail.enabled", type: "switch", label: t("mail_enabled"), hint: t("mail_enabled_hint"), wide: true },
            { key: "mail.faustus_dir", type: "text", label: t("faustus_folder"), hint: t("faustus_folder_hint"), wide: true },
            { key: "mail.faustus_owner", type: "text", label: t("faustus_owner"), hint: t("faustus_owner_hint") },
            { key: "mail.interval_min", type: "number", label: t("mail_interval"), hint: t("minutes") },
            { key: "mail.window_days", type: "number", label: t("mail_window"), hint: t("mail_window_hint") },
            { key: "mail.first_days", type: "number", label: t("mail_first"), hint: t("mail_first_hint") },
          ]} />
        </div>
      </Section>

      <Section id="sec-travel" title={t("set_travel")}>
        <div className="panel space-y-3">
          <p className="help">{t("set_travel_help")}</p>
          <SettingsForm settings={settings} onSaved={reload} fields={[
            { key: "travel.enabled", type: "switch", label: t("tset_enabled"), hint: t("tset_enabled_hint"), wide: true },
            { key: "travel.home_city", type: "text", label: t("tset_home_city"), hint: t("tset_home_city_hint"), placeholder: "Madrid" },
            { key: "travel.home_airports", type: "text", label: t("tset_home_airports"), hint: t("tset_home_airports_hint"), placeholder: "MAD" },
            { key: "travel.home_tz", type: "text", label: t("tset_home_tz"), hint: t("tset_home_tz_hint"), placeholder: "Europe/Madrid" },
            { key: "travel.gap_days", type: "number", label: t("tset_gap_days"), hint: t("tset_gap_days_hint") },
            { key: "travel.kinds", type: "text", label: t("tset_kinds"), hint: t("tset_kinds_hint"), wide: true },
            { key: "travel.departure_hours", type: "number", label: t("tset_departure_hours") },
            { key: "travel.tomorrow_hour", type: "number", label: t("tset_tomorrow_hour"), hint: t("tset_tomorrow_hour_hint") },
            { key: "travel.my_name", type: "text", label: t("tset_my_name"), hint: t("tset_my_name_hint") },
            { key: "travel.ledger_account", type: "text", label: t("tset_ledger_account"), hint: t("tset_ledger_account_hint") },
            { key: "travel.model_fallback", type: "switch", label: t("tset_model_fallback"), hint: t("tset_model_fallback_hint"), wide: true },
            { key: "travel.docs_check", type: "switch", label: t("tset_docs_check"), hint: t("tset_docs_check_hint"), wide: true },
            { key: "travel.docs_days", type: "number", label: t("tset_docs_days") },
          ]} />
          <CheckinTable />
        </div>
      </Section>

      <Section id="sec-carriers" title={t("set_carriers")}>
        <div className="panel space-y-4">
          <p className="help">{t("carriers_help")}</p>
          <p className="help">{t("track17_help")} <a href="https://api.17track.net" target="_blank" rel="noopener noreferrer">api.17track.net</a></p>
          <SecretsForm fields={CARRIER_SECRETS} secrets={secrets} onSaved={reload} />
          <hr style={{ borderColor: "var(--line)" }} />
          <SettingsForm settings={settings} onSaved={reload} fields={[
            { key: "carriers.web_pages", type: "switch", label: t("web_pages"), hint: t("web_pages_hint"), wide: true },
          ]} />
          <CarriersTable />
        </div>
      </Section>

      <Section id="sec-eta" title={t("set_eta")}>
        <div className="panel space-y-3">
          <p className="help">{t("set_eta_help")}</p>
          <SettingsForm settings={settings} onSaved={reload} fields={[
            { key: "eta.region", type: "select", label: t("region"), hint: t("region_hint"), options: regionOptions },
            { key: "eta.extra_holidays", type: "text", label: t("extra_holidays"), hint: t("extra_holidays_hint"), placeholder: "2026-12-24, 2026-12-31" },
            { key: "archive.after_days", type: "number", label: t("archive_after"), hint: t("archive_after_hint") },
            { key: "checks.night_from", type: "number", label: t("night_from"), hint: t("night_hint") },
            { key: "checks.night_to", type: "number", label: t("night_to"), hint: t("night_hint") },
          ]} />
        </div>
      </Section>

      <Section id="sec-notify" title={t("set_notify")}>
        <p className="help">{t("set_notify_help")}</p>
        <ErrorBox error={notifyStatus.error} />
        <div className="grid gap-3 xl:grid-cols-2">
          {CHANNELS.map((c) => <ChannelCard key={c} channel={c} info={channels[c]} secrets={secrets} settings={settings} onChanged={reload} />)}
        </div>
      </Section>

      <Section id="sec-general" title={t("set_general")}>
        <div className="panel space-y-4">
          <div className="space-y-1">
            <span className="label">{t("language_label")}</span>
            <div className="flex flex-wrap gap-2" role="group" aria-label={t("language_label")}>
              <button type="button" className={`btn btn-sm ${lang === "es" ? "btn-primary" : ""}`} aria-pressed={lang === "es"} onClick={() => setLang("es")}>Español</button>
              <button type="button" className={`btn btn-sm ${lang === "en" ? "btn-primary" : ""}`} aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
            </div>
          </div>
          <SettingsForm settings={settings} onSaved={reload} fields={[
            { key: "scheduler.paused", type: "switch", label: t("scheduler_paused"), hint: t("scheduler_paused_hint"), wide: true },
          ]} />
        </div>
      </Section>

      <Runs />
    </div>
  );
}
