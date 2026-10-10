#!/usr/bin/env bash
#
# Instaluje codzienne zadanie EV Radar w launchd (natywny harmonogram macOS).
# Odpowiednik rejestracji zadania w Harmonogramie zadań Windows.
#
# Użycie:
#   ./install_schedule.sh              # instaluje zadanie na 12:00
#   ./install_schedule.sh 8 30         # instaluje zadanie na 08:30
#   ./install_schedule.sh --remove     # usuwa zadanie
#   ./install_schedule.sh --status     # pokazuje stan i ostatnie uruchomienia
#
# Dlaczego launchd, a nie cron: launchd działa też po wybudzeniu MacBooka ze snu
# (cron w tym czasie po prostu nie odpala). Ma też `RunAtLoad`, dzięki któremu
# zaległy skan wykona się po włączeniu komputera.

set -uo pipefail

cd "$(dirname "$0")" || exit 1
PROJECT_DIR="$(pwd)"
LABEL="com.evradar.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

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
            echo "Plik: $PLIST (istnieje)"
        else
            echo "Plik: $PLIST (BRAK — zadanie niezainstalowane)"
        fi
        launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E 'state|last exit|runs' || \
            echo "Zadanie nie jest załadowane do launchd."
        if [ -f out/publish.log ]; then
            echo
            echo "== Ostatnie 12 linii out/publish.log =="
            tail -12 out/publish.log
        fi
        exit 0
        ;;
esac

HOUR="${1:-12}"
MINUTE="${2:-0}"

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

    <!-- Codziennie o $HOUR:$MINUTE -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>$HOUR</integer>
        <key>Minute</key><integer>$MINUTE</integer>
    </dict>

    <!-- Wykonaj także zaraz po zalogowaniu, gdyby skan został pominięty
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

# Przeładuj zadanie, jeśli już było zainstalowane.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST" || {
    echo "BŁĄD: nie udało się załadować zadania do launchd." >&2
    exit 1
}

echo "Zainstalowano zadanie '$LABEL' — codziennie o $(printf '%02d:%02d' "$HOUR" "$MINUTE")."
echo
echo "  Plik:        $PLIST"
echo "  Skrypt:      $PROJECT_DIR/publish_report.sh --scan"
echo "  Log:         $PROJECT_DIR/out/publish.log"
echo "  Stan:        ./install_schedule.sh --status"
echo "  Usunięcie:   ./install_schedule.sh --remove"
echo
echo "Uwaga: zadanie działa, gdy jesteś zalogowany. Skan wymaga Twojego łącza"
echo "domowego — serwisy blokują adresy IP centrów danych."
