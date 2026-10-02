"""Record ids come from the shared ULID helper; ids written by earlier versions keep working."""


def test_new_shipment_and_trip_ids_are_prefixed_ulids_and_old_ids_still_work(config, clock, fake_mail):
    from conftest import build
    from phileas_hoard.hoard_link.ids import is_ulid

    svc = build(config, clock, fake_mail)
    sid = svc.store.create_shipment(carrier="ups", number="1Z999AA10123456784", title="x")["id"]
    assert sid.startswith("s_") and is_ulid(sid[2:])
    # a row written by an earlier version keeps its short id and is found by it
    legacy = svc.store.create_shipment(id="s_0123456789", carrier="ups", number="1Z999AA10123456785", title="old")
    assert svc.store.shipment("s_0123456789")["id"] == legacy["id"] == "s_0123456789"
