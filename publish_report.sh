#!/usr/bin/env bash
#
# Publikuje out/index.html na gałąź gh-pages (GitHub Pages).
# Odpowiednik publish_report.ps1 z Windows — ta sama logika, ten sam efekt.
#
# Użycie:
#   ./publish_report.sh          # publikuje ostatnio wygenerowany raport
#   ./publish_report.sh --scan   # najpierw skan, potem publikacja
#
# Kluczowa własność: gh-pages jest aktualizowana tylko wtedy, gdy raport faktycznie
# się zmienił. Dzięki temu codzienne zadanie nie zaśmieca historii commita, gdy
# nic się nie zmieniło.

set -uo pipefail

cd "$(dirname "$0")" || exit 1

DO_SCAN=0
for arg in "$@"; do
    case "$arg" in
        --scan) DO_SCAN=1 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Nieznany argument: $arg (użyj --scan albo --help)" >&2
            exit 2
            ;;
    esac
done

REPO_DIR="$(pwd)"
mkdir -p out
LOG="out/publish.log"

# Log z przebiegu — przydatny, gdy zadanie z launchd/cron kończy się bez publikacji.
# Celowo `>>` zamiast `tee` z podstawieniem procesu: `exec > >(tee ...)` bywa
# blokowane w środowiskach o ograniczonym dostępie do deskryptorów (/dev/fd).
# Komunikat o logu musi trafić na konsolę PRZED przekierowaniem.
echo "Log: $LOG"
exec >>"$LOG" 2>&1

echo "== EV Radar: publikacja $(date '+%Y-%m-%d %H:%M:%S') =="

# --- 1. Opcjonalny skan ------------------------------------------------------
if [ "$DO_SCAN" -eq 1 ]; then
    ./run_daily.sh
    if [ $? -ne 0 ]; then
        echo "BŁĄD: skan zakończył się błędem — przerywam publikację." >&2
        exit 1
    fi
fi

# --- 2. Czy jest co publikować ----------------------------------------------
REPORT="$REPO_DIR/out/index.html"
if [ ! -f "$REPORT" ]; then
    echo "BŁĄD: brak out/index.html — uruchom najpierw skan (./publish_report.sh --scan)." >&2
    exit 1
fi

REMOTE="$(git remote get-url origin)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/evradar-pages.XXXXXX")"
# Sprzątanie katalogu tymczasowego niezależnie od wyniku.
trap 'rm -rf "$TMP"' EXIT

# --- 3. Klon (albo inicjalizacja) gałęzi gh-pages ---------------------------
if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
    git clone --quiet --branch gh-pages --single-branch --depth 1 "$REMOTE" "$TMP" || exit 1
else
    echo "Gałąź gh-pages nie istnieje — tworzę ją."
    git init --quiet "$TMP" || exit 1
    git -C "$TMP" checkout --quiet -b gh-pages || exit 1
    git -C "$TMP" remote add origin "$REMOTE" || exit 1
fi

# --- 4. Podmiana raportu ----------------------------------------------------
cp "$REPORT" "$TMP/index.html" || exit 1
# .nojekyll wyłącza przetwarzanie przez Jekyll (szybsze Pages, brak niespodzianek).
: > "$TMP/.nojekyll"

git -C "$TMP" add -A || exit 1

# --- 5. Publikuj tylko, gdy jest realna zmiana ------------------------------
if git -C "$TMP" diff --cached --quiet; then
    echo "Raport bez zmian — nic do publikacji."
    exit 0
fi

# Tożsamość: klon tymczasowy ma WŁASNĄ konfigurację git, więc nie dziedziczy
# ustawień z repo (`git config user.email` w repo nic tu nie da). Odczytujemy
# tożsamość z repo i przekazujemy ją jawnie do commita przez `git -c`.
IDENT_NAME="$(git config user.name 2>/dev/null || true)"
IDENT_EMAIL="$(git config user.email 2>/dev/null || true)"
if [ -z "$IDENT_EMAIL" ]; then
    IDENT_NAME="EV Radar"
    IDENT_EMAIL="evradar@localhost"
    echo "Uwaga: brak user.email w konfiguracji git — commit pójdzie jako $IDENT_EMAIL."
    echo "         Ustaw go raz: git config --global user.email 'twoj@email'"
fi

git -C "$TMP" -c user.name="$IDENT_NAME" -c user.email="$IDENT_EMAIL" \
    commit --quiet -m "Raport $(date '+%Y-%m-%d %H:%M')" || exit 1
echo "Commit jako: $IDENT_NAME <$IDENT_EMAIL>"

git -C "$TMP" push --quiet origin gh-pages || {
    echo "BŁĄD: nie udało się wypchnąć na gh-pages." >&2
    echo "Sprawdź dostęp do repozytorium (git push origin gh-pages ręcznie)." >&2
    exit 1
}

echo "Opublikowano na gałąź gh-pages."
echo "Raport: https://sigpath.github.io/EVRadar/"
