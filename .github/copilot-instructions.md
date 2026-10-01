# EV Radar — instrukcje dla Copilota

Agregator ofert leasingowych/poleasingowych aut elektrycznych (9 polskich serwisów) z samodzielnym raportem HTML.

## Stack
- Python 3.12, `uv` (fallback: venv + pip), layout `src/`
- `playwright` (chromium) dla stron dynamicznych, `httpx` + `selectolax` dla statycznych/API
- `pydantic` v2, `sqlite3` (bez ORM), `jinja2`, `structlog` + `rich`, `typer`
- `pytest` + `pytest-asyncio`, `ruff`, `mypy --strict`

## Konwencje
- Pakiet: `src/evradar/`; scrapery w `src/evradar/scrapers/<source_id>.py`, klasa `<Source>Scraper(BaseScraper)`.
- `source_id` = nazwa pliku = klucz w `config/sources.yaml` = katalog fixture'ów.
- Nazwy: `snake_case` (funkcje, moduły), `PascalCase` (klasy), `UPPER_SNAKE` (stałe).
- Type hints obowiązkowe (`mypy --strict`). Docstringi i komentarze po polsku, krótkie.
- Logowanie wyłącznie przez `structlog` (`log = structlog.get_logger()`); **zero `print`** (użyj `rich.console` w CLI).
- Konfiguracja w YAML (`config/`), nic nie jest zahardkodowane (modele, filtry, URL-e, opóźnienia).
- Ceny: zawsze zapisuj czy netto czy brutto, nigdy nie przeliczaj "na oko".
- Awaria jednego źródła nie przerywa runu; `robots.txt` jest respektowany; bez omijania CAPTCHA/antybota; bez logowania.

## Zasada scraperów
Każdy nowy scraper = fixture (`tests/fixtures/<source>/`) + test offline (`tests/test_<source>.py`).
Selektorów nie wymyślamy — najpierw pobierz realną stronę/API, zapisz fixture, dopiero pisz parser.
Preferuj publiczne API JSON nad HTML. Udokumentuj w docstringu modułu źródło danych i parametry filtrów URL.

## Polecenia
- Instalacja: `uv sync` (potem `uv run playwright install chromium`)
- Testy: `uv run pytest`
- Lint: `uv run ruff check . && uv run mypy`
- Uruchomienie: `uv run evradar run`
