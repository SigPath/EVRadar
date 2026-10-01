"""Wykrywanie zmian między skanami: NEW / PRICE_DROP / PRICE_UP / GONE / BACK."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from evradar.models import DiffKind, Offer, OfferDiff, StoredOffer


def compute_diff(
    previous: Mapping[str, StoredOffer],
    current: Iterable[Offer],
    scanned_sources: set[str],
) -> list[OfferDiff]:
    """Porównuje stan z bazy z bieżącym skanem.

    `scanned_sources` — tylko źródła zeskanowane poprawnie; oferty pozostałych
    nie są oznaczane jako zniknięte (awaria źródła != zniknięcie ofert).
    """
    diffs: list[OfferDiff] = []
    seen_ids: set[str] = set()

    for offer in current:
        seen_ids.add(offer.offer_id)
        old = previous.get(offer.offer_id)
        if old is None:
            diffs.append(OfferDiff(kind=DiffKind.NEW, offer=offer))
            continue
        new_price = offer.price_for_diff
        old_price = old.price_for_diff
        if not old.active:
            diffs.append(
                OfferDiff(
                    kind=DiffKind.BACK,
                    offer=offer,
                    old_price=old_price[0] if old_price else None,
                    new_price=new_price[0] if new_price else None,
                    price_basis=new_price[1] if new_price else None,
                )
            )
            continue
        if (
            new_price
            and old_price
            and new_price[1] == old_price[1]
            and new_price[0] != old_price[0]
        ):
            kind = DiffKind.PRICE_DROP if new_price[0] < old_price[0] else DiffKind.PRICE_UP
            diffs.append(
                OfferDiff(
                    kind=kind,
                    offer=offer,
                    old_price=old_price[0],
                    new_price=new_price[0],
                    price_basis=new_price[1],
                )
            )

    for offer_id, old in previous.items():
        if old.active and offer_id not in seen_ids and old.source in scanned_sources:
            price = old.price_for_diff
            diffs.append(
                OfferDiff(
                    kind=DiffKind.GONE,
                    offer=old,
                    old_price=price[0] if price else None,
                    price_basis=price[1] if price else None,
                )
            )
    return diffs
