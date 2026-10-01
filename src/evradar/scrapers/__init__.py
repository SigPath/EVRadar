"""Auto-discovery adapterów: `evradar.scrapers.<source_id>` -> podklasa BaseScraper."""

from __future__ import annotations

import importlib
import inspect

from evradar.scrapers.base import BaseScraper


def get_scraper_class(source_id: str) -> type[BaseScraper]:
    """Ładuje moduł `evradar.scrapers.<source_id>` i zwraca zdefiniowaną w nim klasę adaptera."""
    module = importlib.import_module(f"evradar.scrapers.{source_id}")
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, BaseScraper)
            and obj is not BaseScraper
            and obj.__module__ == module.__name__
        ):
            return obj
    raise LookupError(f"Moduł {source_id} nie definiuje podklasy BaseScraper")
