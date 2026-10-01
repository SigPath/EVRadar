"""Dekoder formatu `devalue` używanego w `<script id="__NUXT_DATA__">` (Nuxt 3)."""

from __future__ import annotations

import json
from typing import Any

from selectolax.parser import HTMLParser

_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}


def extract_nuxt_data(html: str) -> Any:
    """Zwraca zdekodowane drzewo danych z `__NUXT_DATA__` albo rzuca ValueError."""
    node = HTMLParser(html).css_first("script#__NUXT_DATA__")
    if node is None:
        raise ValueError("Brak __NUXT_DATA__ — zmieniła się struktura strony")
    table: list[Any] = json.loads(node.text())
    cache: dict[int, Any] = {}

    def ref(x: Any) -> Any:
        if isinstance(x, int) and not isinstance(x, bool):
            return None if x == -1 else dec(x)
        return x

    def dec(i: int) -> Any:
        if i in cache:
            return cache[i]
        value = table[i]
        if isinstance(value, list):
            if value and isinstance(value[0], str) and value[0] in _WRAPPERS:
                cache[i] = dec(value[1])
                return cache[i]
            if value and isinstance(value[0], str):
                cache[i] = (value[0], value[1:])  # typy specjalne (Date, Set, ...) — nieużywane
                return cache[i]
            out_list: list[Any] = []
            cache[i] = out_list
            out_list.extend(ref(x) for x in value)
            return out_list
        if isinstance(value, dict):
            out_dict: dict[str, Any] = {}
            cache[i] = out_dict
            for key, x in value.items():
                out_dict[key] = ref(x)
            return out_dict
        cache[i] = value
        return value

    return dec(0)
