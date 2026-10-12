import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { CONTEXT_REQUEST, changedFields, rebaseDraft } from "../copilot-context.js";
import { useApp } from "../context.js";
import { useBusy } from "./ui.jsx";

// Reads the mail now (or searches back) and reports "N correos nuevos, X envíos nuevos".
export function useMailScan(onDone) {
  const { t, notify, toastError, refreshDash } = useApp();
  const [busy, run] = useBusy();
  const scan = (args = {}) => run("scan", async () => {
    const r = await api.call("mail_scan", args);
    if (!r || r.ok === false) {
      toastError(new Error((r && r.error) || t("scan_failed")));
    } else {
      const parts = [t("scan_result", { n: r.messages ?? 0, s: r.created ?? 0 })];
      if (r.linked) parts.push(t("scan_linked", { n: r.linked }));
      if (r.maybe) parts.push(t("scan_maybe", { n: r.maybe }));
      notify(parts.join(" · "));
    }
    await refreshDash();
    onDone?.(r);
    return r;
  });
  return [busy.scan, scan];
}

// An open form tells the assistant panel what it holds (unsaved fields included). `snapshot()` may return nothing.
export function useContextProvider(snapshot, active = true) {
  const latest = useRef(snapshot);
  latest.current = snapshot;
  useEffect(() => {
    if (!active) return undefined;
    const answer = (event) => {
      const value = latest.current();
      if (value) event.detail.provide(value);
    };
    window.addEventListener(CONTEXT_REQUEST, answer);
    return () => window.removeEventListener(CONTEXT_REQUEST, answer);
  }, [active]);
}

// Form state that survives refreshes: untouched fields follow the stored object (an assistant edit shows up),
// edited ones stay as typed. `changed` is what differs from what was loaded, to send on save.
export function useRebasedDraft(server) {
  const [state, setState] = useState(() => ({ base: server, draft: server }));
  const key = JSON.stringify(server);
  useEffect(() => {
    setState((s) => {
      const next = rebaseDraft(s.base, s.draft, server);
      return next.base === s.base && next.draft === s.draft ? s : next;
    });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = useCallback((field, value) => setState((s) => ({ ...s, draft: { ...s.draft, [field]: value } })), []);
  return { draft: state.draft, base: state.base, set, changed: changedFields(state.base, state.draft) };
}
