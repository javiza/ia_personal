#!/usr/bin/env bash
# Lanza el asistente. Antes de abrirlo se asegura de que estén instaladas TODAS sus librerías
# (las crea/instala solas, así no vuelve a caerse con «No module named ...») y lo reabre si se cae.
# Si lo cierras tú (decir "adiós", clic derecho > Salir, Ctrl+C), NO se vuelve a abrir.
#
#   ./iniciar.sh              con avatar
#   ./iniciar.sh --sin-ui     solo consola
#   ./iniciar.sh --reinstalar vuelve a instalar las librerías (por si algo quedó a medias)
#
# Variables opcionales:  JARVIS_ESPERA=3 (segundos entre reinicios)

cd "$(dirname "$(readlink -f "$0")")" || exit 1
DIR="$PWD"
ESPERA="${JARVIS_ESPERA:-3}"
MARCA_REQ="$DIR/.requisitos.sha"

# --- Registro (solo si no lo estás mirando en una terminal)
LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/jarvis"
LOG="$LOG_DIR/jarvis.log"
mkdir -p "$LOG_DIR"
if [ ! -t 1 ]; then
    [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 2097152 ] && : > "$LOG"   # tope de 2 MB
    exec >> "$LOG" 2>&1
fi

log()    { echo "[$(date '+%F %T')] $*"; }
avisar() { command -v notify-send >/dev/null 2>&1 && notify-send "Jarvis" "$1" 2>/dev/null; }

REINSTALAR=0
ARGS=()
for a in "$@"; do
    if [ "$a" = "--reinstalar" ]; then REINSTALAR=1; else ARGS+=("$a"); fi
done

# --- 1. Elegir (o crear) el entorno virtual --------------------------------------------------
PY=""
for cand in "$DIR/.venv/bin/python3" "$DIR/venv/bin/python3"; do
    if [ -x "$cand" ] && "$cand" -c "import sys" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    log "▶ no hay un entorno virtual que funcione; creando .venv ..."
    if python3 -m venv "$DIR/.venv" >/dev/null 2>&1 && [ -x "$DIR/.venv/bin/python3" ]; then
        PY="$DIR/.venv/bin/python3"
    else
        log "✖ no pude crear el entorno virtual. Instala:  sudo apt install python3-venv python3-pip   y vuelve a abrir."
        avisar "Falta python3-venv. Mira $LOG"
        exit 1
    fi
fi

# --- 2. Instalar lo que falte ----------------------------------------------------------------
# Se vuelve a revisar solo si cambió requirements.txt o si falta alguna librería importante.
IMPORTS="requests numpy sounddevice faster_whisper openwakeword edge_tts docx openpyxl fpdf PIL mss bs4 pypdf PySide6 psycopg2"

faltan() {
    "$PY" - $IMPORTS <<'PYEOF'
import importlib.util, sys
print(" ".join(m for m in sys.argv[1:] if importlib.util.find_spec(m) is None))
PYEOF
}

instalar() {
    log "▶ instalando librerías (puede tardar unos minutos la primera vez)..."
    "$PY" -m pip install --disable-pip-version-check -q --upgrade pip >/dev/null 2>&1
    if "$PY" -m pip install --disable-pip-version-check -r "$DIR/requirements.txt"; then
        sha256sum "$DIR/requirements.txt" | cut -d' ' -f1 > "$MARCA_REQ"
        log "✔ librerías instaladas"
    else
        # Un solo paquete que no compile hace que pip no instale NADA. Se prueba uno por uno.
        log "⚠ pip falló en un paquete; instalo los demás uno por uno..."
        local linea paq
        while IFS= read -r linea; do
            paq="$(echo "${linea%%#*}" | xargs)"
            [ -z "$paq" ] && continue
            "$PY" -m pip install --disable-pip-version-check -q "$paq" || log "✖ no pude instalar: $paq"
        done < "$DIR/requirements.txt"
    fi
}

verificar_entorno() {
    local sha_actual sha_guardado sin
    sha_actual="$(sha256sum "$DIR/requirements.txt" | cut -d' ' -f1)"
    sha_guardado="$(cat "$MARCA_REQ" 2>/dev/null)"
    sin="$(faltan)"
    if [ "$REINSTALAR" = 1 ] || [ "$sha_actual" != "$sha_guardado" ] || [ -n "$sin" ]; then
        [ -n "$sin" ] && log "▶ faltan librerías: $sin"
        instalar
        REINSTALAR=0
        sin="$(faltan)"
        [ -n "$sin" ] && log "⚠ siguen faltando: $sin (esas funciones quedarán desactivadas)"
    fi
}

verificar_entorno

# Aviso (una vez) de paquetes del sistema que pip no puede instalar
if command -v ldconfig >/dev/null 2>&1 && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
    log "⚠ falta libportaudio2 (micrófono). Instala:  sudo apt install libportaudio2 libxcb-cursor0 wmctrl xdotool"
fi

# --- 3. Abrir y reabrir si se cae -------------------------------------------------------------
rapidos=0
instalo_tras_fallo=0
while true; do
    inicio=$(date +%s)
    log "▶ iniciando con $PY"
    "$PY" main.py "${ARGS[@]}"
    codigo=$?
    log "■ terminó con código $codigo"

    # 0 = cierre normal / ya había otra copia abierta · 130 = Ctrl+C · 143 = apagado del sistema
    case "$codigo" in 0|130|143) exit 0 ;; esac

    # 78 = main.py avisó que falta una librería: instalarla (una vez) y reintentar
    if [ "$codigo" = 78 ]; then
        if [ "$instalo_tras_fallo" = 1 ]; then
            log "✖ sigue faltando una librería aun después de instalar. Revisa los mensajes de pip arriba."
            avisar "No pude instalar una librería. Mira $LOG"
            exit 1
        fi
        instalo_tras_fallo=1
        REINSTALAR=1
        verificar_entorno
        continue
    fi

    # Si se cae al instante 5 veces seguidas, algo está roto de verdad: no insistir eternamente
    if [ $(( $(date +%s) - inicio )) -lt 20 ]; then rapidos=$((rapidos + 1)); else rapidos=0; fi
    if [ "$rapidos" -ge 5 ]; then
        log "✖ se cayó 5 veces seguidas nada más abrir; me rindo."
        avisar "Se cae al iniciar. Revisa $LOG"
        exit 1
    fi
    sleep "$ESPERA"
done
