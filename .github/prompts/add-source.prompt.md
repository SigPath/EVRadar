---
description: Dodaj nowe źródło ofert (adapter + fixture + test) na podstawie URL.
agent: scraper-builder
argument-hint: URL serwisu, np. https://example.pl
---
Dodaj nowe źródło dla URL: ${input:url:Adres serwisu}

Wykonaj wg wzorca referencyjnego `src/evradar/scrapers/spoticar.py` i `tests/test_spoticar.py`:

1. Sprawdź `robots.txt` serwisu. Jeśli ścieżka listingu jest zabroniona — ustaw `enabled: false` z komentarzem i zakończ.
2. Zbadaj stronę: szukaj publicznego API JSON / `__NEXT_DATA__` / JSON-LD; HTML dopiero na końcu. Znajdź parametry URL filtrujące auta elektryczne i markę.
3. Zapisz realną odpowiedź do `tests/fixtures/<source_id>/listing_page.(html|json)`.
4. Utwórz `src/evradar/scrapers/<source_id>.py` (`BaseScraper`, `parse()` jako czysta funkcja bez sieci; docstring: źródło danych + użyte filtry).
5. Zarejestruj w `src/evradar/scrapers/__init__.py` i dodaj wpis w `config/sources.yaml`.
6. Napisz `tests/test_<source_id>.py` (offline, ≥3 oferty: cena, rok, przebieg, URL, tytuł; ceny z flagą netto/brutto).
7. Uruchom scraper na żywo (`uv run evradar run --source <source_id> --dry-run --no-open`) i zweryfikuj, że zwraca oferty.
8. Uruchom `uv run pytest`, `uv run ruff check .`, `uv run mypy` i napraw błędy.
