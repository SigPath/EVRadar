# EV Radar

Codziennie przeszukuje polskie serwisy z autami leasingowymi/poleasingowymi, wyłuskuje **tylko wybrane modele elektryczne** (Kia e-Niro/Niro EV/EV4, Hyundai Kona Electric/Ioniq 5, Tesla Model 3/Y — lista jest w pliku konfiguracyjnym) i tworzy **jeden plik HTML**, który otwierasz dwuklikiem:

- **Nowe oferty** (od ostatniego skanu), **obniżki cen**, **wróciły**, **zniknęły**,
- **Do weryfikacji** — oferty, przy których nie da się jednoznacznie stwierdzić, że to auto elektryczne (np. Kia Niro bez podanego paliwa),
- tabela wszystkich aktywnych ofert z sortowaniem, filtrami i wyszukiwarką,
- status każdego źródła (OK / BŁĄD / POMINIĘTE / DO AKTUALIZACJI).

## Uruchomienie krok po kroku (Windows)

1. Zainstaluj **uv** (menedżer Pythona): otwórz PowerShell i wpisz `winget install astral-sh.uv` (albo `pip install uv`). Zamknij i otwórz PowerShell ponownie.
2. Wejdź do folderu projektu i pobierz zależności (jednorazowo):
   ```powershell
   cd C:\Dev\EVLeaseSentinel
   uv sync
   ```
3. Uruchom skan:
   ```powershell
   uv run evradar run
   ```
   Po kilkunastu sekundach w terminalu pojawi się tabelka z wynikami, a raport otworzy się sam w przeglądarce.
   Pliki raportów leżą w folderze `out\` (`index.html`), baza ofert w `data\evradar.db`.

Albo po prostu dwukliknij **`run_daily.bat`**.

### Przydatne polecenia

| Polecenie | Co robi |
|---|---|
| `uv run evradar run` | skan wszystkich źródeł + raport |
| `uv run evradar run --source mauto,ayvens` | tylko wybrane źródła |
| `uv run evradar run --dry-run` | skan bez zapisu do bazy (nic się „nie zużywa” jako nowe) |
| `uv run evradar run --no-open` | bez otwierania przeglądarki |
| `uv run evradar run --no-headless` | widoczna przeglądarka (dla adapterów używających Playwright) |
| `uv run evradar report --last` | przegenerowanie raportu z bazy, bez skanowania |
| `uv run evradar sources` | lista źródeł i status ostatniego skanu |
| `uv run evradar demo-report` | raport na danych przykładowych (podgląd wyglądu) |

## Co jest skanowane

| Źródło | Stan | Skąd dane | Ceny |
|---|---|---|---|
| `vwfs` — VW Financial Services Store | działa | JSON z `__NEXT_DATA__` (`/oferty?rodzajPaliwa=5`) | brutto + netto |
| `ayvens` — Ayvens (usedcars.ayvens.com) | działa | HTML SSR + JSON w kafelkach | brutto („Zawiera 23% VAT”) |
| `mauto` — mAuto | działa | API JSON (`Offers/AfterLease`, `Offers/NewVehicles`, filtr paliwa) | brutto + netto |
| `automarket` — Automarket (PKO Leasing) | działa | `__NUXT_DATA__` (`?fuel_type=Elektryczny`, per marka) | netto → brutto +23% |
| `stellantis` — Stellantis &You | działa | publiczny indeks Algolia używany przez stronę | brutto |
| `poleasingowe` — Poleasingowe.pl | działa | HTML (`?fueltype=216`) | cena aukcyjna **netto** (patrz uwaga) |

Uwagi:
- Cena jest zawsze pokazywana w brutto. Gdy serwis podaje tylko netto (Automarket, Poleasingowe.pl), brutto = netto + 23% VAT, liczone przy każdym skanie; kwota netto jest zapisana obok. Raport pokazuje „brutto” i „netto” przy kwocie.
- Poleasingowe.pl to aukcje — „Aktualna cena” to bieżąca oferta (bez prowizji); strona aukcji pokazuje ją z przełącznikiem netto/brutto (domyślnie netto).
- Część serwisów aktualnie nie ma w ofercie żadnego z wybranych modeli (np. VWFS sprzedaje wyłącznie marki grupy VW) — wtedy źródło ma status OK i 0 ofert.
- Żaden z obecnych adapterów nie wymaga przeglądarki (wszędzie udało się użyć publicznego API/JSON). Playwright jest gotowy w zależnościach na wypadek stron, które tego wymagają.

## Konfiguracja

**`config/models.yaml`** — które modele Cię interesują, aliasy nazw i filtry:

```yaml
targets:
  kia:
    - { model: "Niro", aliases: ["Niro"], require_electric: true }   # odfiltrowuje HEV/PHEV
filters:
  max_price_gross_pln: 150000   # null = bez limitu
  max_mileage_km: null
  min_year: 2022
```

Dopasowanie nazw ignoruje wielkość liter, spacje, myślniki i polskie znaki (`IONIQ5` = `Ioniq 5`), a w ostateczności używa dopasowania rozmytego (≥ 90%, nigdy dla różnych cyfr — `Ioniq 6` to nie `Ioniq 5`).
`require_electric: true` — model występuje też jako hybryda/spalinowy (Niro, Kona), więc oferta musi mieć potwierdzony napęd elektryczny. Gdy dane są niejednoznaczne, oferta trafia do sekcji **Do weryfikacji** (nie jest po cichu odrzucana).
Cenowe filtry (`max_price_gross_pln`) działają na cenie brutto (dla ofert podanych netto — po doliczeniu 23% VAT).

**`config/sources.yaml`** — adresy, opóźnienia (`delay_min_s`/`delay_max_s`), `max_pages`, `enabled: true/false` (z `reason`).

## Automatyczny codzienny skan

- **Harmonogram zadań Windows:** utwórz zadanie uruchamiające `run_daily.bat` raz dziennie (np. 07:00). Raport zapisze się w `out\` i otworzy w przeglądarce (możesz dodać argument `--no-open`).
- **GitHub Actions:** `.github/workflows/daily.yml` uruchamia skan o 07:00 czasu warszawskiego, cache'uje bazę SQLite między uruchomieniami i publikuje raport jako artefakt (`evradar-report`) oraz na **GitHub Pages** (`index.html`). Jednorazowo włącz w repozytorium: *Settings → Pages → Source: GitHub Actions*. `.github/workflows/ci.yml` uruchamia testy i linter.
- **Powiadomienia (opcjonalne):** w `config/models.yaml` ustaw `notifications.enabled: true`, a w środowisku `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID` (w GitHubie: *Secrets*). Wiadomość wyjdzie tylko gdy są nowe oferty.

## Jak dodać nowe źródło

1. W `config/sources.yaml` dodaj wpis (klucz = `source_id`, np. `mojserwis`).
2. **Najpierw zbadaj stronę**: sprawdź `robots.txt`, a w przeglądarce (F12 → Network → Fetch/XHR) poszukaj publicznego API JSON (`/api/`, `_next/data`, `__NEXT_DATA__`, `__NUXT_DATA__`, GraphQL, Algolia). HTML to ostateczność. Znajdź parametry filtrujące auta elektryczne i marki, żeby pobierać jak najmniej stron.
3. Zapisz realną odpowiedź do `tests/fixtures/mojserwis/listing_page.(html|json)` — **nie wymyślaj selektorów**.
4. Utwórz `src/evradar/scrapers/mojserwis.py` z klasą `MojserwisScraper(BaseScraper)`: czysta funkcja `parse…()` (HTML/JSON → `RawListing`, bez sieci) oraz `fetch()`, które pobiera strony metodami `get_text` / `get_json` / `post_json` (robots.txt, opóźnienia i retry są wbudowane). W docstringu modułu opisz źródło danych, użyte parametry URL i to, czy ceny są netto czy brutto. Adapter wykrywany jest automatycznie po nazwie pliku.
5. Napisz `tests/test_mojserwis.py` (offline; ≥ 3 oferty: cena, rok, przebieg, URL, tytuł). Wzór: `src/evradar/scrapers/vwfs.py` i `tests/test_vwfs.py`.
6. Sprawdź na żywo: `uv run evradar run --source mojserwis --dry-run --no-open`.
7. `uv run pytest && uv run ruff check . && uv run mypy`.

W VS Code z Copilotem możesz użyć gotowego promptu `/add-source` (plik `.github/prompts/add-source.prompt.md`).

Jeśli serwisu nie da się pobrać bez omijania zabezpieczeń (CAPTCHA, antybot, zakaz w `robots.txt`) — ustaw `enabled: false` z `reason` i idź dalej.

## Co zrobić, gdy strona zmieni wygląd

Objawy: w raporcie kafelek źródła ma status **DO AKTUALIZACJI** (parser zwrócił 0 ogłoszeń, a wcześniej zwracał >0) albo **BŁĄD**. Oferty tego źródła nie są wtedy oznaczane jako „zniknęły” (awaria ≠ zniknięcie).

1. Otwórz zapisany podgląd w `debug\<źródło>-<data>.html` (to ostatnia pobrana treść).
2. Pobierz świeżą odpowiedź (przeglądarka → Network lub `uv run evradar run --source X -v`) i porównaj ze starą w `tests\fixtures\X\`.
3. Podmień fixture na nowy, popraw funkcję `parse…()` w `src/evradar/scrapers/X.py`, uruchom `uv run pytest tests/test_X.py`.
4. Sprawdź na żywo: `uv run evradar run --source X --dry-run`.

Typowe przyczyny: zmieniona nazwa parametru filtra, nowy format JSON, rotacja klucza API (Stellantis: odśwież `algolia_api_key` z `/content/stellantis-and-you/website/pl/pl.sandy-const.json`), nowy `buildId` Next.js (VWFS używa `__NEXT_DATA__` z samej strony, więc nie zależy od `buildId`).

## Zasady scrapowania

Respektujemy `robots.txt` (łącznie z regułami z `*`/`$`), mamy opóźnienie 1–3 s między żądaniami, maks. 2 równoległe żądania na źródło, retry z exponential backoff (3 próby) i timeout 30 s. Nie omijamy CAPTCHA ani zabezpieczeń antybotowych i nie logujemy się na konta. Awaria jednego źródła nie przerywa skanu.

## Dla programistów

```powershell
uv run pytest            # testy offline (fixture'y w tests\fixtures\)
uv run ruff check .      # lint
uv run mypy              # typy (strict)
```

Struktura: `src/evradar/` — `models.py`, `matching.py` (normalizacja, dopasowanie, `is_electric()`), `storage.py` (SQLite), `diff.py` (NEW / PRICE_DROP / PRICE_UP / GONE / BACK), `runner.py` (orkiestracja, wykrywanie zmian selektorów), `report.py` + `templates/report.html.j2`, `cli.py`, `scrapers/`.
