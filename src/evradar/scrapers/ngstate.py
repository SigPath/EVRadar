"""Pomocnik: dane osadzone przez Angular SSR w `<script id="ng-state" type="application/json">`."""

from __future__ import annotations

import json
from typing import Any

from selectolax.parser import HTMLParser


def extract_ng_state(html: str) -> dict[str, Any]:
    """Zwraca zawartość `ng-state` (TransferState) albo ValueError, gdy zmieniła się struktura."""
    node = HTMLParser(html).css_first("script#ng-state")
    if node is None:
        raise ValueError("Brak ng-state — zmieniła się struktura strony")
    state: dict[str, Any] = json.loads(node.text())
    return state
