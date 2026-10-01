"""Testy wykrywania zmian i magazynu SQLite."""

from __future__ import annotations

from datetime import timedelta

from evradar.diff import compute_diff
from evradar.models import (
    DiffKind,
    Offer,
    SourceResult,
    SourceStatus,
    StoredOffer,
    make_offer_id,
    utcnow,
)
from evradar.storage import Storage


def make_offer(
    url: str = "https://a.pl/1", price: int | None = 100_000, source: str = "a"
) -> Offer:
    return Offer(
        offer_id=make_offer_id(source, None, url),
        source=source,
        url=url,
        brand="Kia",
        model_matched="e-Niro",
        title_raw="Kia e-Niro",
        price_gross_pln=price,
    )


def stored(offer: Offer, active: bool = True) -> StoredOffer:
    return StoredOffer(**offer.model_dump(), active=active)


def test_offer_id_stable_and_not_from_price() -> None:
    a = make_offer(price=1)
    b = make_offer(price=2)
    assert a.offer_id == b.offer_id
    assert make_offer_id("a", None, "https://a.pl/1?utm_source=x#f") == a.offer_id


def test_new_offer() -> None:
    o = make_offer()
    diffs = compute_diff({}, [o], {"a"})
    assert [d.kind for d in diffs] == [DiffKind.NEW]


def test_price_drop_and_up() -> None:
    old = make_offer(price=100_000)
    drop = compute_diff({old.offer_id: stored(old)}, [make_offer(price=90_000)], {"a"})
    assert drop[0].kind is DiffKind.PRICE_DROP
    assert drop[0].delta == -10_000
    assert drop[0].delta_pct == -10.0
    up = compute_diff({old.offer_id: stored(old)}, [make_offer(price=110_000)], {"a"})
    assert up[0].kind is DiffKind.PRICE_UP


def test_unchanged_has_no_diff() -> None:
    o = make_offer()
    assert compute_diff({o.offer_id: stored(o)}, [make_offer()], {"a"}) == []


def test_gone_only_for_scanned_sources() -> None:
    o = make_offer()
    prev = {o.offer_id: stored(o)}
    assert [d.kind for d in compute_diff(prev, [], {"a"})] == [DiffKind.GONE]
    assert compute_diff(prev, [], {"b"}) == []  # źródło "a" padło — nie ma wniosków


def test_back() -> None:
    o = make_offer()
    diffs = compute_diff({o.offer_id: stored(o, active=False)}, [make_offer(price=95_000)], {"a"})
    assert diffs[0].kind is DiffKind.BACK
    assert diffs[0].new_price == 95_000


def test_net_vs_gross_not_compared() -> None:
    old = make_offer(price=100_000)
    new = old.model_copy(update={"price_gross_pln": None, "price_net_pln": 81_000})
    assert compute_diff({old.offer_id: stored(old)}, [new], {"a"}) == []


def test_storage_roundtrip_and_lifecycle() -> None:
    db = Storage(":memory:")
    t0 = utcnow()
    o = make_offer(price=100_000)
    res = [SourceResult(source="a", name="A", status=SourceStatus.OK, offers_count=1, raw_count=5)]

    diffs = compute_diff(db.load_offers(), [o], {"a"})
    run1 = db.save_run(t0, 1.0, res, [o], diffs)
    assert db.last_raw_count("a") == 5

    cheaper = make_offer(price=90_000)
    cheaper.last_seen_at = t0 + timedelta(days=1)
    diffs = compute_diff(db.load_offers(), [cheaper], {"a"})
    run2 = db.save_run(t0 + timedelta(days=1), 1.0, res, [cheaper], diffs)
    assert run2 > run1
    assert len(db.price_history(o.offer_id)) == 2
    stored_o = db.load_offers()[o.offer_id]
    assert stored_o.first_seen_at == o.first_seen_at
    assert stored_o.price_gross_pln == 90_000

    data = db.load_report_data(run2)
    assert data is not None
    assert [d.kind for d in data.price_drops] == [DiffKind.PRICE_DROP]
    assert len(data.active) == 1

    diffs = compute_diff(db.load_offers(), [], {"a"})
    run3 = db.save_run(t0 + timedelta(days=2), 1.0, res, [], diffs)
    data3 = db.load_report_data(run3)
    assert data3 is not None and len(data3.gone) == 1 and data3.active == []

    back = make_offer(price=85_000)
    diffs = compute_diff(db.load_offers(), [back], {"a"})
    run4 = db.save_run(t0 + timedelta(days=3), 1.0, res, [back], diffs)
    data4 = db.load_report_data(run4)
    assert data4 is not None and [d.kind for d in data4.back] == [DiffKind.BACK]
    assert len(data4.active) == 1
