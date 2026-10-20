# AGENTS.md — EVRadar

> Dokument dla agentów AI i nowych osób w projekcie. Stan na **20.10.2026, po dodaniu 4 źródeł
> (Arval, EFL, Car Arena, Dawro)**.
> Wszystkie liczby i ścieżki w tym pliku zostały zweryfikowane w kodzie i bazie, nie przepisane z README
> (README w kilku miejscach jest nieaktualny — patrz sekcja 8).

## 1. Czym jest ten projekt

EV Radar to agregator ofert **leasingowych i poleasingowych aut elektrycznych** z 13 polskich serwisów
(Otomoto, Autoplac, FindCar, mAuto, Automarket, VW Financial Services, Ayvens, Stellantis &You,
Poleasingowe.pl, Arval AutoSelect, Aukcje EFL, Car Arena, Dawro). Codziennie pobiera oferty, dopasowuje
je do wąskiej listy śledzonych modeli, porównuje
wynik z poprzednim skanem i generuje **jeden samodzielny plik HTML** z raportem. Powstał dla jednej osoby
szukającej EV w budżecie ~80–145 tys. zł, żeby nie przeklikiwać ręcznie trzynastu portali i nie przegapić
obniżek.

**Status: MVP w codziennym użyciu, nie produkt.** Skan i publikację uruchamia się ręcznie
(`./publish_report.sh --scan`); zadanie launchd (12:00) jest zainstalowane, ale **blokuje je TCC macOS**
(patrz sekcja 7). W bazie jest 25 przebiegów i 232 aktywne oferty, testy: 205. Brak serwera, kont
użytkowników i jakiejkolwiek wielodostępności — baza `data/evradar.db` jest lokalna dla komputera i nie
podlega synchronizacji.

## 2. Stos technologiczny

| Technologia | Wersja | Dlaczego |
|---|---|---|
| Python | 3.12.15 (`requires-python = ">=3.12"`) | `StrEnum` i `datetime.UTC`; 3.12 jest w `uv` bez instalowania ręcznego |
| uv | 0.13.0 | Jeden menedżer: pobiera Pythona, tworzy `.venv`, lockuje zależności (`uv.lock`, CI używa `--frozen`) |
| httpx | 0.28.1 | Async HTTP z timeoutami i retry — 90% źródeł to SSR/API JSON, przeglądarka niepotrzebna |
| selectolax | 0.4.13 | Najszybszy parser HTML dla Pythona; używamy CSS-selektorów na wąskich fragmentach |
| pydantic | 2.13.5 | Modele danych (`RawListing`, `Offer`, konfiguracja) z walidacją i `.model_copy()` w testach |
| Jinja2 | 3.1.6 | Szablon raportu (`templates/report.html.j2`) renderowany do jednego pliku bez zależności |
| structlog | 26.1.0 | Logi strukturalne (klucz=wartość) — trafiają do `out/publish.log` i służą do diagnostyki źródeł |
| typer + rich | 0.27.2 / 13.x | CLI z podpowiedziami i tabele wyników w terminalu |
| rapidfuzz | 3.14.6 | Rozmyte dopasowanie nazw modeli (`ID3` = `ID.3`, ale `ID.3` ≠ `ID.4`) |
| PyYAML + tzdata | 6.x / 2026.4 | Cała konfiguracja w YAML; `Europe/Warsaw` w raporcie |
| SQLite (`sqlite3`, stdlib) | — | **Bez ORM** — schemat jest mały (6 tabel), a plik bazy łatwo kopiować między maszynami |
| playwright | 1.63.0 | W zależnościach na wypadek stron wymagających przeglądarki — **obecnie żaden adapter go nie używa** |
| pytest + pytest-asyncio | 9.1.1 / ≥0.23 | `asyncio_mode = "auto"`, testy offline na fixture'ach |
| ruff / mypy | 0.16.9 / 2.3.1 | Lint (E,F,I,UP,B,SIM,T20,RUF) i typy w trybie `strict` |

Wersje zależności są zapięte w `uv.lock`; nie zmieniaj ich bez uzgodnienia (patrz sekcja 6).

## 3. Struktura projektu

```text
EVRadar/
├── AGENTS.md                 # ten dokument
├── README.md                 # dokumentacja użytkownika (miejscami nieaktualna — sekcja 8)
├── pyproject.toml            # zależności, skrypt `evradar`, konfiguracja pytest/ruff/mypy
├── uv.lock                   # zapięte wersje wszystkich zależności
├── .python-version           # 3.12 — wersja wybierana przez uv
├── install_schedule.sh       # instaluje/usuwa zadanie launchd (com.evradar.daily)
├── run_daily.sh              # skan z terminala/launchd (macOS); wybiera .venv → .tools/uv → uv z PATH
├── run_daily.bat             # to samo na Windows
├── publish_report.sh         # publikacja out/index.html na gh-pages (+ `--scan` = skan i publikacja)
├── publish_report.ps1        # to samo w PowerShell
├── config/
│   ├── models.yaml           # ŚLEDZONE MODELE + aliasy, filtry (cena/przebieg/rocznik/tekst), WLTP, linki „Alternatywnie"
│   └── sources.yaml          # źródła: URL, opóźnienia, max_pages, priority, parametry (ścieżki modeli, klucze API)
├── src/evradar/
│   ├── cli.py                # polecenia: run | report | sources | health | backup | demo-report
│   ├── runner.py             # orkiestracja: źródła → matching → diff → zapis; izoluje awarie źródeł
│   ├── config.py             # wczytywanie i walidacja YAML (pydantic)
│   ├── models.py             # modele danych: RawListing, Offer, OfferDiff, SourceResult, ReportData
│   ├── matching.py           # normalizacja nazw, dopasowanie do modeli, ocena napędu (is_electric)
│   ├── parsing.py            # parsowanie cen/przebiegu/rocznika/kWh/SOH + VAT 23% (netto ⇄ brutto)
│   ├── diff.py               # NEW / PRICE_DROP / PRICE_UP / GONE / BACK między skanami
│   ├── analysis.py           # deprecjacja (regresja cena ~ wiek i przebieg) oraz czas ekspozycji ofert
│   ├── storage.py            # SQLite: offers, price_history, model_stats, diffs, runs, source_runs
│   ├── health.py             # ocena zdrowia źródła z historii liczby ofert (wykrywanie spadków)
│   ├── report.py             # przygotowanie danych dla szablonu (mediany, wykresy, kafelki źródeł)
│   ├── robots.py             # robots.txt z regułami `*`/`$`; 401/403 traktowane jak zakaz
│   ├── notify.py             # powiadomienia Telegram (nowe oferty, awarie źródeł)
│   ├── demo.py               # dane syntetyczne do `evradar demo-report`
│   ├── templates/report.html.j2  # cały raport: HTML + CSS + JS (filtry, suwaki, ★/✕ w localStorage)
│   └── scrapers/
│       ├── __init__.py       # auto-discovery: `evradar.scrapers.<source_id>` → podklasa BaseScraper
│       ├── base.py           # wspólna warstwa sieciowa: robots, opóźnienia, semafor, retry, timeout
│       ├── vwfs.py           # REFERENCYJNY adapter — wzór dla nowych źródeł
│       ├── ayvens.py         # usedcars.ayvens.com (Salesforce Commerce Cloud, HTML SSR)
│       ├── mauto.py          # publiczne API JSON (mLeasing/mBank), paginacja po `Count` z API
│       ├── automarket.py     # automarket.pl (PKO Leasing), Nuxt 3 `__NUXT_DATA__`
│       ├── stellantis.py     # publiczny indeks Algolia serwowany przez stronę
│       ├── poleasingowe.py   # aukcje ECR — HTML SSR (uwaga: twardy limit 20 pozycji na stronę)
│       ├── otomoto.py        # Next.js SSR → `advertSearch`; per model, wycina „Uszkodzony: Tak"
│       ├── autoplac.py       # Angular SSR `ng-state`; per model (`?p=N`)
│       ├── findcar.py        # Angular SSR `ng-state` → TanStack Query; per marka
│       ├── arval.py          # Arval AutoSelect — publiczne API JSON (energies=Electric), tylko sprzedaż
│       ├── efl.py            # Aukcje EFL — HTML SSR, parametry z pagera (fc=10), limit 8/stronę, ceny netto
│       ├── cararena.py       # Car Arena (Santander Leasing) — HTML SSR, ?field-fuel=electric, bez widgetu
│       ├── dawro.py          # Dawro (Santander Consumer Multirent) — HTML SSR, brak paliwa → napęd z tytułu
│       ├── ngstate.py        # pomocnik: parsowanie `<script id="ng-state">`
│       └── nuxt.py           # dekoder formatu `devalue` z `__NUXT_DATA__` (Nuxt 3)
├── tests/                    # 29 plików testów, 205 testów, wszystkie offline
│   ├── fixtures/<źródło>/    # realne, przycięte odpowiedzi serwisów (13 katalogów) — selektorów nie wymyślamy
│   └── test_*.py             # parser + przypadki brzegowe per źródło, plus testy runnera, diffów, raportu
├── data/
│   ├── evradar.db            # baza stanu (NIE w repo, .gitignore)
│   └── backups/              # kopie z ostatnich dni (rotacja 14, tworzone po każdym skanie)
├── out/                      # artefakty: index.html (raport), publish.log, _proof.png, demo/
├── docs/report.png           # zrzut raportu do README
├── debug/                    # zrzuty HTML przy awarii parsera (tworzone doraźnie, .gitignore)
├── .github/
│   ├── workflows/ci.yml      # ruff + mypy + pytest przy każdym pushu
│   ├── workflows/daily.yml   # ręczny skan na GitHub Actions (tylko artefakt, bez publikacji)
│   ├── copilot-instructions.md  # zwięzłe konwencje dla Copilota
│   ├── agents/*.agent.md     # role pomocnicze (qa-runner, report-designer, scraper-builder)
│   └── prompts/add-source.prompt.md  # prompt `/add-source` do dodawania nowego źródła
├── .tools/                   # lokalne uv + Python (macOS, .gitignore)
└── .venv/                    # środowisko projektu (.gitignore)
```

## 4. Architektura i kluczowe decyzje

### Przepływ danych

```text
config/sources.yaml ─┐
config/models.yaml ──┴─→ runner.run_scan()
                          ├─ per źródło (równolegle, z opóźnieniami): scrapers/<id>.py → list[RawListing]
                          ├─ build_offers(): matching (model z `targets` + is_electric) → filtry → Offer
                          ├─ dedupe_across_sources(): VIN, a bez VIN (model, rocznik, przebieg, cena)
                          ├─ storage: zapis ofert, historii cen, diffs, source_runs
                          └─ report.py + templates/report.html.j2 → out/index.html → publish_report.sh → gh-pages
```

### Decyzje i odrzucone alternatywy

1. **Skan działa lokalnie, nie w chmurze.** VWFS i Otomoto zwracają 403 na `robots.txt`/stronach z adresów
   IP centrów danych (zmierzone: Cloudflare, GitHub Actions). Projekt traktuje to jak zakaz i **nie obchodzi
   blokad** — dlatego `daily.yml` w GitHub Actions jest tylko ręcznym, opcjonalnym skanem, a raport buduje i
   publikuje maszyna domowa. *Odrzucone: cron w chmurze / worker.*
2. **`launchd`, nie `cron`** (macOS). Cron nie odpala zadań, gdy Mac jest uśpiony; `launchd` z `RunAtLoad`
   nadrabia zaległy skan po wybudzeniu. Wszystkie pory dnia trafiają do jednego zadania (tablica
   `StartCalendarInterval`), żeby nie mnożyć wpisów.
3. **Raport to jeden samodzielny plik HTML** (bez serwera, bez CDN, bez zależności) — otwierasz dwuklikiem,
   a ta sama treść idzie na GitHub Pages. *Odrzucone: aplikacja webowa / API + frontend* — to projekt dla
   jednej osoby, a statyczny plik jest niezniszczalny i działa offline.
4. **SQLite bez ORM.** Schemat jest mały i stabilny, a plik bazy łatwo skopiować na inny komputer.
   *Odrzucone: SQLAlchemy* — narzut bez korzyści przy 6 tabelach.
5. **Publiczne API JSON zamiast HTML, gdzie się da** (mAuto, Automarket, Stellantis/Algolia); HTML tylko
   jako ostateczność. *Odrzucone: Playwright do każdej strony* — jest w zależnościach, ale nieużywany.
6. **Lista modeli w `config/models.yaml` jest jedynym wyznacznikiem zakresu.** Oferta, która nie pasuje do
   żadnego `targets`, jest **całkowicie odrzucana** (nie ma sekcji „inne modele"). To świadoma decyzja o
   jakości raportu, ale ma skutek uboczny: źródła o szerokiej ofercie (Ayvens, Poleasingowe.pl) wnoszą
   bardzo mało — patrz sekcja 8.
7. **Skanowanie po ścieżkach `<marka>/<model>`, nie po całych markach** (Otomoto, Autoplac). Uzasadnienie:
   ścieżki marki zwracają mnóstwo ofert, które i tak odpadną na dopasowaniu. **Pułapka:** nieistniejący slug
   w Otomoto nie zwraca błędu — cicho zwraca całą markę (zweryfikowane: `kia/e-niro` i `hyundai/kona-electric`
   nie istnieją). Dlatego każdą nową ścieżkę trzeba sprawdzić na żywo i udokumentować w `sources.yaml`.
8. **Priorytety źródeł przy deduplikacji:** przy tym samym aucie zostaje źródło o niższym `priority`
   (Otomoto 200 = agregator, Autoplac/FindCar 150, bezpośredni sprzedawcy 100). Uzasadnienie: oferta
   bezpośrednia jest bardziej wiarygodna niż agregat. Pozostałe źródła widać w kolumnie Źródło z linkami.
9. **Deduplikacja dwustopniowa:** najpierw po VIN (podają go Stellantis, Automarket, Ayvens), a bez VIN po
   (model, rocznik, przebieg, cena brutto); dwa różne VIN-y nigdy się nie łączą, a oferty bez rocznika,
   przebiegu lub ceny nigdy nie są łączone (ryzyko fałszywego scalenia). Uwaga: realnie VIN trafia do
   raportu tylko z Automarketu — Stellantis zwraca 0 śledzonych ofert, a Ayvens nie wnosi ofert z VIN.
10. **Ceny zapisujemy dokładnie tak, jak podaje serwis** (osobne pola netto/brutto) i nigdy nie „przeliczamy
    na oko". Brakującą wartość dolicza runner przez VAT 23%. Aukcje (Poleasingowe.pl) są zapisywane jako
    netto i **nigdy** nie przeliczane na brutto w parserze.
11. **Awaria źródła nie generuje „zniknęło".** Jeśli źródło zwróci błąd, jego oferty nie są oznaczane jako
    usunięte — inaczej jeden timeout zamieniłby pół raportu w fałszywe „zniknęły".
12. **Odporność ponad prostotę, gdy dane są cenne:** Otomoto potrafi zwrócić HTTP 200 bez wyników (timeout
    jego własnego GraphQL). Od 13.10.2026 obowiązuje: `ListingUnavailable` + ponowienie strony + **izolacja
    ścieżek** (nieudana ścieżka nie zeruje całego źródła; błąd źródła dopiero, gdy zawiodą wszystkie).
13. **Respektowanie `robots.txt` jest niepodlegające negocjacji:** reguły `*`/`$` obsługiwane ręcznie,
    odpowiedź 401/403 = zakaz, bez omijania CAPTCHA i bez logowania. OLX (403 na `robots.txt`) i Allegro
    (403 na kategoriach) są wykluczone — OLX występuje wyłącznie jako linki w sekcji „Alternatywnie".
14. **Grzeczność sieciowa:** opóźnienie 1–3 s między żądaniami, semafor (2 równoległe na źródło), retry z
    backoffem (3 próby) na 408/429/5xx, timeout 30 s, limit czasu źródła 600 s.
15. **Każdy scraper = fixture + test offline.** Selektorów nie wymyślamy: najpierw realna odpowiedź do
    `tests/fixtures/<źródło>/`, potem parser. Testy nigdy nie wychodzą do sieci.
16. **Powiadomienia Telegram są opcjonalne** (`notifications.enabled: false` domyślnie) i nie wysyłają się w
    trybie `--dry-run`.

## 5. Konfiguracja i uruchomienie

### Wymagane narzędzia

- **Python 3.12+** (w tym repo: 3.12.15 w `.venv`)
- **uv 0.13.0** — na tej maszynie leży w `.tools/bin/uv` i **nie musi być w `PATH`**
  (`run_daily.sh` sam wybiera: `.venv/bin/evradar` → `.tools/bin/uv run` → `uv` z `PATH`)
- System: macOS (główna maszyna) lub Windows; kod jest identyczny, różnią się skrypty uruchomieniowe

### Instalacja (kolejność ma znaczenie)

```bash
cd /Users/marcin/Desktop/ZCODE/EVRadar

# 1. zależności + Python (jeśli nie masz uv: curl -LsSf https://astral.sh/uv/install.sh | sh)
uv sync

# 2. opcjonalnie: przeglądarka dla Playwrighta (żaden adapter jej obecnie nie używa)
uv run playwright install chromium

# 3. jeśli skrypty zgubiły prawo wykonywania (np. po klonie repo)
chmod +x run_daily.sh publish_report.sh install_schedule.sh
```

### Uruchomienie

```bash
# skan wszystkich źródeł + raport (bez otwierania przeglądarki)
.venv/bin/evradar run --no-open        # to samo co: uv run evradar run --no-open

# skrypty powłoki (robią dokładnie to samo, używane przez launchd)
./run_daily.sh                         # skan
./run_daily.sh --source mauto          # tylko wybrane źródła
./run_daily.sh --dry-run               # bez zapisu do bazy

# publikacja na GitHub Pages
./publish_report.sh --scan             # skan + publikacja
./publish_report.sh                    # publikacja ostatnio wygenerowanego raportu

# harmonogram (macOS)
./install_schedule.sh                  # domyślnie 12:00
./install_schedule.sh 7:15 18:00       # dwie pory dnia, format GODZINA:MINUTA
./install_schedule.sh --status
./install_schedule.sh --remove
```

### Polecenia CLI

| Polecenie | Co robi |
|---|---|
| `evradar run` | skan wszystkich źródeł + raport (`--source a,b`, `--dry-run`, `--open/--no-open`, `--verbose`) |
| `evradar report --last` | przegenerowanie raportu z bazy, bez sieci |
| `evradar sources` | lista źródeł i status ostatniego skanu |
| `evradar health` | liczba ofert z ostatnich przebiegów + wykryte spadki |
| `evradar backup` | kopia bazy do `data/backups` (i tak robiona po każdym skanie, rotacja 14) |
| `evradar demo-report` | raport na danych syntetycznych (podgląd wyglądu bez skanu) |

### Zmienne środowiskowe

Projekt **nie ma pliku `.env` ani loadera `.env`** (brak `python-dotenv`) — zmienne trzeba wyeksportować w
powłoce albo w zadaniu launchd. `.env` jest w `.gitignore`, ale samo jego istnienie nic nie da.

| Nazwa | Do czego | Przykład formatu (bez prawdziwych wartości) |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | token bota wysyłającego powiadomienia; czytany tylko gdy `notifications.enabled: true` | `123456789:AAAbCdEfGhIjKlMnOpQrStUvWxYz0123456` |
| `TELEGRAM_CHAT_ID` | identyfikator czatu/ grupy odbiorcy | `-1001234567890` |

Brak tych zmiennych nie przerywa skanu — powiadomienie jest pomijane z ostrzeżeniem w logu.

`config/sources.yaml` zawiera `algolia_api_key` dla Stellantis. To **klucz search-only** serwowany publicznie
przez stronę (nie sekret), ale przy rotacji trzeba go odświeżyć z `pl.sandy-const.json`.

### Adresy

- **Lokalnie nie ma serwera HTTP.** Raport to plik: `out/index.html` (otwierany dwuklikiem, `file://`).
  Jeśli naprawdę potrzebujesz serwera: `python3 -m http.server -d out 8000`.
- **Wersja publiczna:** <https://sigpath.github.io/EVRadar/> (gałąź `gh-pages`).
- **Log ostatniej publikacji:** `out/publish.log`.
- Katalog roboczy na tej maszynie: `/Users/marcin/Desktop/ZCODE/EVRadar` (repo było wcześniej
  w `~/Desktop/Deepseek/EVRadar`; po przenosinach trzeba odtworzyć `.venv` przez `uv sync --reinstall`,
  bo shebangi skryptów w `.venv/bin` wskazują absolutną starą ścieżkę, oraz ponownie zainstalować
  launchd przez `./install_schedule.sh`).

## 6. Konwencje

- **Język:** docstringi, komentarze, komunikaty CLI i commity po polsku. Komunikaty commitów **bez polskich
  znaków diakrytycznych**, z prefiksem obszaru: `Otomoto: ...`, `Poleasingowe: ...`, `Modele: ...`, `Filtr: ...`.
- **Typowanie:** `mypy --strict` na `src` i `tests`; `from __future__ import annotations` w każdym module.
- **Lint:** `ruff` z `line-length = 100` i regułami `E,F,I,UP,B,SIM,T20,RUF`. Reguła `T20` zakazuje
  `print` — w CLI używaj `rich.console`, w kodzie bibliotecznym `structlog`.
- **Nazewnictwo:** `snake_case` (funkcje, moduły, zmienne), `PascalCase` (klasy), `UPPER_SNAKE` (stałe).
- **Scraper = plik = klucz konfiguracji = katalog fixture'ów.** `src/evradar/scrapers/<source_id>.py`
  z klasą `<Source>Scraper(BaseScraper)`; adapter jest wykrywany automatycznie po nazwie pliku.
  Wzór referencyjny: `scrapers/vwfs.py` + `tests/test_vwfs.py`.
- **Nic nie jest zahardkodowane:** modele, filtry, URL-e, opóźnienia i ścieżki modeli żyją w `config/*.yaml`.
- **Ceny:** zawsze zapisuj, czy kwota jest netto czy brutto; brakującą doliczaj wyłącznie przez VAT 23%.
- **Testy:** tylko offline, na fixture'ach z `tests/fixtures/`; selektorów nie wymyślamy — najpierw realna
  odpowiedź serwisu, potem parser.
- **Logowanie:** wyłącznie `structlog` (`log = structlog.get_logger()`), z kluczami w `snake_case`
  (`source_done`, `otomoto_path_failed`).
- **Nowe zależności: tylko po uzgodnieniu.** Zmiana `pyproject.toml` wymaga `uv lock`; CI używa `uv sync --frozen`.
- **Czego nie robić:** nie obchodzić `robots.txt`, CAPTCHA ani blokad antybotowych; nie logować się na konta;
  nie zmieniać `priority` źródeł bez zrozumienia deduplikacji; nie „naprawiać" liczby ofert przez poluzowanie
  filtrów w `models.yaml` (to decyzja produktowa); nie commitować `data/`, `out/`, `debug/`, `.venv/`, `.tools/`.

## 7. Aktualny stan prac

### ✅ Zrobione i działające

- 13 adapterów źródeł z fixture'ami i testami; auto-discovery scraperów.
- Raport HTML: nowe/obniżki/podwyżki/powroty/zniknięcia, „Do weryfikacji", filtry i suwaki, miniatury,
  wykresy ceny, Vs rynek, deprecjacja, trend cen modeli, czas ekspozycji, kafelki zdrowia źródeł,
  grupowanie po VIN, sekcja „Alternatywnie" (OLX).
- Historia w SQLite (6 tabel), diffy, backupy z rotacją 14 dni, ocena zdrowia źródeł, powiadomienia Telegram.
- Automatyzacja: publikacja ręczna `./publish_report.sh --scan` + log `out/publish.log`; zadanie
  `launchd` (12:00) zainstalowane, ale **zablokowane przez TCC** (bash z launchd nie czyta `~/Desktop`) —
  do rozstrzygnięcia: Full Disk Access dla `/bin/bash` albo przeniesienie repo poza Desktop.
- CI: `ruff` + `mypy` + `pytest` (205 testów) przy każdym pushu.
- **Nowe źródła z 20.10.2026 (4 adaptery, 22 testy, wszystkie zweryfikowane skanem `--dry-run` na żywo):**
  - **Arval AutoSelect** (`arval`): publiczne API JSON `portalapi-prod.autoselect.cloud/api/Announcements/17`
    z `energies=Electric` (kod ze słownika `Filters/17`; polska nazwa z URL-a frontu nie działa w API).
    robots frontu zabrania URL-i z parametrami, więc adapter chodzi wyłącznie przez API (host bez robots —
    wzorzec mAuto). **Bug backendu:** `purchaseOption` w żądaniu po cichu kasuje filtr paliwa, dlatego oferty
    najmu (`release`, cena 0) odrzuca adapter. Stan 20.10: **0 EV na sprzedaż** (32 EV = przedłużony najem).
  - **Aukcje EFL** (`efl`): HTML SSR; paginacja działa tylko z parametrami z własnego pagera serwisu
    (`category=12&sort=Title-asc&fc=10&page=N`, numeracja od 0) — kanoniczny `/AuctionList/Pojazdy/Osobowe`
    ignoruje `page`. Twardy limit 8 ofert/stronę (`perPage` ignorowany). Ceny **netto** („Aktualna cena
    (bez VAT)"). Paliwo filtrowane po stronie klienta („Napęd elektryczny" → „Elektryczny").
  - **Car Arena** (`cararena`, Santander Leasing): HTML SSR, `?field-fuel=electric` działa serwerowo;
    kafelki `.offers-item` są też w widgecie „top aukcje" (ignoruje filtr, ma ukryte ceny) — parser bierze
    tylko `#auction_items_list`. Ceny brutto, bez paginacji.
  - **Dawro** (`dawro`, Santander Consumer Multirent): HTML SSR z parametrami w ścieżce
    (`sprzedawca,santander_scm,typ,10,ilosc,100`); strona poza zakresem zwraca stronę 1 (pętla kończy się
    na powtórzonym ID). **Brak paliwa w serwisie** — napęd ocenia matching po tytule. Ceny **brutto**
    (regulamin: „oferta = cena brutto"); zapisujemy najwyższą ofertę, a bez ofert — cenę wywoławczą.
    Pierwszy skan: 19 aukcji → 2 oferty (Tesla Model Y 2023 96 100 zł, Tesla Model 3 LR 2023 95 500 zł).
- **Naprawy z 13.10.2026 (commit `041d712`, `117d7d3`):**
  - Otomoto: odporność na `OptimusTimeoutError [HTTP408]` — `ListingUnavailable`, ponowienie strony,
    izolacja ścieżek (wcześniej jedna nieudana ścieżka zerowała całe źródło); dodana brakująca ścieżka
    `hyundai/ioniq-6`, usunięte 4 martwe ścieżki; `max_pages: 8`.
  - Poleasingowe.pl: naprawiona paginacja (serwis ignoruje `list_pagesize` > 20, a próg „pełnej strony"
    był ustawiony na 50 → zbieraliśmy tylko 20 z 40 aukcji); dodany filtr osobowy
    `procsubcat=ecr_cartypess` (bez busów). Efekt: 20 → 30 aukcji na skan.
- **Porządki z wieczoru 13.10.2026 (po audycie lejka wszystkich 9 źródeł):**
  - Odtworzone środowisko po przenosinach repo (`uv sync --frozen --reinstall` — przenosiny psują
    shebangi `.venv/bin/*`) i ponownie zainstalowany launchd (`./install_schedule.sh`, 12:00).
    **Wykryte przy okazji:** launchd jest blokowany przez TCC macOS (bash uruchomiony przez launchd
    nie ma dostępu do `~/Desktop` — „Operation not permitted"; `out/launchd.err.log`), a godziny
    przebiegów w bazie (klastry typu 12:01–12:19, nigdy pojedynczy run o 12:00) wskazują, że
    **automatyzacja nigdy nie wykonała skanu** — wszystkie 25 przebiegów było ręcznych. Wymagana
    decyzja właściciela: Full Disk Access dla `/bin/bash` albo przeniesienie repo poza `~/Desktop`.
  - Autoplac: izolacja ścieżek na wzór Otomoto (`autoplac_path_failed`; błąd źródła dopiero, gdy
    zawiodą wszystkie) + porządek ścieżek w `sources.yaml`: usunięte `kia/ev3`, `kia/ev4`,
    `volkswagen/id3`, `skoda/enyaq`, dodany zweryfikowany `hyundai/ioniq-6` (model `257_2893`,
    22 oferty). `tesla/model-y` zweryfikowany jako poprawny (`555_5285`, to samo co `tesla/y`).
  - `BaseScraper`: retry honoruje nagłówek `Retry-After` (format sekundowy), `assert` zamieniony
    na jawny wyjątek.
  - README odświeżony (lista modeli, przykład progów cen, liczba testów, ścieżki Windows),
    skasowane artefakty `debug/`, `out/_proof.png`, `out/demo/`.
- Ostatni przebieg: **25** (`2026-10-13 19:13 UTC`), 232 aktywne oferty, 57,8 s.
- Opublikowany raport: stopka `13.10.2026 21:13`, gh-pages `0588978`.

### 🚧 W trakcie (dokładne miejsce przerwania)

- Zmiany wieczorne (Autoplac, `Retry-After`, README, AGENTS.md) są zacommitowane i wypchnięte na
  `origin/main` — sprawdź w GitHub Actions, czy CI przeszło zielono.
- Otwarta decyzja produktowa: użytkownik **świadomie nie dodał** nowych modeli do `models.yaml`
  (Mercedes EQA/EQB, EQE/EQS, Fiat 500e, Korando e-Motion, Subaru Solterra, Tesla Model X, Toyota Mirai),
  mimo że dane z Poleasingowe.pl są już pobierane. Bez tej decyzji raport pokazuje z tego źródła 1 ofertę.

### 📋 Do zrobienia (w kolejności)

1. **Odblokować automatyzację (decyzja właściciela):** nadać `/bin/bash` Full Disk Access w
   Ustawieniach systemowych (Prywatność i ochrona) albo przenieść repo poza `~/Desktop`
   (np. `~/Projects/EVRadar` — wtedy wystarczy `uv sync --frozen --reinstall` +
   `./install_schedule.sh` w nowej lokalizacji). Do tego czasu skan uruchamiać ręcznie.
2. **Decyzja o zakresie modeli** — patrz sekcja 9, pkt 1 (dane z audytu lejka są w sekcji 8).
3. Rozważyć wyłączenie Stellantis (`enabled: false`) — przy obecnej liście modeli źródło nie może
   wnosić ofert (0 śledzonych marek w inwentarzu).
4. Rozważyć usunięcie nieużywanego Playwrighta z zależności (oszczędza ~50 MB i krok instalacji).
5. Rozważyć `max_pages` dla Poleasingowe.pl (domyślne 5 stron × 20 = 100 aukcji zapasu).

## 8. Znane problemy i ograniczenia

**Zbieranie danych (audyt lejka wszystkich 9 źródeł, 13.10.2026 wieczór — surowe → dopasowane → filtry):**

- **Arval: 0 śledzonych ofert — strukturalnie, nie błąd adaptera.** Cała flota EV (32 szt.: Model Y×7,
  Model 3×6, EQC×3, EV6×2, Enyaq×2, Mach-e×2, Leaf×2, Zoe, ID.4, Q4 e-tron, Megane, Kangoo, i3, Mini)
  jest wystawiona wyłącznie jako **przedłużony najem** (`purchaseOption=release`, `salePrice=0`),
  a filtr „tylko sprzedaż" w API nie działa (bug parametrów). Adapter wróci oferty, gdy Arval wystawi
  EV na sprzedaż — to kwestia czasu, flota EV jest duża.
- **Dawro: brak danych o paliwie w całym serwisie** — oferty śledzonych marek spalinowych (np. Niro
  hybrydowe) trafiłyby do „Do weryfikacji" zamiast zostać odrzucone; obecnie przechodzą tylko tytuły
  jednoznacznie elektryczne (Tesla) lub z „elektryczn*" w nazwie.

- **Stellantis: ~202 surowe → 0 ofert i nie może być inaczej.** Parser działa poprawnie (marka/model
  z Algolii są poprawne), ale cały inwentarz to marki Grupy Stellantis (Peugeot 2008/308/5008,
  Citroën, Opel, DS, Jeep, 1× Leapmotor C10) — ani jednej śledzonej marki. Podejrzenie błędnego
  mapowania pól Algolii było fałszywe. Opcja: `enabled: false` do czasu ewentualnego dodania
  EV-ów Stellantisa (e-2008, e-Mokka, C4 Electric) do `targets`.
- **Ayvens: ~431 surowe → 1 oferta.** Parser poprawny; to zwroty floty leasingowej w ~99% spalinowej
  (Corolla×50, Passat×26, Golf×22, Octavia×16…). Śledzone modele w całym inwentarzu: 2× Tesla,
  z czego 1 odrzucona progiem przebiegu. Strukturalnie źródło wniesie ~1 ofertę.
- **FindCar: ~132 surowe → 1 oferta.** Dopasowuje się 9 ofert (Ioniq 6×4, Ioniq 5×3, Kona×1, ID.4×1),
  ale 8 z nich odpada progiem ceny 145 tys. zł. Poza targets: ID.3 Neo×38, ID.7×24, ID. Polo×19,
  Inster×14, ID.CROSS×9, ID. Buzz×11, EV3×2, EV4×2 — czyli to praktycznie dealer rodziny VW ID.
- **Poleasingowe.pl: 30 aukcji, `models.yaml` przepuszcza 1.** Odrzucane: Mercedes EQE/EQS/EQA/EQB
  (~17), Fiat 500, Korando e-Motion, Subaru Solterra, Tesla Model X, Toyota Mirai. Parser nie ustawia
  pola `brand` (matching po tytule) — działa, ale to najsłabsze ogniwo dopasowania tego źródła.
- **Progi cenowe odcinają łącznie ~168 ofert na skan** (145 tys. zł: ~103, w tym mAuto 21 i Autoplac 62;
  80 tys. zł: ~65). To statystycznie najczęstszy powód odrzucenia — każda zmiana progów to decyzja
  właściciela produktu, ale jej wpływ jest policzalny.
- **VWFS: 43 surowe → 3 oferty.** 37 poza targets, w tym Audi Q4 e-tron×16 (największa pojedyncza
  niewykorzystana pula ofert ze wszystkich źródeł), ID.3×6, Enyaq×4, Cupra Born×3.
- **Otomoto wycina ~26% ogłoszeń** jako „Uszkodzony: Tak" (47 z ~223 w pomiarze). Świadome, wyłączalne
  przez `exclude_damaged: false`. Ścieżki Otomoto są idealnie zsynchronizowane z `models.yaml`
  (176/176 surowych ogłoszeń dopasowanych w audycie).
- **Otomoto potrafi zwrócić HTTP 200 bez wyników** (timeout jego GraphQL, ~1 raz na kilkanaście przebiegów).
  Obsłużone, ale przy trwałej zmianie struktury źródło zgłosi błąd po wyczerpaniu ponowień.

**Dokumentacja i spójność:**

- **Brak loadera `.env`** — `python-dotenv` nie jest zależnością, więc plik `.env` sam z siebie nic nie zrobi.

**Architektura / dług techniczny:**

- **Playwright (1.63.0) jest w zależnościach, ale nieużywany** — `headless` jest przekazywany do scraperów,
  lecz żaden adapter nie otwiera przeglądarki.
- **Baza jest lokalna i niesynchronizowana.** Skan z drugiego komputera startuje z pustą bazą: wszystko
  pokaże się jako „nowe", nic jako „zniknięło". Zalecenie: skanować z jednej maszyny.
- **Oferty spoza `targets` są bezpowrotnie odrzucane** — nie ma sekcji „inne modele" ani trybu szerokiego.
- **`max_pages: 8` dla Otomoto** to zapas — przy zweryfikowanych ścieżkach modele mieszczą się w ≤4 stronach.

**Raport w przeglądarce (może wyglądać jak błąd, choć nim nie jest):**

- Przyciski **★/✕ zapisują się w `localStorage`** (`evradar:marks`) i **przywracają po odświeżeniu** — jeśli
  oferty z jakiegoś źródła wyglądają na brakujące, sprawdź „Pokaż ukryte" albo wyczyść klucz.
- **GitHub Pages cache'uje raport 1–3 minuty** po pushu; baner „starszy niż 36 h" pojawia się przy
  niedziałającym zadaniu dziennym.
- Baner „⚠ Problem ze źródłami" **nie oznacza**, że źródło nie działa — oferty takiego źródła pochodzą
  z poprzedniego skanu (dokładnie to zdarzyło się 13.10.2026 o 20:17, gdy Otomoto miało timeout).

## 9. Następne kroki

Priorytety od najwyższego:

1. **Odblokować automatyzację launchd (decyzja właściciela):** Full Disk Access dla `/bin/bash`
   albo przeniesienie repo poza `~/Desktop` (sekcja 7). Do tego czasu skanować ręcznie.
2. **Decyzja o zakresie modeli** (`models.yaml`) — jedyna realna dźwignia na liczbę ofert w raporcie;
   dane z audytu lejka (sekcja 8) mówią, co konkretnie zyska każda opcja: Audi Q4 e-tron ×16 (VWFS),
   EQA/EQB (+2 z Poleasingowe), ewentualnie ID.7/Inster/ID.3 Neo z FindCar (dziesiątki ofert,
   ale poszerzenie zakresu o nowego gracza). To decyzja właściciela produktu — **nie zmieniaj progów
   ani listy modeli bez pytania**. Analogicznie próg 145 tys. zł odcina ~103 dopasowane oferty na skan.
3. **Wyłączenie Stellantis?** Zero śledzonych marek w inwentarzu (sekcja 8) — `enabled: false`
   oszczędza żądania; decyzja właściciela.
4. **Drobne porządki:** usunąć Playwrighta z zależności (jeśli nie planujesz adaptera na stronie
   dynamicznej), dopisać `max_pages` dla Poleasingowe.pl (domyślne 5 stron × 20 = 100 aukcji zapasu),
   rozważyć uzupełnienie `brand` w parserze Poleasingowe (dziś matching po samym tytule).

**Zasada dla agenta przejmującego pracę:** najpierw uruchom `uv run pytest` i `uv run evradar health`,
potem sprawdź `git status -sb` (czy `main` nie jest przed `origin`) — ten projekt rozwija się małymi
commitami, a najczęstszym źródłem „dziwnych" liczb w raporcie jest lista modeli i filtry w
`config/models.yaml`, nie kod scraperów.
