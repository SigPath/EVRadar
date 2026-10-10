#!/usr/bin/env bash
#
# Instaluje codzienne zadanie EV Radar w launchd (natywny harmonogram macOS).
# Odpowiednik rejestracji zadania w Harmonogramie zadań Windows.
#
# Użycie:
#   ./install_schedule.sh                      # domyślnie 12:00 i 18:00
#   ./install_schedule.sh 12:00 18:00          # o 12:00 i 18:00  ← ZALECANY format
#   ./install_schedule.sh 7:15 12:00 18:30     # o 07:15, 12:00 i 18:30
#   ./install_schedule.sh 9                    # o 09:00 (sama godzina)
#   ./install_schedule.sh 12 18 21             # o 12:00, 18:00, 21:00 (nieparzysta liczba = same godziny)
#   ./install_schedule.sh 8 30 12 0            # tryb zgodności: pary godzina/minuta
#   ./install_schedule.sh --remove             # usuwa zadanie
#   ./install_schedule.sh --status             # stan zadania + ostatnie wpisy z logu
#   ./install_schedule.sh --help
#
# Zalecany jest format GODZINA:MINUTA, bo jest jednoznaczny. Zapis "12 18" jest
# dwuznaczny (dwie godziny czy godzina 12 i minuta 18?) — dlatego go nie używamy.
#
# Wszystkie pory trafiają do JEDNEGO zadania launchd (tablica StartCalendarInterval),
# więc nie powstają osobne zadania do zarządzania.
#
# Dlaczego launchd, a nie cron: launchd działa też po wybudzeniu MacBooka ze snu
# (cron w tym czasie po prostu nie odpala). Ma też `RunAtLoad`, dzięki któremu
# zaległy skan wykona się po włączeniu komputera.

set -uo pipefail

cd "$(dirname "$0")" || exit 1
PROJECT_DIR="$(pwd)"
LABEL="com.evradar.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

# --- Tryby specjalne ---------------------------------------------------------
case "${1:-}" in
    --remove)
        launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
        rm -f "$PLIST"
        echo "Zadanie '$LABEL' usunięte."
        exit 0
        ;;
    --status)
        echo "== Stan zadania $LABEL =="
        if [ -f "$PLIST" ]; then
            echo "Plik: $PLIST"
            echo
            echo "Zaplanowane pory:"
            /usr/libexec/PlistBuddy -c "Print :StartCalendarInterval" "$PLIST" 2>/dev/null \
                | grep -E 'Hour|Minute' | sed 's/^/    /' || echo "    (nie udało się odczytać)"
        else
            echo "Plik: $PLIST (BRAK — zadanie niezainstalowane)"
        fi
        echo
        launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E 'state|last exit|runs' \
            | sed 's/^/  /' || echo "  Zadanie nie jest załadowane do launchd."
        if [ -f out/publish.log ]; then
            echo
            echo "== Ostatnie 10 linii out/publish.log =="
            tail -10 out/publish.log | sed 's/^/  /'
        fi
        exit 0
        ;;
    -h|--help)
        sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
esac

# --- Parsowanie argumentów ---------------------------------------------------
# ZALECANY format: GODZINA:MINUTA, po jednym argumencie na porę dnia.
#   ./install_schedule.sh 12:00 18:00        -> 12:00 i 18:00
#   ./install_schedule.sh 7:15 12:00 18:30   -> trzy pory
#
# Dlaczego nie "12 18": to jest niejednoznaczne — nie da się odróżnić
# "dwie godziny (12:00, 18:00)" od "godzina 12, minuta 18". Format z dwukropkiem
# usuwa tę dwuznaczność, więc nie trzeba zgadywać intencji.
#
# Skróty (zachowane dla wygody):
#   ./install_schedule.sh                    -> 12:00 i 18:00 (domyślnie)
#   ./install_schedule.sh 9                  -> 09:00
#   ./install_schedule.sh 8 30 12 0          -> 08:30 i 12:00 (pary, tryb zgodności)
if [ "$#" -eq 0 ]; then
    set -- 12:00 18:00
fi

SCHEDULE_BLOCK="    <key>StartCalendarInterval</key>
    <array>"
SUMMARY=""

add_time() {
    H="$1"; M="$2"
    case "$H" in ''|*[!0-9]*) echo "BŁĄD: godzina '$H' nie jest liczbą." >&2; exit 2 ;; esac
    case "$M" in ''|*[!0-9]*) echo "BŁĄD: minuta '$M' nie jest liczbą." >&2; exit 2 ;; esac
    if [ "$H" -gt 23 ] || [ "$M" -gt 59 ]; then
        echo "BŁĄD: '$H:$M' poza zakresem (godzina 0-23, minuta 0-59)." >&2
        exit 2
    fi
    SCHEDULE_BLOCK="$SCHEDULE_BLOCK
        <dict>
            <key>Hour</key><integer>$H</integer>
            <key>Minute</key><integer>$M</integer>
        </dict>"
    if [ -z "$SUMMARY" ]; then
        SUMMARY="$(printf '%02d:%02d' "$H" "$M")"
    else
        SUMMARY="$SUMMARY, $(printf '%02d:%02d' "$H" "$M")"
    fi
}

# Czy użyto formatu z dwukropkiem?
HAS_COLON=0
for a in "$@"; do
    case "$a" in *:*) HAS_COLON=1 ;; esac
done

if [ "$HAS_COLON" -eq 1 ]; then
    # Format GODZINA:MINUTA — po jednym argumencie na porę.
    for a in "$@"; do
        case "$a" in
            *:*) H="${a%%:*}"; M="${a#*:}" ;;
            *)
                if [ "$#" -eq 1 ]; then
                    H="$a"; M=0
                else
                    echo "BŁĄD: '$a' nie ma formatu GODZINA:MINUTA." >&2
                    echo "      Nie mieszaj formatów, np. użyj: $0 8:30 12:00" >&2
                    exit 2
                fi
                ;;
        esac
        add_time "$H" "$M"
    done
elif [ "$#" -eq 1 ]; then
    # Pojedyncza liczba = godzina, minuta 0.
    add_time "$1" 0
elif [ $(( $# % 2 )) -eq 0 ]; then
    # Tryb zgodności: pary godzina/minuta.
    while [ "$#" -gt 0 ]; do
        add_time "$1" "$2"
        shift 2
    done
else
    # Nieparzysta liczba bez dwukropków: potraktuj każdy jako godzinę.
    # To pozwala na "./install_schedule.sh 12 18 21" = 12:00, 18:00, 21:00.
    for H in "$@"; do
        add_time "$H" 0
    done
fi

SCHEDULE_BLOCK="$SCHEDULE_BLOCK
    </array>"

if [ ! -x "./publish_report.sh" ]; then
    echo "BŁĄD: brak ./publish_report.sh albo nie jest wykonywalny." >&2
    echo "Uruchom: chmod +x publish_report.sh run_daily.sh install_schedule.sh" >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" out

# Ścieżki bezwzględne są wymagane przez launchd — nie ma tu pojęcia katalogu roboczego.
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/publish_report.sh</string>
        <string>--scan</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

$SCHEDULE_BLOCK

    <!-- Wykonaj także zaraz po zalogowaniu, gdyby któryś skan został pominięty
         (np. MacBook był zamknięty o wyznaczonej godzinie). -->
    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/out/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/out/launchd.err.log</string>

    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
PLIST_EOF

# Walidacja plist przed ładowaniem — lepiej złapać błąd tutaj niż w launchd.
if ! plutil -lint "$PLIST" >/dev/null 2>&1; then
    echo "BŁĄD: wygenerowany plist jest niepoprawny:" >&2
    plutil -lint "$PLIST" >&2
    rm -f "$PLIST"
    exit 1
fi

# Przeładuj zadanie, jeśli już było zainstalowane.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST" || {
    echo "BŁĄD: nie udało się załadować zadania do launchd." >&2
    exit 1
}

echo "Zainstalowano zadanie '$LABEL' — codziennie o: $SUMMARY"
echo
echo "  Plik:        $PLIST"
echo "  Skrypt:      $PROJECT_DIR/publish_report.sh --scan"
echo "  Log:         $PROJECT_DIR/out/publish.log"
echo "  Stan:        ./install_schedule.sh --status"
echo "  Usunięcie:   ./install_schedule.sh --remove"
echo
echo "Uwaga: zadanie działa, gdy jesteś zalogowany. Skan wymaga Twojego łącza"
echo "domowego — serwisy blokują adresy IP centrów danych."
echo "RunAtLoad sprawia, że po zalogowaniu wykona się też zaległy skan."
