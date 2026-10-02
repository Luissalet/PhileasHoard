import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../context.js";
import { Busy, Chip, ErrorBox, Field, Icon, ICONS, Modal, Section, Tabs, useBusy, useLoad } from "../components/ui.jsx";
import {
  CATEGORIES, CheckinChip, segCount, KindIcon, PasteModal, SegmentCard, SegmentEditor, StatusChip, daysToGo, localLabel, tripWhen, tsIn, useTripChoices,
} from "../components/travel.jsx";
import { dayLabel, money, num } from "../format.js";

const ICS_ICON = "M5 5h14v15H5zM5 10h14M9 3v4M15 3v4M12 13v5M9.5 15.5L12 18l2.5-2.5";

// ------------------------------------------------------------------ check-in
function CheckinSection({ segments }) {
  const { t, lang } = useApp();
  const flights = segments.filter((s) => s.kind === "flight" && s.status !== "cancelled" && s.checkin?.applies);
  if (!flights.length) return null;
  return (
    <Section id="sec-checkin" title={t("sec_checkin")} count={flights.length}>
      <div className="panel p-0">
        <ul className="m-0 list-none p-0">
          {flights.map((s) => {
            const ci = s.checkin;
            const state = s.checkin_done ? "done" : ci.state;
            return (
              <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-b px-3 py-2 last:border-b-0" style={{ borderColor: "var(--line)" }}>
                <KindIcon kind="flight" />
                <span className="font-semibold">{s.label}</span>
                <span className="help">{localLabel(s.dep_local, lang, { weekday: false })}</span>
                <span className="help">{ci.opens_ts ? t("ci_opens", { when: tsIn(ci.opens_ts, s.dep_tz, lang) }) : ""}</span>
                <span className="ml-auto flex items-center gap-2"><CheckinChip state={state} /></span>
              </li>
            );
          })}
        </ul>
      </div>
      <details>
        <summary className="help">{t("ci_source")}</summary>
        <ul className="help m-0 mt-1 list-disc pl-5">
          {[...new Map(flights.map((s) => [s.checkin.airline || s.carrier, s.checkin])).values()].map((ci, i) => (
            <li key={i}>{ci.airline || "?"}: {ci.known ? `${lang === "en" ? ci.note_en : ci.note_es} (${ci.source}, ${ci.checked})` : t("ci_unknown_rule")}</li>
          ))}
        </ul>
      </details>
    </Section>
  );
}

// ------------------------------------------------------------------ documents (from Kafka)
function DocsSection({ tripId, auto }) {
  const { t, lang } = useApp();
  const [busy, run] = useBusy();
  const [data, setData] = useState(null);
  const check = () => run("docs", async () => setData(await api.call("trip_documents_check", { trip: tripId })));
  useEffect(() => { if (auto) check(); }, [tripId]); // eslint-disable-line react-hooks/exhaustive-deps
  const tone = { ok: "chip-ok", problem: "chip-danger", warning: "chip-amber", unknown: "" }[data?.status] || "";
  const reasonKey = data?.reason ? `docs_reason_${data.reason}` : "";
  const reason = reasonKey && t(reasonKey) !== reasonKey ? t(reasonKey) : data?.reason || "";
  return (
    <Section id="sec-docs" title={t("sec_documents")} actions={<Busy className="btn btn-sm" busy={busy.docs} onClick={check}>{t("docs_check")}</Busy>}>
      <div className="panel space-y-2">
        <p className="help">{t("docs_intro")}</p>
        {data && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Chip className={tone}>{t(`docs_status_${data.status}`)}</Chip>
              {data.return_date && <span className="help">{t("docs_return", { date: dayLabel(data.return_date, lang, { weekday: false, year: true }) })}</span>}
            </div>
            {reason && data.status !== "ok" && <p className="help">{reason}</p>}
            {data.documents?.length > 0 && (
              <ul className="m-0 list-none space-y-0.5 p-0">
                {data.documents.map((d, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2">
                    <span>{d.title}</span>
                    {d.expiry
                      ? <Chip className={d.valid_for_trip ? "chip-ok" : "chip-danger"}>{d.valid_for_trip ? t("docs_valid_until", { date: dayLabel(d.expiry, lang, { weekday: false, year: true }) }) : t("docs_expired", { date: dayLabel(d.expiry, lang, { weekday: false, year: true }) })}</Chip>
                      : <Chip>{t("docs_no_expiry")}</Chip>}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </Section>
  );
}

// ------------------------------------------------------------------ timeline
function Timeline({ days, today }) {
  const { t, lang } = useApp();
  if (!days.length) return null;
  return (
    <Section id="sec-timeline" title={t("sec_timeline")} count={days.length}>
      <div className="panel p-0">
        {days.map((d) => (
          <div key={d.date} className="grid gap-x-4 border-b px-3 py-2 last:border-b-0 sm:grid-cols-[110px_minmax(0,1fr)]" style={{ borderColor: "var(--line)", background: d.date === today ? "var(--accent-soft)" : undefined }}>
            <div className="font-semibold">{dayLabel(d.date, lang)}{d.date === today && <span className="chip chip-accent ml-2">{t("today")}</span>}</div>
            <ul className="m-0 list-none space-y-1 p-0">
              {d.items.map((it, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span style={{ color: "var(--accent)" }}><KindIcon kind={it.kind} /></span>
                  <span className="num" style={{ minWidth: 40 }}>{it.time || ""}</span>
                  <span className="help" style={{ minWidth: 70 }}>{t(`role_${it.role}`)}</span>
                  <span style={{ textDecoration: it.cancelled ? "line-through" : "none", overflowWrap: "anywhere" }}>{it.label}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ------------------------------------------------------------------ expenses
function PeopleBox({ tripId, people, suggested, onChanged }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const [name, setName] = useState("");
  const add = (names) => run("add", async () => { await api.call("trip_people", { trip: tripId, add: names }); setName(""); await onChanged(); });
  const remove = (p) => run(`rm-${p.id}`, async () => { await api.call("trip_people", { trip: tripId, remove: [p.id] }); await onChanged(); });
  const makeMe = (p) => run(`me-${p.id}`, async () => { await api.call("trip_people", { trip: tripId, me: p.id }); notify(t("saved")); await onChanged(); });
  return (
    <div className="panel space-y-2">
      <h3>{t("exp_people")}</h3>
      <p className="help">{t("exp_people_help")}</p>
      <div className="flex flex-wrap gap-2">
        {people.map((p) => (
          <span key={p.id} className="chip" style={{ padding: "2px 4px 2px 9px", gap: 6 }}>
            {p.name}{p.is_me && <span className="chip chip-accent">{t("exp_person_me")}</span>}
            {!p.is_me && <button type="button" className="btn-link text-[11px]" onClick={() => makeMe(p)}>{t("exp_person_make_me")}</button>}
            <button type="button" className="btn-link text-[11px]" style={{ color: "var(--muted)" }} aria-label={`${t("exp_person_remove")} ${p.name}`} onClick={() => remove(p)}>×</button>
          </span>
        ))}
      </div>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add([name.trim()]); }}>
        <Field label={t("exp_person_name")} className="w-[200px]"><input className="field" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Busy type="submit" className="btn btn-sm" busy={busy.add} disabled={!name.trim()}>{t("exp_person_add")}</Busy>
      </form>
      {suggested.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="help">{t("exp_suggested")}</span>
          {suggested.map((n) => <button key={n} type="button" className="btn btn-sm" onClick={() => add([n])}>+ {n}</button>)}
        </div>
      )}
    </div>
  );
}

function ExpenseModal({ trip, people, expense, onClose, onSaved }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const editing = !!expense;
  const today = new Date().toISOString().slice(0, 10);
  const me = people.find((p) => p.is_me) || people[0];
  const [d, setD] = useState(() => ({
    description: expense?.description || "",
    amount: expense ? String(expense.amount) : "",
    currency: expense?.currency || trip.currency,
    rate: expense && expense.currency !== trip.currency ? String(expense.rate) : "",
    payer: expense?.payer_id || me?.id || "",
    mode: expense?.split_mode || "equal",
    date: expense?.date || today,
    category: expense?.category || "other",
  }));
  const [who, setWho] = useState(() => new Set(expense?.split?.participants || people.map((p) => p.id)));
  const [shares, setShares] = useState(() => Object.fromEntries(people.map((p) => [p.id, String(expense?.split?.shares?.[p.id] ?? 1)])));
  const [amounts, setAmounts] = useState(() => Object.fromEntries(people.map((p) => [p.id, String(expense?.split?.amounts?.[p.id] ?? "")])));
  const set = (key, value) => setD((x) => ({ ...x, [key]: value }));
  const foreign = d.currency && d.currency.toUpperCase() !== trip.currency;
  const exactSum = people.reduce((n, p) => n + (Number(amounts[p.id]) || 0), 0);
  const submit = (e) => {
    e.preventDefault();
    run("save", async () => {
      let split = {};
      if (d.mode === "equal") split = who.size === people.length ? {} : { people: [...who] };
      if (d.mode === "shares") split = { shares: Object.fromEntries(people.filter((p) => Number(shares[p.id]) > 0).map((p) => [p.id, Number(shares[p.id])])) };
      if (d.mode === "exact") split = { amounts: Object.fromEntries(people.filter((p) => Number(amounts[p.id]) > 0).map((p) => [p.id, Number(amounts[p.id])])) };
      const body = { description: d.description, amount: Number(d.amount), payer: d.payer, currency: d.currency.toUpperCase(), rate: foreign ? Number(d.rate) : 1, split_mode: d.mode, split, category: d.category, date: d.date };
      if (editing) await api.call("trip_expense_update", { expense: expense.id, ...body });
      else await api.call("trip_expense_add", { trip: trip.id, ...body });
      notify(t("exp_saved"));
      await onSaved();
      onClose();
    });
  };
  const toggle = (id) => setWho((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <Modal title={editing ? t("exp_edit") : t("exp_add")} onClose={onClose} wide>
      <form className="space-y-3" onSubmit={submit} noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("exp_desc")} className="sm:col-span-2"><input className="field" value={d.description} onChange={(e) => set("description", e.target.value)} required /></Field>
          <Field label={t("exp_amount")}><input className="field" type="number" min="0" step="0.01" value={d.amount} onChange={(e) => set("amount", e.target.value)} required /></Field>
          <Field label={t("exp_currency")}><input className="field" maxLength={3} value={d.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} /></Field>
          {foreign && (
            <Field label={t("exp_rate", { cur: trip.currency })} hint={t("exp_rate_hint", { from: d.currency, cur: trip.currency })} className="sm:col-span-2">
              <input className="field" type="number" min="0" step="0.0001" value={d.rate} onChange={(e) => set("rate", e.target.value)} required />
            </Field>
          )}
          <Field label={t("exp_payer")}>
            <select className="field" value={d.payer} onChange={(e) => set("payer", e.target.value)}>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          </Field>
          <Field label={t("exp_category")}>
            <select className="field" value={d.category} onChange={(e) => set("category", e.target.value)}>{CATEGORIES.map((c) => <option key={c} value={c}>{t(`cat_${c}`)}</option>)}</select>
          </Field>
          <Field label={t("exp_date")}><input className="field" type="date" value={d.date} onChange={(e) => set("date", e.target.value)} /></Field>
          <Field label={t("exp_split")}>
            <select className="field" value={d.mode} onChange={(e) => set("mode", e.target.value)}>
              {["equal", "shares", "exact"].map((m) => <option key={m} value={m}>{t(`exp_split_${m}`)}</option>)}
            </select>
          </Field>
        </div>
        <fieldset className="space-y-1.5" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label">{t("exp_split_who")}</legend>
          {people.map((p) => (
            <div key={p.id} className="flex items-center gap-3">
              {d.mode === "equal" && <label className="inline-flex items-center gap-2"><input type="checkbox" checked={who.has(p.id)} onChange={() => toggle(p.id)} />{p.name}</label>}
              {d.mode === "shares" && (<><span style={{ minWidth: 110 }}>{p.name}</span><input className="field num" style={{ width: 90 }} type="number" min="0" step="0.5" aria-label={`${p.name} ${t("exp_split_weight")}`} value={shares[p.id]} onChange={(e) => setShares((s) => ({ ...s, [p.id]: e.target.value }))} /><span className="help">{t("exp_split_weight")}</span></>)}
              {d.mode === "exact" && (<><span style={{ minWidth: 110 }}>{p.name}</span><input className="field num" style={{ width: 110 }} type="number" min="0" step="0.01" aria-label={`${p.name} ${t("exp_amount")}`} value={amounts[p.id]} onChange={(e) => setAmounts((s) => ({ ...s, [p.id]: e.target.value }))} /><span className="help">{d.currency}</span></>)}
            </div>
          ))}
          {d.mode === "exact" && <div className="help num">{num(exactSum, 2)} / {num(Number(d.amount) || 0, 2)}</div>}
        </fieldset>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <Busy type="submit" className="btn btn-primary" busy={busy.save} disabled={!d.description.trim() || !(Number(d.amount) > 0) || (d.mode === "equal" && who.size === 0)}>{t("save")}</Busy>
        </div>
      </form>
    </Modal>
  );
}

function LedgerBox({ trip, view, onChanged }) {
  const { t, lang, notify } = useApp();
  const [busy, run] = useBusy();
  const [result, setResult] = useState(null);
  const [account, setAccount] = useState("");
  const call = (dry) => run(dry ? "dry" : "send", async () => {
    const r = await api.call("trip_to_ledger", { trip: trip.id, account, dry_run: dry });
    setResult(r);
    if (!dry && r.sent?.length) { notify(t("exp_ledger_ok", { n: r.sent.length })); await onChanged(); }
  });
  const status = result?.status;
  const sentCount = (view.expenses || []).filter((e) => e.sent_to_ledger).length;
  const reasonKey = result?.reason ? `led_reason_${result.reason}` : "";
  const reason = reasonKey && t(reasonKey) !== reasonKey ? t(reasonKey) : result?.reason;
  return (
    <div className="panel space-y-2">
      <h3>{t("exp_to_ledger")}</h3>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("exp_ledger_account")} className="w-[220px]"><input className="field" value={account} onChange={(e) => setAccount(e.target.value)} /></Field>
        <Busy className="btn btn-sm" busy={busy.dry} onClick={() => call(true)}>{t("exp_to_ledger_preview")}</Busy>
        <Busy className="btn btn-sm btn-primary" busy={busy.send} onClick={() => call(false)} disabled={!view.expenses?.length}>{t("exp_to_ledger")}</Busy>
        {sentCount > 0 && <Chip className="chip-ok">{t("exp_in_ledger")}: {sentCount}</Chip>}
      </div>
      {status === "nothing_to_send" && <p className="help">{t("exp_ledger_nothing")}</p>}
      {["no_hub", "ledger_unavailable", "currency_mismatch", "partial"].includes(status) && (
        <div className="banner banner-warn" role="status">
          {t(`exp_ledger_status_${status}`)} {reason && <span className="help block">{reason}</span>}
          {result.accounts?.length > 0 && <span className="help block">{t("exp_ledger_choose")} {result.accounts.join(", ")}</span>}
        </div>
      )}
      {status === "ok" && <div className="banner banner-info" role="status">{t("exp_ledger_ok", { n: result.sent.length })} · {result.account}{result.category ? ` · ${result.category}` : ""}</div>}
      {result?.pending?.length > 0 && (
        <ul className="help m-0 list-disc pl-5">
          {result.pending.map((p) => <li key={p.expense}>{p.description} — {money(p.my_share, trip.currency, lang)}</li>)}
        </ul>
      )}
    </div>
  );
}

function ExpensesTab({ trip }) {
  const { t, lang, confirm, notify } = useApp();
  const view = useLoad(async () => {
    const r = await api.call("trip_expenses", { trip: trip.id });
    if (!r.people?.length) { await api.call("trip_people", { trip: trip.id }); return api.call("trip_expenses", { trip: trip.id }); }
    return r;
  }, [trip.id]);
  const detail = useLoad(() => api.call("trip_get", { trip: trip.id }), [trip.id]);
  const [busy, run] = useBusy();
  const [editing, setEditing] = useState(null);
  const data = view.data;
  const reload = async () => { await Promise.all([view.reload(), detail.reload()]); };
  if (!data) return <p className="help">…</p>;
  const people = data.people || [];
  const summary = data.summary || { balances: [], transfers: [], total: 0 };
  const cur = trip.currency;
  const del = async (e) => {
    const ok = await confirm({ title: t("exp_delete"), message: t("exp_delete_msg", { name: e.description }), confirmLabel: t("delete") });
    if (!ok) return;
    run(`d-${e.id}`, async () => { await api.call("trip_expense_delete", { expense: e.id, confirm: true }); notify(t("exp_deleted")); await reload(); });
  };
  return (
    <div className="space-y-5">
      <ErrorBox error={view.error} />
      <PeopleBox tripId={trip.id} people={people} suggested={detail.data?.suggested_people || []} onChanged={reload} />

      <Section id="sec-expenses" title={t("exp_list")} count={data.expenses.length} actions={<button type="button" className="btn btn-sm btn-primary" onClick={() => setEditing({})} disabled={!people.length}><Icon d={ICONS.plus} size={14} />{t("exp_add")}</button>}>
        {data.expenses.length === 0 ? <div className="panel help text-center">{t("exp_empty")}</div> : (
          <div className="panel overflow-x-auto p-0">
            <table>
              <thead><tr><th>{t("exp_date")}</th><th>{t("exp_desc")}</th><th>{t("exp_payer")}</th><th className="r">{t("exp_amount")}</th><th className="r">{t("exp_my_share")}</th><th /></tr></thead>
              <tbody>
                {data.expenses.map((e) => (
                  <tr key={e.id}>
                    <td className="whitespace-nowrap">{dayLabel(e.date, lang, { weekday: false })}</td>
                    <td>{e.description}<div className="help">{t(`cat_${e.category}`)}{e.sent_to_ledger ? ` · ${t("exp_in_ledger")}` : ""}</div></td>
                    <td>{e.payer}</td>
                    <td className="r num">{money(e.amount, e.currency, lang)}{e.currency !== cur && <div className="help">{money(e.base_amount, cur, lang)}</div>}</td>
                    <td className="r num">{money(e.my_share, cur, lang)}</td>
                    <td className="r"><button type="button" className="btn btn-sm" onClick={() => setEditing(e)}>{t("seg_edit")}</button> <Busy className="btn btn-sm btn-danger" busy={busy[`d-${e.id}`]} onClick={() => del(e)}>{t("delete")}</Busy></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {data.expenses.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Section id="sec-balances" title={t("exp_balances")} actions={<span className="chip">{t("exp_total")}: {money(summary.total, cur, lang)}</span>}>
            <div className="panel overflow-x-auto p-0">
              <table>
                <thead><tr><th /><th className="r">{t("exp_paid")}</th><th className="r">{t("exp_owes")}</th><th className="r">{t("exp_net")}</th></tr></thead>
                <tbody>
                  {summary.balances.map((b) => (
                    <tr key={b.person_id}>
                      <td>{b.name}{b.is_me ? <span className="help"> · {t("exp_person_me")}</span> : ""}</td>
                      <td className="r num">{money(b.paid, cur, lang)}</td>
                      <td className="r num">{money(b.owed, cur, lang)}</td>
                      <td className="r num" style={{ color: b.net > 0 ? "var(--hoard-success)" : b.net < 0 ? "var(--hoard-danger)" : undefined, fontWeight: 600 }}>{b.net > 0 ? "+" : ""}{money(b.net, cur, lang)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <Section id="sec-settle" title={t("exp_transfers")}>
            <div className="panel space-y-1.5">
              {summary.transfers.length === 0 ? <p className="help">{t("exp_transfers_none")}</p> : (
                <ul className="m-0 list-none space-y-1 p-0">
                  {summary.transfers.map((x, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-2">
                      <Icon d="M5 12h14M13 6l6 6-6 6" size={15} />
                      <span>{t("exp_transfer_line", { from: x.from_name, to: x.to_name, amount: money(x.amount, cur, lang) })}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Section>
        </div>
      )}

      {data.expenses.length > 0 && <LedgerBox trip={trip} view={data} onChanged={reload} />}
      {editing && <ExpenseModal trip={trip} people={people} expense={editing.id ? editing : null} onClose={() => setEditing(null)} onSaved={reload} />}
    </div>
  );
}

// ------------------------------------------------------------------ the page
function RenameModal({ trip, onClose, onSaved }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const [title, setTitle] = useState(trip.title);
  const save = (value) => run("save", async () => { await api.call("trip_update", { trip: trip.id, title: value }); notify(t("trip_renamed")); await onSaved(); onClose(); });
  return (
    <Modal title={t("trip_rename")} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save(title); }}>
        <Field label={t("trip_title")}><input className="field" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <div className="flex flex-wrap justify-between gap-2">
          <Busy type="button" className="btn btn-sm" busy={busy.save} onClick={() => save("")}>{t("trip_auto_title")}</Busy>
          <div className="flex gap-2">
            <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
            <Busy type="submit" className="btn btn-primary" busy={busy.save} disabled={!title.trim()}>{t("save")}</Busy>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function MergeModal({ trip, others, onClose, onSaved }) {
  const { t, notify, confirm } = useApp();
  const [busy, run] = useBusy();
  const [other, setOther] = useState(others[0]?.id || "");
  const go = async (e) => {
    e.preventDefault();
    const target = others.find((x) => x.id === other);
    const ok = await confirm({ title: t("trip_merge"), message: t("trip_merge_msg", { name: target?.title || "" }), confirmLabel: t("trip_merge_go"), danger: false });
    if (!ok) return;
    run("merge", async () => { await api.call("trip_update", { trip: trip.id, merge_from: other, confirm: true }); notify(t("trip_merged")); await onSaved(); onClose(); });
  };
  return (
    <Modal title={t("trip_merge")} onClose={onClose}>
      <form className="space-y-3" onSubmit={go}>
        <Field label={t("trip_merge_pick")}>
          <select className="field" value={other} onChange={(e) => setOther(e.target.value)}>{others.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}</select>
        </Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <Busy type="submit" className="btn btn-primary" busy={busy.merge} disabled={!other}>{t("trip_merge_go")}</Busy>
        </div>
      </form>
    </Modal>
  );
}

function MoveModal({ trip, segment, others, onClose, onSaved }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const [target, setTarget] = useState("");
  const go = (e) => {
    e.preventDefault();
    run("move", async () => { await api.call("trip_update", { trip: trip.id, move_segment: segment.id, to_trip: target }); notify(t("seg_moved")); await onSaved(); onClose(); });
  };
  return (
    <Modal title={`${t("seg_move")}: ${segment.label}`} onClose={onClose}>
      <form className="space-y-3" onSubmit={go}>
        <Field label={t("seg_move_pick")}>
          <select className="field" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">{t("seg_move_auto")}</option>
            <option value="new">{t("seg_move_new")}</option>
            {others.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <Busy type="submit" className="btn btn-primary" busy={busy.move}>{t("seg_move")}</Busy>
        </div>
      </form>
    </Modal>
  );
}

export default function Viaje({ param, query }) {
  const { t, lang, refreshDash, confirm, notify } = useApp();
  const id = param || "";
  const { data, error, loading, reload } = useLoad(() => api.call("trip_get", { trip: id }), [id]);
  const others = useTripChoices(id);
  const [tab, setTab] = useState(query?.get("tab") === "gastos" ? "expenses" : "plan");
  const [busy, run] = useBusy();
  const [modal, setModal] = useState(null);
  const [picked, setPicked] = useState(new Set());
  const after = async () => { await reload(); refreshDash(); };

  if (!data) {
    return <div className="space-y-3"><a href="#/viajes" className="btn btn-sm"><Icon d={ICONS.back} size={14} />{t("trip_back")}</a>{error ? <ErrorBox error={error} /> : <p className="help">…</p>}</div>;
  }
  const trip = data.trip;
  const segments = data.segments;
  const today = new Date().toISOString().slice(0, 10);
  const doc = (name, args, message) => run(name, async () => { await api.call("trip_update", { trip: trip.id, ...args }); if (message) notify(message); await after(); });
  const delTrip = async () => {
    const ok = await confirm({ title: t("trip_delete"), message: t("trip_delete_msg") });
    if (!ok) return;
    run("del", async () => { await api.call("trip_update", { trip: trip.id, delete: true, confirm: true }); notify(t("trip_deleted")); refreshDash(); window.location.hash = "#/viajes"; });
  };
  const delSeg = async (s) => {
    const ok = await confirm({ title: t("seg_delete"), message: t("seg_delete_msg", { name: s.label }) });
    if (!ok) return;
    run(`ds-${s.id}`, async () => { await api.call("segment_delete", { segment: s.id, confirm: true }); notify(t("seg_deleted")); await after(); });
  };
  const select = (sid, on) => setPicked((p) => { const n = new Set(p); on ? n.add(sid) : n.delete(sid); return n; });
  const split = () => run("split", async () => {
    await api.call("trip_update", { trip: trip.id, split_segments: [...picked] });
    setPicked(new Set());
    notify(t("trip_split_done"));
    await after();
  });
  const canSplit = picked.size > 0 && picked.size < segments.length;
  const reviewCount = trip.needs_review;

  return (
    <div className="space-y-5">
      <header className="space-y-2">
        <a href="#/viajes" className="btn btn-sm"><Icon d={ICONS.back} size={14} />{t("trip_back")}</a>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 style={{ overflowWrap: "anywhere" }}>{trip.title}</h1>
          <StatusChip status={trip.status} />
          {trip.status === "upcoming" && trip.days_to_go !== null && <Chip className="chip-info">{daysToGo(trip, t)}</Chip>}
          {trip.muted && <Chip>{t("trip_muted")}</Chip>}
          {reviewCount > 0 && <Chip className="chip-amber">{t("trip_review_n", { n: reviewCount })}</Chip>}
        </div>
        <p className="help">{tripWhen(trip, lang)} · {segCount(t, trip.active_segments)} · {trip.currency}</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setModal({ kind: "add" })}><Icon d={ICONS.plus} size={14} />{t("seg_add")}</button>
          <button type="button" className="btn btn-sm" onClick={() => setModal({ kind: "paste" })}>{t("trip_paste")}</button>
          <a className="btn btn-sm" href={`/api/trips/${encodeURIComponent(trip.id)}/ics`} download><Icon d={ICS_ICON} size={14} />{t("trip_ics")}</a>
          <button type="button" className="btn btn-sm" onClick={() => setModal({ kind: "rename" })}><Icon d={ICONS.pencil} size={14} />{t("trip_rename")}</button>
          <Busy className="btn btn-sm" busy={busy.mute} onClick={() => doc("mute", { muted: !trip.muted })}>{trip.muted ? t("trip_unmute") : t("trip_mute")}</Busy>
          {others.length > 0 && <button type="button" className="btn btn-sm" onClick={() => setModal({ kind: "merge" })}>{t("trip_merge")}</button>}
          <Busy className="btn btn-sm" busy={busy.cancel} onClick={() => doc("cancel", { cancelled: !trip.cancelled })}>{trip.cancelled ? t("trip_uncancel") : t("trip_cancel")}</Busy>
          <button type="button" className="btn btn-sm btn-danger" onClick={delTrip}>{t("trip_delete")}</button>
        </div>
      </header>

      <ErrorBox error={error} />
      {data.unassigned_hint > 0 && <div className="banner banner-info">{t("trip_unassigned", { n: data.unassigned_hint })}</div>}

      <Tabs active={tab} onChange={setTab} tabs={[{ key: "plan", label: t("tab_plan") }, { key: "expenses", label: t("tab_expenses"), count: trip.expenses || null }]} />

      {tab === "plan" && (
        <div className="space-y-5">
          <CheckinSection segments={segments} />
          <DocsSection tripId={trip.id} auto={trip.status === "upcoming" || trip.status === "ongoing"} />
          <Timeline days={data.timeline} today={today} />

          <Section id="sec-segments" title={t("sec_segments")} count={segments.length}
            actions={canSplit ? <Busy className="btn btn-sm" busy={busy.split} onClick={split}>{t("trip_split_n", { n: picked.size })}</Busy> : null}>
            {segments.length === 0 ? <div className="panel help text-center">{t("trips_empty_body")}</div> : (
              <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                {segments.map((s) => (
                  <SegmentCard key={s.id} s={s} trip={trip} selectable={segments.length > 1} selected={picked.has(s.id)} onSelect={select}
                    onEdit={(x) => setModal({ kind: "edit", segment: x })} onMove={(x) => setModal({ kind: "move", segment: x })} onDelete={delSeg} onChanged={after} />
                ))}
              </div>
            )}
          </Section>

          {data.links.length > 0 && (
            <Section id="sec-links" title={t("sec_links")} count={data.links.length}>
              <div className="panel p-0">
                <ul className="m-0 list-none p-0">
                  {data.links.map((l) => (
                    <li key={l.url} className="flex flex-wrap items-baseline gap-x-3 border-b px-3 py-2 last:border-b-0" style={{ borderColor: "var(--line)" }}>
                      <a href={l.url} target="_blank" rel="noopener noreferrer" style={{ overflowWrap: "anywhere" }}>{l.kind === "checkin" ? t("ci_open_link") : l.label || l.kind}</a>
                      <span className="help">{l.segment}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Section>
          )}

          {data.mails.length > 0 && (
            <details className="panel">
              <summary className="font-semibold">{t("sec_trip_mails")} <span className="chip">{data.mails.length}</span></summary>
              <ul className="help m-0 mt-2 list-disc pl-5">
                {data.mails.map((m) => <li key={m.message_id}>{m.subject} <span className="mono">{m.from_address}</span></li>)}
              </ul>
            </details>
          )}

          <Section id="sec-notes" title={t("trip_notes")}>
            <NotesBox trip={trip} onSaved={after} />
          </Section>
        </div>
      )}

      {tab === "expenses" && <ExpensesTab trip={trip} />}

      {modal?.kind === "add" && <SegmentEditor trips={[trip, ...others]} tripId={trip.id} onClose={() => setModal(null)} onSaved={after} />}
      {modal?.kind === "edit" && <SegmentEditor segment={modal.segment} onClose={() => setModal(null)} onSaved={after} />}
      {modal?.kind === "paste" && <PasteModal trips={[trip, ...others]} tripId={trip.id} onClose={() => setModal(null)} onDone={after} />}
      {modal?.kind === "rename" && <RenameModal trip={trip} onClose={() => setModal(null)} onSaved={after} />}
      {modal?.kind === "merge" && <MergeModal trip={trip} others={others} onClose={() => setModal(null)} onSaved={after} />}
      {modal?.kind === "move" && <MoveModal trip={trip} segment={modal.segment} others={others} onClose={() => setModal(null)} onSaved={after} />}
    </div>
  );
}

function NotesBox({ trip, onSaved }) {
  const { t, notify } = useApp();
  const [busy, run] = useBusy();
  const [text, setText] = useState(trip.notes || "");
  const dirty = text !== (trip.notes || "");
  return (
    <form className="panel space-y-2" onSubmit={(e) => { e.preventDefault(); run("save", async () => { await api.call("trip_update", { trip: trip.id, notes: text }); notify(t("saved")); await onSaved(); }); }}>
      <textarea className="field" rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label={t("trip_notes")} />
      <Busy type="submit" className="btn btn-sm btn-primary" busy={busy.save} disabled={!dirty}>{t("save")}</Busy>
    </form>
  );
}
