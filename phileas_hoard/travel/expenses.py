"""Shared trip expenses: splitting, balances and the fewest transfers that settle them.

Everything is computed in integer cents of the trip's base currency (an expense in another currency carries its own manual rate),
so shares always add up to the amount to the cent, with the odd cents given by largest remainder. Splitting and settling are the
shared ``money.split_shares`` and ``money.settle``.
"""

from __future__ import annotations

from typing import Any, Optional

from ..errors import PhileasError
from ..hoard_link.money import settle, split_shares  # noqa: F401 - settle: the fewest transfers that clear the balances


def cents(amount: float, rate: float = 1.0) -> int:
    return int(round(float(amount) * float(rate) * 100 + 1e-9))


def base_cents(expense: dict[str, Any]) -> int:
    return cents(expense["amount"], expense.get("rate") or 1.0)


def apportion(total: int, weights: dict[str, float], order: list[str]) -> dict[str, int]:
    """Split ``total`` cents by weight (``money.split_shares``); the leftover cents go to the largest fractional parts (ties: earlier in ``order``)."""
    positive = [(k, float(w)) for k, w in weights.items() if float(w) > 0]
    if not positive:
        raise PhileasError("invalid", "A split needs at least one person with a share.")
    positive.sort(key=lambda kw: order.index(kw[0]) if kw[0] in order else 999)
    return split_shares(total, dict(positive))


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
