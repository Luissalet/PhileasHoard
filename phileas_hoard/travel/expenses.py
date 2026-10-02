"""Shared trip expenses: splitting, balances and the fewest transfers that settle them.

Everything is computed in integer cents of the trip's base currency (an expense in another currency carries its own manual rate),
so shares always add up to the amount to the cent, with the odd cents given by largest remainder.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from ..errors import PhileasError

EXACT_LIMIT = 16        # settle is exact up to this many people with a balance; beyond it a greedy pass is used


def cents(amount: float, rate: float = 1.0) -> int:
    return int(round(float(amount) * float(rate) * 100 + 1e-9))


def base_cents(expense: dict[str, Any]) -> int:
    return cents(expense["amount"], expense.get("rate") or 1.0)


def apportion(total: int, weights: dict[str, float], order: list[str]) -> dict[str, int]:
    """Split ``total`` cents by weight; the leftover cents go to the largest fractional parts (ties: earlier in ``order``)."""
    weights = {k: float(w) for k, w in weights.items() if float(w) > 0}
    whole = sum(weights.values())
    if not weights or whole <= 0:
        raise PhileasError("invalid", "A split needs at least one person with a share.")
    raw = {k: total * w / whole for k, w in weights.items()}
    out = {k: int(math.floor(v + 1e-9)) for k, v in raw.items()}
    left = total - sum(out.values())
    ranked = sorted(raw, key=lambda k: (-(raw[k] - out[k]), order.index(k) if k in order else 999))
    for k in ranked[:max(0, left)]:
        out[k] += 1
    return out


def validate(expense: dict[str, Any], person_ids: list[str], base_currency: str) -> None:
    mode = expense.get("split_mode") or "equal"
    split = expense.get("split") or {}
    if expense.get("payer_id") not in person_ids:
        raise PhileasError("invalid", "The payer is not on this trip.", "Add the person to the trip first (trip_update add_people).")
    if float(expense.get("amount") or 0) <= 0:
        raise PhileasError("invalid", "The amount must be positive.")
    cur = (expense.get("currency") or base_currency).upper()
    if cur != base_currency.upper() and not (expense.get("rate") and float(expense["rate"]) > 0 and float(expense["rate"]) != 1.0):
        raise PhileasError("rate_required", f"The expense is in {cur} but the trip is in {base_currency}: give the exchange rate (1 {cur} = x {base_currency}).",
                           "Rates are never fetched from the network; use the one you paid.")
    if mode == "equal":
        who = split.get("participants") or person_ids
        if not who or any(p not in person_ids for p in who):
            raise PhileasError("invalid", "Everybody in an equal split must be on the trip.")
    elif mode == "shares":
        weights = split.get("shares") or {}
        if not weights or any(p not in person_ids for p in weights) or not any(float(w) > 0 for w in weights.values()):
            raise PhileasError("invalid", "Shares need a positive weight per person on the trip.")
    elif mode == "exact":
        amounts = split.get("amounts") or {}
        if not amounts or any(p not in person_ids for p in amounts):
            raise PhileasError("invalid", "Exact amounts need a person on the trip for each line.")
        total = sum(cents(a, expense.get("rate") or 1.0) for a in amounts.values())
        if abs(total - base_cents(expense)) > 1:
            raise PhileasError("invalid", f"The exact amounts add up to {total / 100:.2f}, not {base_cents(expense) / 100:.2f}.",
                               "They must add up to the expense amount.")
    else:
        raise PhileasError("invalid", f"Unknown split mode {mode!r}.", "Use equal, shares or exact.")


def shares_of(expense: dict[str, Any], person_ids: list[str]) -> dict[str, int]:
    """What each person owes for one expense, in cents of the base currency."""
    total = base_cents(expense)
    mode = expense.get("split_mode") or "equal"
    split = expense.get("split") or {}
    if mode == "exact":
        amounts = {p: cents(a, expense.get("rate") or 1.0) for p, a in (split.get("amounts") or {}).items() if p in person_ids}
        drift = total - sum(amounts.values())
        if amounts and drift:
            first = next(iter(amounts))
            amounts[first] += drift                      # a one-cent rounding difference lands on the first line
        return amounts
    if mode == "shares":
        weights = {p: w for p, w in (split.get("shares") or {}).items() if p in person_ids}
    else:
        weights = {p: 1 for p in (split.get("participants") or person_ids) if p in person_ids}
    return apportion(total, weights, person_ids)


def balances(people: list[dict[str, Any]], expenses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [p["id"] for p in people]
    paid = {i: 0 for i in ids}
    owed = {i: 0 for i in ids}
    for e in expenses:
        if e.get("payer_id") in paid:
            paid[e["payer_id"]] += base_cents(e)
        for pid, c in shares_of(e, ids).items():
            owed[pid] += c
    return [{"person_id": p["id"], "name": p["name"], "is_me": p.get("is_me", False), "paid": paid[p["id"]], "owed": owed[p["id"]],
             "net": paid[p["id"]] - owed[p["id"]]} for p in people]


def settle(net: dict[str, int]) -> list[dict[str, Any]]:
    """The fewest transfers that bring every net balance to zero: ``[{"from", "to", "cents"}]`` (debtor pays creditor).

    Exact: people are grouped into the largest number of subsets that already balance among themselves; a group of k people needs
    k-1 transfers, so more groups means fewer transfers. Beyond ``EXACT_LIMIT`` people with a balance a greedy pass is used."""
    ids = [k for k, v in net.items() if v != 0]
    if not ids:
        return []
    groups = _groups(ids, net) if len(ids) <= EXACT_LIMIT else [ids]
    out: list[dict[str, Any]] = []
    for group in groups:
        debtors = sorted(([-net[i], i] for i in group if net[i] < 0), key=lambda x: (-x[0], x[1]))
        creditors = sorted(([net[i], i] for i in group if net[i] > 0), key=lambda x: (-x[0], x[1]))
        while debtors and creditors:
            amount = min(debtors[0][0], creditors[0][0])
            out.append({"from": debtors[0][1], "to": creditors[0][1], "cents": amount})
            debtors[0][0] -= amount
            creditors[0][0] -= amount
            if debtors[0][0] == 0:
                debtors.pop(0)
            if creditors and creditors[0][0] == 0:
                creditors.pop(0)
            debtors.sort(key=lambda x: (-x[0], x[1]))
            creditors.sort(key=lambda x: (-x[0], x[1]))
    return out


def _groups(ids: list[str], net: dict[str, int]) -> list[list[str]]:
    n = len(ids)
    full = (1 << n) - 1
    total = [0] * (1 << n)
    for mask in range(1, 1 << n):
        low = (mask & -mask).bit_length() - 1
        total[mask] = total[mask & (mask - 1)] + net[ids[low]]
    best = [0] * (1 << n)
    pick = [0] * (1 << n)
    for mask in range(1, 1 << n):
        top, choice = -1, 0
        for i in range(n):
            if mask >> i & 1:
                value = best[mask ^ (1 << i)]
                if value > top:
                    top, choice = value, i
        best[mask] = top + (1 if total[mask] == 0 else 0)
        pick[mask] = choice
    order: list[int] = []
    mask = full
    while mask:
        i = pick[mask]
        order.append(i)
        mask ^= 1 << i
    order.reverse()
    groups: list[list[str]] = []
    current: list[str] = []
    running = 0
    for i in order:
        current.append(ids[i])
        running += net[ids[i]]
        if running == 0:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def my_share(expense: dict[str, Any], me_id: Optional[str], person_ids: list[str]) -> int:
    return shares_of(expense, person_ids).get(me_id or "", 0)


def summary(people: list[dict[str, Any]], expenses: list[dict[str, Any]], currency: str) -> dict[str, Any]:
    bal = balances(people, expenses)
    names = {p["id"]: p["name"] for p in people}
    transfers = [{"from": t["from"], "from_name": names.get(t["from"], ""), "to": t["to"], "to_name": names.get(t["to"], ""), "amount": t["cents"] / 100}
                 for t in settle({b["person_id"]: b["net"] for b in bal})]
    by_cat: dict[str, int] = {}
    for e in expenses:
        by_cat[e.get("category") or "other"] = by_cat.get(e.get("category") or "other", 0) + base_cents(e)
    return {"currency": currency, "total": sum(base_cents(e) for e in expenses) / 100,
            "balances": [{**b, "paid": b["paid"] / 100, "owed": b["owed"] / 100, "net": b["net"] / 100} for b in bal],
            "transfers": transfers, "by_category": {k: v / 100 for k, v in sorted(by_cat.items())}}
