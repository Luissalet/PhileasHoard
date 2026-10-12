// What the assistant panel needs from this app: the open object(s) with real ids, the unsaved form fields,
// and a refresh when the assistant finishes a turn. Pure helpers first (tested in node), browser glue last.

import { api } from "./api.js";

export const CONTEXT_REQUEST = "phileas:context-request";
export const REFRESH_EVENT = "phileas:refresh";
export const TURN_END_EVENT = "hoard:copilot-turn-end";

// Only what the user changed by hand, so an edit made by the assistant in the meantime is not overwritten.
export function changedFields(initial, draft) {
  return Object.fromEntries(Object.entries(draft).filter(([key, value]) =>
    JSON.stringify(value) !== JSON.stringify(initial[key])));
}

// A refresh brought `server` values while the user may be editing `draft` (loaded as `base`).
// Untouched fields follow the server; fields the user edited keep the user's value and their old base,
// unless the server now has exactly that value (the save went through), which settles them.
export function rebaseDraft(base, draft, server) {
  let nextBase = base;
  let nextDraft = draft;
  for (const key of Object.keys(server)) {
    const untouched = JSON.stringify(draft[key]) === JSON.stringify(base[key]);
    const settled = JSON.stringify(draft[key]) === JSON.stringify(server[key]);
    if (!untouched && !settled) continue;
    if (JSON.stringify(base[key]) !== JSON.stringify(server[key])) nextBase = { ...nextBase, [key]: server[key] };
    if (JSON.stringify(draft[key]) !== JSON.stringify(server[key])) nextDraft = { ...nextDraft, [key]: server[key] };
  }
  return { base: nextBase, draft: nextDraft };
}

export function parseRoute(hash) {
  const [path, query = ""] = String(hash || "").replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean).map((p) => {
    try { return decodeURIComponent(p); } catch { return p; }
  });
  return { page: parts[0] || "", param: parts[1] || null, query: new URLSearchParams(query) };
}

const NOT_AN_ID = new Set(["", "new", "nuevo", "nueva", "add"]);

function pick(source, keys) {
  const out = {};
  for (const key of keys) if (source && source[key] !== undefined && source[key] !== null && source[key] !== "") out[key] = source[key];
  return out;
}

export function shipmentObject(detail) {
  const s = detail && detail.shipment;
  if (!s || !s.id) return null;
  return {
    kind: "shipment",
    object_id: s.id,
    title: s.label || s.item || s.tracking_number || s.id,
    // The pickup code is private: it never goes into the context.
    ...pick(s, ["status", "status_label", "carrier", "tracking_number", "merchant", "item", "order_ref", "origin_country", "notes", "late", "archived", "muted", "mail_only"]),
  };
}

export function tripObject(detail) {
  const t = detail && detail.trip;
  if (!t || !t.id) return null;
  const segments = (detail.segments || []).slice(0, 40).map((s) => ({ object_id: s.id, kind: s.kind, title: s.label, status: s.status }));
  return {
    kind: "trip",
    object_id: t.id,
    title: t.title || t.id,
    ...pick(t, ["status", "start_date", "end_date", "currency", "muted", "cancelled", "notes"]),
    segments,
  };
}

// `call(name, args)` is the app's own tool endpoint. A missing or new object yields no object, never an exception.
export async function openObjects(route, call) {
  if (NOT_AN_ID.has(String(route.param || "").toLowerCase())) return [];
  try {
    if (route.page === "envio") {
      const obj = shipmentObject(await call("shipment_get", { shipment: route.param }));
      return obj ? [obj] : [];
    }
    if (route.page === "viaje") {
      const obj = tripObject(await call("trip_get", { trip: route.param }));
      return obj ? [obj] : [];
    }
  } catch {
    return [];
  }
  return [];
}

// Editors that answered the request: one snapshot as is, several as { forms: [...] }.
export function mergeSnapshots(snapshots) {
  const list = snapshots.filter(Boolean);
  if (!list.length) return undefined;
  return list.length === 1 ? list[0] : { forms: list };
}

export function editorContext(target = typeof window !== "undefined" ? window : null) {
  if (!target) return undefined;
  const snapshots = [];
  target.dispatchEvent(new CustomEvent(CONTEXT_REQUEST, { detail: { provide: (value) => { snapshots.push(value); } } }));
  return mergeSnapshots(snapshots);
}

let viewExtras = {};
// A page announces state that is not in the URL (the open tab). Cleared when the route changes.
export function publishView(extras, hash) {
  viewExtras = { ...extras, __hash: hash };
}

export async function buildContext({ hash, call, editor, extras = {} }) {
  const route = parseRoute(hash);
  const active_objects = await openObjects(route, call);
  // An editor on a stored object (a segment, an expense) names it too, so the assistant has its real id.
  const forms = editor ? (editor.forms || [editor]) : [];
  for (const form of forms) {
    if (form && form.kind && form.object_id && !active_objects.some((o) => o.kind === form.kind && o.object_id === form.object_id)) {
      active_objects.push({ kind: form.kind, object_id: form.object_id, title: form.title || form.object_id });
    }
  }
  const view = { page: route.page || "envios" };
  if (route.param && !NOT_AN_ID.has(route.param.toLowerCase())) view.object_id = route.param;
  Object.assign(view, extras);
  if (editor) view.editor = editor;
  return { active_objects, view };
}

// ------------------------------------------------------------------ browser glue
let lastRefresh = 0;
export function requestRefresh(now = Date.now, target = window) {
  const t = now();
  if (t - lastRefresh < 300) return false; // the event and onTurnEnd both arrive for one turn
  lastRefresh = t;
  target.dispatchEvent(new Event(REFRESH_EVENT));
  return true;
}

export function installCopilot(win = window, call) {
  const run = call || api.call;
  win.hoardCopilot = {
    async context() {
      const hash = win.location.hash;
      const { __hash, ...rest } = viewExtras;
      return buildContext({ hash, call: run, editor: editorContext(win), extras: __hash === hash ? rest : {} });
    },
    onTurnEnd() { requestRefresh(Date.now, win); },
  };
  win.addEventListener(TURN_END_EVENT, () => requestRefresh(Date.now, win));
}
