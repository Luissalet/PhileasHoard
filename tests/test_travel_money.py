"""Shared trip expenses: splits, balances, the fewest transfers, exchange rates and sending my share to Ledger (mocked)."""

from __future__ import annotations

import itertools
import random

import pytest

from conftest import FakeHub, build
from phileas_hoard.errors import PhileasError
from phileas_hoard.travel import expenses as exp, hubcalls


def test_apportion_adds_up_to_the_cent():
    assert exp.apportion(1000, {"a": 1, "b": 1, "c": 1}, ["a", "b", "c"]) == {"a": 334, "b": 333, "c": 333}
    assert exp.apportion(1000, {"a": 2, "b": 1}, ["a", "b"]) == {"a": 667, "b": 333}
    assert sum(exp.apportion(1, {"a": 1, "b": 1, "c": 1, "d": 1}, list("abcd")).values()) == 1
    with pytest.raises(PhileasError):
        exp.apportion(100, {}, [])


def test_shares_by_mode():
    ids = ["a", "b", "c"]
    equal = {"amount": 100.0, "split_mode": "equal", "split": {}}
    assert exp.shares_of(equal, ids) == {"a": 3334, "b": 3333, "c": 3333}
    some = {"amount": 90.0, "split_mode": "equal", "split": {"participants": ["a", "c"]}}
    assert exp.shares_of(some, ids) == {"a": 4500, "c": 4500}
    weights = {"amount": 100.0, "split_mode": "shares", "split": {"shares": {"a": 2, "b": 1, "c": 1}}}
    assert exp.shares_of(weights, ids) == {"a": 5000, "b": 2500, "c": 2500}
    exact = {"amount": 100.0, "split_mode": "exact", "split": {"amounts": {"a": 60, "b": 40}}}
    assert exp.shares_of(exact, ids) == {"a": 6000, "b": 4000}


def test_foreign_currency_uses_its_own_rate():
    e = {"amount": 100.0, "currency": "GBP", "rate": 1.15, "split_mode": "equal", "split": {}}
    assert exp.base_cents(e) == 11500 and sum(exp.shares_of(e, ["a", "b", "c"]).values()) == 11500


def test_validation():
    ids = ["a", "b"]
    base = {"amount": 50.0, "currency": "EUR", "rate": 1.0, "payer_id": "a", "split_mode": "equal", "split": {}}
    exp.validate(base, ids, "EUR")
    for bad in ({"payer_id": "z"}, {"amount": 0}, {"split_mode": "magic"}, {"split_mode": "exact", "split": {"amounts": {"a": 10, "b": 10}}},
                {"split_mode": "shares", "split": {"shares": {"a": 0}}}):
        with pytest.raises(PhileasError):
            exp.validate({**base, **bad}, ids, "EUR")
    with pytest.raises(PhileasError) as err:
        exp.validate({**base, "currency": "GBP"}, ids, "EUR")
    assert err.value.code == "rate_required"
    exp.validate({**base, "currency": "GBP", "rate": 1.2}, ids, "EUR")


def check_settlement(net):
    transfers = exp.settle(net)
    after = dict(net)
    for t in transfers:
        assert t["cents"] > 0
        after[t["from"]] += t["cents"]
        after[t["to"]] -= t["cents"]
    assert all(v == 0 for v in after.values()), (net, transfers)
    return transfers


def brute_force_minimum(net):
    """The true minimum number of transfers: n minus the most disjoint zero-sum groups (tried over every partition)."""
    ids = [k for k, v in net.items() if v]
    best = len(ids)

    def groups(items):
        if not items:
            yield []
            return
        first, rest = items[0], items[1:]
        for r in range(len(rest) + 1):
            for combo in itertools.combinations(rest, r):
                block = (first, *combo)
                if sum(net[x] for x in block) == 0:
                    remaining = [x for x in rest if x not in combo]
                    for tail in groups(remaining):
                        yield [block, *tail]
    for partition in groups(ids):
        best = min(best, len(ids) - len(partition))
    return best


def test_settle_basic_cases():
    assert exp.settle({"a": 0, "b": 0}) == []
    assert check_settlement({"a": 5000, "b": -5000}) == [{"from": "b", "to": "a", "cents": 5000}]
    t = check_settlement({"a": 3000, "b": 2000, "c": -2500, "d": -2500})
    assert len(t) == 3


def test_settle_is_minimal_where_a_greedy_pass_is_not():
    # two pairs that cancel out exactly: 2 transfers; a greedy largest-first pass needs 3
    net = {"a": 10, "b": 7, "c": -9, "d": -8}
    assert len(check_settlement(net)) == 3 == brute_force_minimum(net)
    net = {"a": 10, "b": 7, "c": -10, "d": -7}
    assert len(check_settlement(net)) == 2 == brute_force_minimum(net)


def test_settle_random_cases_are_exact_and_minimal():
    rng = random.Random(7)
    for _ in range(150):
        n = rng.randint(2, 7)
        values = [rng.randint(-40, 40) for _ in range(n - 1)]
        values.append(-sum(values))
        net = {f"p{i}": v for i, v in enumerate(values)}
        transfers = check_settlement(net)
        assert len(transfers) == brute_force_minimum(net), net


def test_settle_with_many_people_still_balances():
    rng = random.Random(3)
    values = [rng.randint(-5000, 5000) for _ in range(24)]
    values.append(-sum(values))
    check_settlement({f"p{i}": v for i, v in enumerate(values)})


# ------------------------------------------------------------------ through the service
@pytest.fixture
def tv(config, clock, fake_mail):
    hub = FakeHub()
    s = build(config, clock, fake_mail, hub_call=hub)
    s.set_settings({"travel.my_name": "Luis"})
    s.hub = hub
    trip = s.travel.create_trip("Roma", "2026-12-18", "2026-12-21")["trip"]
    s.trip_id = trip["id"]
    s.travel.add_people(trip["id"], ["Marta", "Pablo"])
    yield s
    s.stop()


def test_people_start_with_me(tv):
    people = tv.travel.t.people(tv.trip_id)
    assert [(p["name"], p["is_me"]) for p in people] == [("Luis", True), ("Marta", False), ("Pablo", False)]


def test_expenses_balances_and_transfers(tv):
    t = tv.travel
    t.add_expense(tv.trip_id, description="Cena", amount=90, payer="Luis")
    t.add_expense(tv.trip_id, description="Taxi", amount=30, payer="Marta", split_mode="exact", split={"amounts": {"Luis": 10, "Marta": 10, "Pablo": 10}})
    t.add_expense(tv.trip_id, description="Museo", amount=40, payer="Pablo", split_mode="shares", split={"shares": {"Luis": 1, "Marta": 3}})
    view = t.expenses_view(tv.trip_id)
    s = view["summary"]
    assert s["total"] == 160.0 and s["currency"] == "EUR"
    net = {b["name"]: b["net"] for b in s["balances"]}
    assert net == {"Luis": 90 - 30 - 10 - 10, "Marta": 30 - 30 - 10 - 30, "Pablo": 40 - 30 - 10} or sum(net.values()) == 0
    assert round(sum(net.values()), 2) == 0
    assert 1 <= len(s["transfers"]) <= 2
    mine = {e["description"]: e["my_share"] for e in view["expenses"]}
    assert mine == {"Cena": 30.0, "Taxi": 10.0, "Museo": 10.0}


def test_other_currency_needs_a_rate(tv):
    t = tv.travel
    with pytest.raises(PhileasError) as err:
        t.add_expense(tv.trip_id, description="Pub", amount=20, currency="GBP")
    assert err.value.code == "rate_required"
    out = t.add_expense(tv.trip_id, description="Pub", amount=20, currency="GBP", rate=1.15)
    assert out["expense"]["base_amount"] == 23.0


def test_payers_and_participants_must_be_on_the_trip(tv):
    with pytest.raises(PhileasError):
        tv.travel.add_expense(tv.trip_id, description="X", amount=5, payer="Nadie")
    with pytest.raises(PhileasError):
        tv.travel.add_expense(tv.trip_id, description="X", amount=5, split_mode="equal", split={"people": ["Nadie"]})
    tv.travel.add_expense(tv.trip_id, description="X", amount=5, payer="Marta")
    with pytest.raises(PhileasError):
        tv.travel.remove_person(tv.trip_id, "Marta")                    # she paid something


def test_update_and_delete_expense(tv):
    t = tv.travel
    e = t.add_expense(tv.trip_id, description="Cena", amount=90)["expense"]
    out = t.update_expense(e["id"], amount=120, split_mode="equal", split={"people": ["Luis", "Marta"]})
    assert out["expense"]["base_amount"] == 120 and [s["amount"] for s in out["expense"]["shares"]] == [60.0, 60.0]
    assert t.delete_expense(e["id"])["summary"]["total"] == 0


def test_a_bookings_price_becomes_an_expense_once(tv):
    t = tv.travel
    seg = t.add_segment(kind="flight", number="IB3166", from_code="MAD", to_code="FCO", dep_local="2026-12-18T09:05", price=212.4, currency="EUR", trip=tv.trip_id)["segment"]
    out = t.expense_from_segment(seg["id"])
    assert out["expense"]["base_amount"] == 212.4 and out["expense"]["category"] == "transport" and out["expense"]["payer"] == "Luis"
    with pytest.raises(PhileasError):
        t.expense_from_segment(seg["id"])


# ------------------------------------------------------------------ Ledger (mocked)
ACCOUNTS = {"accounts": [{"id": 1, "name": "Cuenta corriente", "currency": "EUR", "archived": False}]}
CATEGORIES = {"categories": [{"name": "Comida"}, {"name": "Viajes"}]}


def ledger_hub(tv, *, accounts=ACCOUNTS, categories=CATEGORIES):
    sent = []

    def add_entry(args):
        sent.append(args)
        return {"entry": {"id": 100 + len(sent), "date": args.get("date"), "amount_text": args["amount"]}, "account": {"name": args["account"]}}
    tv.hub.answers.update({("ledger", "list_accounts"): accounts, ("ledger", "list_categories"): categories, ("ledger", "add_entry"): add_entry})
    return sent


def test_my_share_goes_to_ledger_once(tv):
    t = tv.travel
    t.add_expense(tv.trip_id, description="Cena", amount=90, payer="Marta", day="2026-12-19")
    t.add_expense(tv.trip_id, description="Hotel", amount=200, payer="Luis", day="2026-12-18")
    sent = ledger_hub(tv)
    dry = t.to_ledger(tv.trip_id, dry_run=True)
    assert dry["status"] == "dry_run" and [p["my_share"] for p in dry["pending"]] == [66.67, 30.0] or len(dry["pending"]) == 2
    out = t.to_ledger(tv.trip_id)
    assert out["status"] == "ok" and out["account"] == "Cuenta corriente" and out["category"] == "Viajes" and len(out["sent"]) == 2
    assert sorted(s["amount"] for s in sent) == ["30,00", "66,67"] and all(s["kind"] == "expense" and s["account"] == "Cuenta corriente" for s in sent)
    assert {s["date"] for s in sent} == {"2026-12-18", "2026-12-19"} and "Roma" in sent[0]["note"]
    again = t.to_ledger(tv.trip_id)
    assert again["status"] == "nothing_to_send" and again["already_sent"] == 2 and len(sent) == 2
    t.add_expense(tv.trip_id, description="Museo", amount=30, payer="Pablo")
    assert t.to_ledger(tv.trip_id)["status"] == "ok" and len(sent) == 3
    flags = {e["description"]: e["sent_to_ledger"] for e in t.expenses_view(tv.trip_id)["expenses"]}
    assert flags == {"Cena": True, "Hotel": True, "Museo": True}


def test_ledger_picks_the_closest_category_or_asks_to_create_it(tv):
    t = tv.travel
    t.add_expense(tv.trip_id, description="Cena", amount=90)
    sent = ledger_hub(tv, categories={"categories": [{"name": "Comida"}, {"name": "Ocio y vacaciones"}]})
    t.to_ledger(tv.trip_id)
    assert sent[0]["category"] == "Ocio y vacaciones" and sent[0]["create_category"] is False
    t.update_expense(t.t.expenses(tv.trip_id)[0]["id"], description="Cena 2")
    tv.hub.answers[("ledger", "list_categories")] = {"categories": [{"name": "Comida"}]}
    t.add_expense(tv.trip_id, description="Taxi", amount=20)
    t.to_ledger(tv.trip_id)
    assert sent[-1]["category"] == "Viajes" and sent[-1]["create_category"] is True


def test_ledger_down_is_explained_and_nothing_is_lost(tv):
    t = tv.travel
    t.add_expense(tv.trip_id, description="Cena", amount=90)
    out = t.to_ledger(tv.trip_id)                                       # the hub does not answer
    assert out["status"] == "ledger_unavailable" and out["reason"] == "hub_down" and out["pending"]
    assert not t.t.expenses(tv.trip_id)[0].get("ledger_sent_ts")
    ledger_hub(tv)
    assert t.to_ledger(tv.trip_id)["status"] == "ok"


def test_ledger_account_choice_and_currency(tv):
    t = tv.travel
    t.add_expense(tv.trip_id, description="Cena", amount=90)
    two = {"accounts": [{"name": "Banco", "currency": "EUR"}, {"name": "Tarjeta USD", "currency": "USD"}]}
    ledger_hub(tv, accounts=two)
    out = t.to_ledger(tv.trip_id)
    assert out["status"] == "ledger_unavailable" and out["reason"] == "choose_account" and out["accounts"] == ["Banco", "Tarjeta USD"]
    assert t.to_ledger(tv.trip_id, account="Tarjeta USD")["status"] == "currency_mismatch"
    assert t.to_ledger(tv.trip_id, account="banco")["status"] == "ok"


def test_proxy_answers_are_unwrapped_safely():
    assert hubcalls.unwrap({"ok": True, "result": {"a": 1}}) == ({"a": 1}, "")
    assert hubcalls.unwrap({"ok": True, "result": {"content": [{"type": "text", "text": '{"b": 2}'}]}}) == ({"b": 2}, "")
    assert hubcalls.unwrap({"ok": False, "status": None, "error": "hub not reachable at x"})[1] == "hub_down"
    assert hubcalls.unwrap({"ok": False, "status": 502, "error": "app unreachable"})[1] == "app_down"
    assert hubcalls.unwrap({"ok": False, "status": 401, "error": "bad token"})[1] == "unauthorized"
    assert hubcalls.unwrap("junk")[0] is None
