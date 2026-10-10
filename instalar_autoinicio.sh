#!/usr/bin/env bash
# Hace que el asistente se abra solo al iniciar sesión (y aparezca en el menú de aplicaciones).
#
#   ./instalar_autoinicio.sh            instalar
#   ./instalar_autoinicio.sh --quitar   desinstalar (no borra tu carpeta ni tus claves)

set -e
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
AUTO="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/jarvis.desktop"
MENU="${XDG_DATA_HOME:-$HOME/.local/share}/applications/jarvis.desktop"
ENVF="${XDG_CONFIG_HOME:-$HOME/.config}/jarvis/env"

if [ "$1" = "--quitar" ]; then
    rm -f "$AUTO" "$MENU"
    echo "✔ Autoinicio y acceso del menú eliminados. (Tus claves siguen en $ENVF)"
    exit 0
fi

chmod +x "$DIR/iniciar.sh"
mkdir -p "$(dirname "$AUTO")" "$(dirname "$MENU")" "$(dirname "$ENVF")"

cat > "$AUTO" <<DESK
[Desktop Entry]
Type=Application
Name=Jarvis
Comment=Asistente de voz con avatar
Exec="$DIR/iniciar.sh"
Path=$DIR
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=8
DESK

cat > "$MENU" <<DESK
[Desktop Entry]
Type=Application
Name=Jarvis
Comment=Asistente de voz con avatar
Exec="$DIR/iniciar.sh"
Path=$DIR
Icon=$DIR/assets/avatar.png
Terminal=false
Categories=Utility;
DESK

# Las claves van en un archivo, porque el autoinicio NO ve los 'export' de tu terminal.
if [ ! -f "$ENVF" ]; then
    {
        echo "# Claves de Jarvis (formato CLAVE=valor). Este archivo es privado."
        echo "GROQ_API_KEY=${GROQ_API_KEY:-}"
        echo "#ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}"
        echo "# Memoria en la nube (Postgres de Render): pega aquí la «External Database URL»"
        echo "#JARVIS_DATABASE_URL=postgresql://usuario:clave@host.render.com/base"
    } > "$ENVF"
    chmod 600 "$ENVF"
    CREADO=1
fi

echo "✔ Listo. Jarvis se abrirá solo al iniciar sesión (con ~8 s de espera para que cargue el audio)."
echo "  • También aparece en el menú de aplicaciones, para abrirlo sin terminal."
echo "  • Si se cae, se reabre solo. Si dices «adiós» o clic derecho > Salir, se queda cerrado."
echo "  • Registro de lo que pasa: ~/.cache/jarvis/jarvis.log"
if [ -n "$CREADO" ]; then
    if grep -q '^GROQ_API_KEY=.\+' "$ENVF"; then
        echo "  • Copié tu GROQ_API_KEY actual a $ENVF"
    else
        echo "  ⚠ Falta tu clave: abre $ENVF y escribe  GROQ_API_KEY=tu_clave"
    fi
fi
