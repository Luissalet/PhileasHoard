"""Calls to the other Hoards through the hub proxy (Kafka for identity documents, Ledger for expenses).

``Call`` is ``hoard_link.family.call``; tests pass a fake. Nothing here raises: a hub or app that is down comes back as
``{"ok": False, "reason": ...}`` so the app can say why the feature is unavailable.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Callable, Optional

from .airlines import fold
from .airports import SCHENGEN

Call = Callable[..., dict[str, Any]]


def default_call() -> Call:
    from ..hoard_link import family
    return family.call


def unwrap(answer: Any) -> tuple[Optional[dict[str, Any]], str]:
    """The tool result of a proxy answer, or ``(None, reason)``. The reason is short and safe to show."""
    if not isinstance(answer, dict):
        return None, "unexpected answer"
    if not answer.get("ok"):
        status = answer.get("status")
        err = str(answer.get("error") or "")
        low = err.lower()
        if status is None or "not reachable" in low or "hub" in low and "refused" not in low:
            return None, "hub_down"
        if status in (404, 502, 503) or "not running" in low or "unreachable" in low or "connect" in low:
            return None, "app_down"
        if status == 401 or "token" in low:
            return None, "unauthorized"
        if "unknown tool" in low or status == 400 and "tool" in low:
            return None, "tool_missing"
        return None, (err[:160] or f"http {status}")
    result = answer.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return None, "unexpected answer"
    if isinstance(result, dict) and isinstance(result.get("content"), list):          # an MCP-shaped result
        for part in result["content"]:
            if isinstance(part, dict) and part.get("type") == "text":
                try:
                    return json.loads(part["text"]), ""
                except ValueError:
                    continue
    if isinstance(result, dict):
        if result.get("error") and len(result) <= 3:
            return None, str(result["error"])[:160]
        return result, ""
    return None, "unexpected answer"


# ------------------------------------------------------------------ Kafka: identity documents
DNI_RX = re.compile(r"\bdni\b|documento nacional|national id|identity card|\bnie\b|tarjeta de residencia|carnet de identidad|cedula", re.I)
PASSPORT_RX = re.compile(r"pasaporte|passport", re.I)


def doc_type(title: str) -> str:
    folded = fold(title or "")
    if PASSPORT_RX.search(folded):
        return "passport"
    if DNI_RX.search(folded):
        return "id_card"
    return "other"


def identity_documents(call: Call) -> dict[str, Any]:
    """Identity documents with their expiry dates, from Kafka. Never includes document numbers."""
    docs, why = unwrap(call("kafka", "docs_list", {"kind": "identity", "limit": 50}))
    if docs is None:
        return {"ok": False, "reason": why, "documents": []}
    deadlines, why2 = unwrap(call("kafka", "deadlines_list", {"filter": "open", "kind": "expiry", "limit": 200}))
    if deadlines is None:
        return {"ok": False, "reason": why2, "documents": []}
    by_doc: dict[str, str] = {}
    for d in deadlines.get("deadlines") or []:
        if d.get("doc_id") and d.get("date"):
            by_doc[d["doc_id"]] = min(by_doc.get(d["doc_id"], "9999-12-31"), str(d["date"])[:10])
    out = []
    for doc in docs.get("documents") or []:
        expiry = by_doc.get(doc.get("id"), "")
        out.append({"id": doc.get("id"), "title": str(doc.get("title") or "")[:80], "type": doc_type(str(doc.get("title") or "")), "expiry": expiry})
    return {"ok": True, "reason": "", "documents": out}


def check_trip_documents(call: Call, trip: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Will an identity document still be valid on the trip's return date? Kafka down → ``unknown`` (not an error)."""
    ids = identity_documents(call)
    end = str(trip.get("end_date") or "")[:10]
    countries = {s.get("to_country") or s.get("from_country") for s in segments if s.get("status") != "cancelled"} - {None, ""}
    outside_schengen = sorted(c for c in countries if c not in SCHENGEN)
    base = {"trip": trip.get("id"), "return_date": end, "outside_schengen": outside_schengen}
    if not ids["ok"]:
        return {**base, "status": "unknown", "reason": ids["reason"], "documents": [], "problems": []}
    docs = ids["documents"]
    if not docs:
        return {**base, "status": "unknown", "reason": "no_documents", "documents": [], "problems": []}
    try:
        back = date.fromisoformat(end)
    except ValueError:
        back = None
    for d in docs:
        d["valid_for_trip"] = bool(d["expiry"] and back and d["expiry"] >= back.isoformat())
        d["days_after_return"] = (date.fromisoformat(d["expiry"]) - back).days if d["expiry"] and back else None
    usable = [d for d in docs if d["type"] in ("id_card", "passport", "other")]
    needs_passport = bool(outside_schengen)
    candidates = [d for d in usable if d["type"] == "passport"] if needs_passport and any(d["type"] == "passport" for d in usable) else usable
    problems = []
    dated = [d for d in candidates if d["expiry"]]
    if not dated:
        status = "unknown"
        reason = "no_expiry_dates"
    elif any(d["valid_for_trip"] for d in dated):
        status, reason = "ok", ""
    else:
        status, reason = "problem", "expires_before_return"
        problems = [{"document": d["title"], "expiry": d["expiry"], "type": d["type"]} for d in dated]
    if needs_passport and not any(d["type"] == "passport" for d in usable):
        problems.append({"document": "", "expiry": "", "type": "missing_passport"})
        if status == "ok":
            status, reason = "warning", "no_passport_in_kafka"
    return {**base, "status": status, "reason": reason, "documents": docs, "problems": problems}


# ------------------------------------------------------------------ Ledger
VIAJE_RX = re.compile(r"viaj|travel|vacacion|trip|turismo|ocio", re.I)


def ledger_target(call: Call, account_name: str = "") -> dict[str, Any]:
    """The Ledger account and category an expense share goes to, or ``{"ok": False, "reason": ...}``."""
    accounts, why = unwrap(call("ledger", "list_accounts", {}))
    if accounts is None:
        return {"ok": False, "reason": why}
    live = [a for a in accounts.get("accounts") or [] if not a.get("archived")]
    if not live:
        return {"ok": False, "reason": "no_accounts"}
    if account_name:
        match = [a for a in live if fold(a.get("name") or "") == fold(account_name)] or [a for a in live if fold(account_name) in fold(a.get("name") or "")]
        if not match:
            return {"ok": False, "reason": "account_not_found", "accounts": [a.get("name") for a in live]}
        account = match[0]
    elif len(live) == 1:
        account = live[0]
    else:
        return {"ok": False, "reason": "choose_account", "accounts": [a.get("name") for a in live]}
    cats, _ = unwrap(call("ledger", "list_categories", {"kind": "expense"}))
    names = [c.get("name") for c in (cats or {}).get("categories") or [] if c.get("name")]
    exact = [n for n in names if fold(n) in ("viajes", "viaje", "travel")]
    close = [n for n in names if VIAJE_RX.search(n)]
    category = (exact or close or [""])[0]
    return {"ok": True, "account": account.get("name"), "currency": str(account.get("currency") or "EUR").upper(), "category": category or "Viajes",
            "create_category": not category}


def amount_text(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


def send_entry(call: Call, target: dict[str, Any], *, cents: int, day: str, counterparty: str, note: str, tags: list[str]) -> dict[str, Any]:
    args = {"amount": amount_text(cents), "kind": "expense", "date": day or None, "account": target["account"], "category": target["category"],
            "create_category": bool(target.get("create_category")), "counterparty": counterparty[:200], "note": note[:2000], "tags": tags[:20]}
    args = {k: v for k, v in args.items() if v is not None}
    out, why = unwrap(call("ledger", "add_entry", args))
    if out is None:
        return {"ok": False, "reason": why}
    entry = out.get("entry") or {}
    return {"ok": True, "entry": entry, "entry_id": str(entry.get("id") or ""), "account": (out.get("account") or {}).get("name") or target["account"]}
