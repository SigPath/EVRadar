#!/usr/bin/env bash
#
# Skan dzienny dla macOS: uruchomienie z terminala albo z launchd.
# Odpowiednik run_daily.bat z Windows.
#
# Użycie:
#   ./run_daily.sh                 # skan wszystkich źródeł + raport
#   ./run_daily.sh --source mauto  # tylko wybrane źródła
#   ./run_daily.sh --dry-run       # bez zapisu do bazy
#
# Wszystkie argumenty są przekazywane wprost do `evradar run`.

set -uo pipefail

# Katalog, w którym leży ten skrypt — działa niezależnie od tego, skąd go wywołasz.
cd "$(dirname "$0")" || exit 1

# --- Wybór interpretera: venv -> lokalne uv -> uv z PATH ---------------------
if [ -x ".venv/bin/evradar" ]; then
    EVRADAR=".venv/bin/evradar"
    RUN=("$EVRADAR")
elif [ -x ".tools/bin/uv" ]; then
    RUN=(".tools/bin/uv" "run" "evradar")
elif command -v uv >/dev/null 2>&1; then
    RUN=("uv" "run" "evradar")
else
    echo "BŁĄD: nie znalazłem ani .venv/bin/evradar, ani uv." >&2
    echo "Uruchom najpierw: uv sync" >&2
    exit 1
fi

echo "== EV Radar: skan $(date '+%Y-%m-%d %H:%M:%S') =="
"${RUN[@]}" run --no-open "$@"
STATUS=$?

if [ $STATUS -ne 0 ]; then
    echo
    echo "Skan zakończył się błędem (kod $STATUS). Sprawdź komunikaty powyżej." >&2
fi
exit $STATUS
