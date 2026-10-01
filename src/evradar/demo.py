"""Dane syntetyczne do podglądu wyglądu raportu (`evradar demo-report`)."""

from __future__ import annotations

from datetime import timedelta

from evradar.models import (
    DiffKind,
    Offer,
    OfferDiff,
    ReportData,
    RunInfo,
    SourceResult,
    SourceStatus,
    make_offer_id,
    utcnow,
)

_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='200'>"
    "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
    "<stop offset='0' stop-color='%234f7cff'/><stop offset='1' stop-color='%2322c1c3'/>"
    "</linearGradient></defs><rect width='320' height='200' fill='url(%23g)'/>"
    "<text x='160' y='115' font-size='64' text-anchor='middle'>🚗</text></svg>"
)

def _offer(
    i: int,
    source: str,
    brand: str,
    model: str,
    year: int,
    km: int,
    gross: int | None,
    *,
    net: int | None = None,
    rate: int | None = None,
    uncertain: bool = False,
    image: bool = True,
    days_ago: int = 0,
) -> Offer:
    url = f"https://example.pl/{source}/{i}"
    now = utcnow()
    return Offer(
        offer_id=make_offer_id(source, None, url),
        source=source,
        url=url,
        brand=brand,
        model_matched=model,
        title_raw=f"{brand} {model} {year} — wersja demo",
        year=year,
        mileage_km=km,
        price_gross_pln=gross,
        price_net_pln=net,
        monthly_installment_pln=rate,
        installment_basis="net" if rate else None,
        vat_invoice=net is not None,
        battery_kwh=64.0 if model in ("e-Niro", "Kona Electric") else None,
        range_km_wltp=455 if model == "e-Niro" else None,
        location="Warszawa",
        image_url=_SVG if image else None,
        first_seen_at=now - timedelta(days=days_ago),
        last_seen_at=now,
        uncertain_powertrain=uncertain,
    )


def synthetic_report_data() -> ReportData:
    """Zestaw ofert pokrywający wszystkie sekcje raportu."""
    new = [
        _offer(1, "spoticar", "Kia", "e-Niro", 2022, 41_000, 119_900, rate=2_150),
        _offer(2, "vwfs", "Tesla", "Model 3", 2021, 68_500, None, net=118_500),
        _offer(3, "ayvens", "Hyundai", "Ioniq 5", 2023, 22_000, 169_000, net=137_398, image=False),
        _offer(4, "mauto", "Kia", "EV4", 2024, 9_000, 189_900),
    ]
    drops_base = [
        _offer(10, "automarket", "Hyundai", "Kona Electric", 2022, 35_000, 99_000, days_ago=9),
        _offer(11, "carsandcare", "Tesla", "Model Y", 2022, 54_000, 172_000, days_ago=4),
    ]
    stable = [
        _offer(20, "poleasingowe", "Kia", "e-Niro", 2021, 72_000, 104_500, days_ago=21),
        _offer(21, "leasygroup", "Kia", "Niro", 2023, 30_000, 139_000, rate=2_390, days_ago=14),
        _offer(22, "stellantis", "Tesla", "Model 3", 2020, 91_000, 98_900, days_ago=30),
    ]
    uncertain = [_offer(30, "spoticar", "Kia", "Niro", 2022, 48_000, 109_000, uncertain=True)]
    gone = [_offer(40, "vwfs", "Hyundai", "Ioniq 5", 2022, 38_000, 149_000, days_ago=12)]

    drops = [
        OfferDiff(
            kind=DiffKind.PRICE_DROP,
            offer=o.model_copy(update={"price_gross_pln": new_p}),
            old_price=old_p,
            new_price=new_p,
            price_basis="gross",
        )
        for o, old_p, new_p in zip(drops_base, (104_000, 175_500), (99_000, 172_000), strict=True)
    ]

    ok = SourceStatus.OK
    sources = [
        SourceResult(source="vwfs", name="VW Financial Services", status=ok, offers_count=5, duration_s=4.2),
        SourceResult(source="ayvens", name="Ayvens", status=ok, offers_count=3, duration_s=8.1),
        SourceResult(source="carsandcare", name="Cars&Care", status=ok, offers_count=2, duration_s=3.3),
        SourceResult(
            source="mauto", name="Mauto", status=SourceStatus.ERROR,
            error="TimeoutError: page.goto exceeded 30000 ms", duration_s=30.0,
        ),
        SourceResult(source="automarket", name="Automarket", status=ok, offers_count=6, duration_s=2.8),
        SourceResult(source="stellantis", name="Stellantis &You", status=ok, offers_count=1, duration_s=6.4),
        SourceResult(source="spoticar", name="Spoticar", status=ok, offers_count=7, duration_s=12.4),
        SourceResult(
            source="poleasingowe", name="Poleasingowe.pl", status=SourceStatus.STALE,
            duration_s=3.1, note="Zapisano debug/poleasingowe-demo.html",
        ),
        SourceResult(
            source="leasygroup", name="Leasy Group", status=SourceStatus.SKIPPED,
            note="robots.txt zabrania pobierania listingu", duration_s=0.2,
        ),
    ]
    active = [*new, *[d.offer for d in drops], *stable, *uncertain]
    return ReportData(
        run=RunInfo(run_id=None, started_at=utcnow(), duration_s=74.3, dry_run=True),
        sources=sources,
        active=active,
        new=[OfferDiff(kind=DiffKind.NEW, offer=o) for o in new],
        price_drops=drops,
        price_ups=[],
        back=[],
        gone=[
            OfferDiff(kind=DiffKind.GONE, offer=o, old_price=o.price_gross_pln, price_basis="gross")
            for o in gone
        ],
        uncertain=uncertain,
    )
