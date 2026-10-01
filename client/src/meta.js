// Vocabulary shared with the backend. Labels live in i18n.js.
export const STATUSES = ["ordered", "label_created", "not_found", "in_transit", "customs", "out_for_delivery", "available_for_pickup", "failed_attempt", "exception", "delivered", "returned", "unknown"];

// colour + chip class + 24x24 stroke icon path per status
export const STATUS_META = {
  ordered: { color: "#9aa9a5", cls: "", icon: "M6 3h12l2 4v14H4V7zM4 7h16M9 11h6" },
  label_created: { color: "#9aa9a5", cls: "", icon: "M4 6h16v12H4zM8 10h8M8 14h5" },
  not_found: { color: "#9aa9a5", cls: "", icon: "M11 4a7 7 0 100 14 7 7 0 000-14zM21 21l-5-5" },
  in_transit: { color: "#5fa8d3", cls: "chip-info", icon: "M2 7h11v9H2zM13 10h5l3 3v3h-8zM6 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM17 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3z" },
  customs: { color: "#d4a843", cls: "chip-amber", icon: "M4 21V4M4 4h13l-2 4 2 4H4" },
  out_for_delivery: { color: "#3fb8a8", cls: "chip-accent", icon: "M3 11l9-7 9 7v9H3zM9 20v-6h6v6" },
  available_for_pickup: { color: "#e0a43a", cls: "chip-amber", icon: "M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4M12 11v10" },
  failed_attempt: { color: "#e5604b", cls: "chip-danger", icon: "M12 3l10 18H2zM12 10v5M12 18h.01" },
  exception: { color: "#e5604b", cls: "chip-danger", icon: "M12 3l10 18H2zM12 10v5M12 18h.01" },
  delivered: { color: "#4a9e6d", cls: "chip-ok", icon: "M5 12l5 5 9-10" },
  returned: { color: "#b56a5c", cls: "chip-danger", icon: "M9 14L4 9l5-5M4 9h11a5 5 0 010 10h-3" },
  unknown: { color: "#9aa9a5", cls: "", icon: "M12 12h.01M12 8a2 2 0 011 3.7" },
};

export const FINAL = new Set(["delivered", "returned"]);
export const PROBLEM = new Set(["failed_attempt", "exception", "returned"]);

export const CHANNELS = ["toast", "hub", "ntfy", "telegram", "email"];
export const SEVERITIES = ["low", "medium", "high"];
export const REGIONS = ["", "ES-MD", "ES-CT", "ES-AN", "ES-VC", "ES-GA", "ES-PV"];
export const BASIS_ICON = { status: "M5 12l5 5 9-10", carrier: "M2 7h11v9H2zM13 10h5l3 3v3h-8z", shop: "M4 9l1-5h14l1 5M4 9v11h16V9M9 20v-6h6v6", history: "M12 7v5l3 2M21 12a9 9 0 11-3-6.7L21 8M21 3v5h-5", promise: "M5 5h14v15H5zM5 10h14M9 3v4M15 3v4", typical: "M4 19h16M6 19V9M11 19V5M16 19v-7", late: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2" };
