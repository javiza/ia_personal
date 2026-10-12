"""
Configuración central de tu asistente.
Cambia estos valores según tu equipo y preferencias.
(El NOMBRE de la asistente ya no va aquí: se cambia hablándole —"a partir de
ahora te llamas Aria"— o con clic derecho sobre el avatar. Se guarda en ajustes.json)
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cargar_claves():
    """
    Lee las API keys desde un archivo de texto (formato CLAVE=valor), para que el programa
    funcione igual si lo abres tú, el autoinicio o un acceso directo (esos NO ven los
    'export' de tu terminal). Busca, en este orden:  ./.env  y  ~/.config/jarvis/env
    Lo que ya esté en el entorno tiene prioridad.
    """
    rutas = [os.path.join(BASE_DIR, ".env"),
             os.path.join(os.path.expanduser("~"), ".config", "jarvis", "env")]
    for ruta in rutas:
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if not linea or linea.startswith("#") or "=" not in linea:
                        continue
                    clave, valor = linea.split("=", 1)
                    clave = clave.replace("export ", "").strip()
                    os.environ.setdefault(clave, valor.strip().strip('"').strip("'"))
        except OSError:
            pass


_cargar_claves()

# --- Identidad ---
NOMBRE_POR_DEFECTO = os.environ.get("JARVIS_NOMBRE", "Jarvis")   # nombre inicial; luego puedes cambiarlo cuando quieras

# --- Versión web / celular (servidor.py, desplegada en Render) ---
# JARVIS_MODO_WEB=1 la pone en modo servidor: solo herramientas seguras (web, clima, memoria), sin tocar archivos,
# pantalla ni ventanas del servidor. Se activa sola en servidor.py.
MODO_WEB = os.environ.get("JARVIS_MODO_WEB", "") == "1"
AVATAR_PATH = os.path.join(BASE_DIR, "assets", "avatar.png")
# Para usar OTRA imagen como icono (una foto, una ilustración que generes con una IA
# de imágenes, etc.) basta con reemplazar assets/avatar.png por tu archivo (PNG con
# fondo transparente o ya recortado en círculo se ve mejor).
AVATAR_MOVIMIENTO = 1.0            # 0 = imagen quieta; 1 = respira y se mece; 2 = más movimiento
# AVATAR ANIMADO: deja en assets/ un avatar.gif (o .webp/.apng animado) y se usa en vez de la imagen fija.
# Opcional, uno por estado: avatar_reposo.gif, avatar_escuchando.gif, avatar_pensando.gif, avatar_hablando.gif
AVATAR_TAMANO = 150                # diámetro del avatar en pantalla (píxeles)

# --- Grabación de audio ---
SAMPLE_RATE = 16000        # Whisper trabaja mejor a 16kHz
CHANNELS = 1

# --- Wake word ("Hey Jarvis") ---
# openWakeWord trae modelos ya entrenados: "hey_jarvis", "alexa", "hey_mycroft",
# "hey_rhasspy". NO puede aprender un nombre cualquiera sin entrenar un modelo
# propio, así que la palabra de activación sigue siendo una de esas, aunque la
# asistente se llame como tú quieras. Siempre puedes activarla con un CLIC en el avatar.
WAKEWORD_MODEL = "hey_jarvis"
# El umbral ideal depende de TU micrófono y ambiente. Si se activa sola con ruido,
# súbelo (ej. 0.25); si te cuesta activarla, bájalo (ej. 0.1).
# Tip: di "Hey Jarvis" en inglés (no "harvis" a la española).
WAKEWORD_THRESHOLD = 0.15

# --- Detección de silencio (para saber cuándo dejaste de hablar) ---
SILENCE_THRESHOLD = 0.015
SILENCE_DURATION = 0.8
MAX_RECORD_SECONDS = 15

# --- Reconocimiento de voz (STT) ---
# "tiny", "base", "small", "medium", "large-v3" (de más rápido a más preciso)
WHISPER_MODEL_SIZE = "small"
WHISPER_LANGUAGE = "es"
WHISPER_VAD_FILTER = True

# --- Cerebro (LLM) ---
# ORDEN_CEREBROS: en qué orden se prueban. Si uno falla (límite de uso, sin internet,
# Ollama apagado, modelo retirado) pasa SOLO al siguiente; ya no tienes que esperar.
#   "ollama"    -> en tu computador: sin límites de uso, sin internet y con un modelo SIN los
#                  filtros de las nubes (OLLAMA_MODEL). Más lento si tu PC no tiene GPU.
#   "groq"      -> nube gratis con límites; sus modelos traen filtros de seguridad propios.
#   "anthropic" -> Claude (de pago, por uso); también trae sus propias normas.
# Si quieres que NUNCA use una nube con filtros: ORDEN_CEREBROS = ["ollama"]
ORDEN_CEREBROS = ["groq", "gemini", "anthropic", "ollama"]   # los que no tienen clave se saltan solos
if os.environ.get("JARVIS_CEREBROS"):          # p. ej. en Render:  JARVIS_CEREBROS=groq,anthropic
    ORDEN_CEREBROS = [x.strip() for x in os.environ["JARVIS_CEREBROS"].split(",") if x.strip()]

# Ollama (local).  Instalar:  ollama pull hermes3:8b   (~5 GB; hecho para usar herramientas)
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_VISION_MODEL = "llama3.2-vision"    # ollama pull llama3.2-vision  (para analizar fotos)
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_NUM_CTX = 8192                      # memoria de la conversación; con menos se corta el prompt
OLLAMA_KEEP_ALIVE = "60m"                  # mantiene el modelo cargado entre preguntas (responde más rápido)
# --- Anti-lentitud ---
# ANTES esperaba hasta 300 s a Ollama antes de pasar a Groq (por eso cada respuesta tardaba ~5 min).
OLLAMA_TIMEOUT_PRIMER_TOKEN = 45           # s máx. hasta que Ollama empieza a responder (carga del modelo + leer el prompt)
OLLAMA_TIMEOUT_TOTAL = 90                  # s máx. por CADA vuelta del modelo en Ollama; si no, pasa a la nube
OLLAMA_TIMEOUT_TAREA = 420                 # s máx. para una tarea completa de varios pasos (revisar un proyecto, etc.)
OLLAMA_PAUSA_TRAS_LENTITUD = 600           # s que NO se vuelve a intentar con Ollama tras ser demasiado lento (evita esperar en cada pregunta)
if ORDEN_CEREBROS == ["ollama"]:           # sin nube de respaldo no hay a dónde saltar: se le da tiempo (CPU sin GPU es lento)
    OLLAMA_TIMEOUT_PRIMER_TOKEN = 240
    OLLAMA_TIMEOUT_TOTAL = 360
    OLLAMA_TIMEOUT_TAREA = 900
OLLAMA_MAX_TOKENS_RESPUESTA = 400          # las respuestas son de 1-4 frases; así no divaga
OLLAMA_TEMPERATURA = 0.3
OLLAMA_REPEAT_PENALTY = 1.15               # evita el bucle de «… … …» que salía a veces

# Groq (nube gratis). Cada modelo tiene su PROPIO límite por minuto, así que si uno se agota
# pasa al siguiente en vez de quedarse esperando. El plan gratis de gpt-oss-120b es de solo
# ~8.000 tokens/minuto; por eso el primero es el que más rinde y los demás son el respaldo.
GROQ_MODELOS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]
GROQ_REASONING_EFFORT = "low"              # "low" | "medium" | "high": más alto = piensa más y gasta más tokens
# Modelo de Groq que VE imágenes. Groq los cambia seguido (llama-4-scout fue retirado
# en junio de 2026). Si da error 404, mira https://console.groq.com/docs/vision
# o define la variable de entorno GROQ_VISION_MODEL sin tocar el código.
GROQ_VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

# Si la nube dice "espera N segundos" y N es menor que esto, espera y reintenta en el mismo
# modelo; si es más, pasa al siguiente cerebro de la lista.
ESPERA_MAX_REINTENTO = 8  # reintentos breves; esperas largas se delegan al siguiente proveedor

ANTHROPIC_MODEL = "claude-sonnet-5-5"

# Gemini (Google AI Studio, capa gratis). Clave en ~/.config/jarvis/env:  GEMINI_API_KEY=...
# Se usa su endpoint compatible con OpenAI. Si un modelo da 404, mira los nombres vigentes en
# https://ai.google.dev/gemini-api/docs/models y cámbialos aquí.
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
# Se puede sobrescribir sin editar el código: GEMINI_MODELOS=gemini-2.5-flash,gemini-2.5-flash-lite
GEMINI_MODELOS = [x.strip() for x in os.environ.get(
    "GEMINI_MODELOS", "gemini-2.5-flash" #quite "gemini-2.5-flash-lite" porque da error 404 en junio de 2026
).split(",") if x.strip()]
GEMINI_CACHE_SEGUNDOS = 1800          # vuelve a consultar modelos disponibles cada 30 minutos
GEMINI_TIMEOUT = 60

# La API key se lee de la variable de entorno ANTHROPIC_API_KEY (no la pongas aquí).
# La de Groq, de GROQ_API_KEY.

# Cuántas vueltas herramienta->modelo puede dar en una sola petición (tareas de varios
# pasos: buscar -> leer página -> resumir -> guardar). Más = más capaz pero más lento.
MAX_TURNOS_TOOL = 12
MAX_CHARS_RESULTADO_TOOL = 3000    # tope de texto que una herramienta devuelve al modelo
MAX_CHARS_TOOL_ANTIGUO = 1500      # resultados de pasos ya superados se acortan a esto (ahorra tokens)

# --- Herramientas (tools) ---
# Carpetas a las que puede acceder: listar, leer, crear y editar archivos e imágenes.
# NUNCA puede tocar nada fuera de esta lista. Se agregan las carpetas con nombre en
# español (Escritorio, Documentos, Descargas, Imágenes) solo si existen en tu equipo.
_HOME = os.path.expanduser("~")
OUTPUT_DIR = os.path.join(_HOME, "JarvisArchivos")     # donde guarda lo que crea si no dices otra carpeta


def _xdg(nombre):
    """Lee ~/.config/user-dirs.dirs (Linux): ahí está la ruta REAL de tu Escritorio, aunque se llame Escritorio, Desktop..."""
    try:
        with open(os.path.join(_HOME, ".config", "user-dirs.dirs"), encoding="utf-8") as f:
            for linea in f:
                if linea.startswith(f"XDG_{nombre}_DIR="):
                    return linea.split("=", 1)[1].strip().strip('"').replace("$HOME", _HOME)
    except OSError:
        pass
    return None


def _primera_existente(candidatas, defecto):
    for c in candidatas:
        if c and os.path.isdir(c):
            return c
    return defecto


# Nombre que puedes decir -> carpeta real. Así «escritorio», «Desktop» o «Escritorio/notas.txt»
# terminan SIEMPRE en tu Escritorio de verdad y no en una carpeta inventada.
DIRS_USUARIO = {
    "escritorio": _primera_existente(
        [_xdg("DESKTOP"), os.path.join(_HOME, "Escritorio"), os.path.join(_HOME, "Desktop"),
         os.path.join(_HOME, "OneDrive", "Escritorio"), os.path.join(_HOME, "OneDrive", "Desktop")],
        os.path.join(_HOME, "Desktop")),
    "documentos": _primera_existente(
        [_xdg("DOCUMENTS"), os.path.join(_HOME, "Documentos"), os.path.join(_HOME, "Documents")],
        os.path.join(_HOME, "Documents")),
    "descargas": _primera_existente(
        [_xdg("DOWNLOAD"), os.path.join(_HOME, "Descargas"), os.path.join(_HOME, "Downloads")],
        os.path.join(_HOME, "Downloads")),
    "imagenes": _primera_existente(
        [_xdg("PICTURES"), os.path.join(_HOME, "Imágenes"), os.path.join(_HOME, "Imagenes"),
         os.path.join(_HOME, "Pictures")],
        os.path.join(_HOME, "Pictures")),
}
ALIAS_CARPETAS = {
    "escritorio": "escritorio", "desktop": "escritorio", "el escritorio": "escritorio",
    "documentos": "documentos", "documents": "documentos", "mis documentos": "documentos",
    "descargas": "descargas", "downloads": "descargas",
    "imagenes": "imagenes", "imágenes": "imagenes", "pictures": "imagenes", "fotos": "imagenes",
}
ALLOWED_DIRS = [OUTPUT_DIR] + list(dict.fromkeys(DIRS_USUARIO.values()))
CARPETA_RESPALDOS = os.path.join(OUTPUT_DIR, ".respaldos")  # copia automática antes de sobrescribir

# --- Espacio de archivos de la versión web/celular ---
# Es la única carpeta que la asistente puede tocar desde el celular: lo que subes (📎) y lo que ella crea/edita.
# En Render el disco gratis se borra en cada reinicio/deploy: descarga lo importante, o monta un Disk
# (plan pagado) y pon JARVIS_ESPACIO=/var/data/espacio.
WEB_ESPACIO = os.environ.get("JARVIS_ESPACIO", os.path.join(BASE_DIR, "espacio"))
WEB_MAX_ARCHIVO = 15 * 1024 * 1024          # bytes por archivo subido
WEB_MAX_TOTAL = 150 * 1024 * 1024           # bytes en todo el espacio
WEB_MAX_ARCHIVOS = 300
WEB_EXT_PERMITIDAS = {                      # solo formatos que ella sabe leer/editar; nada ejecutable ni .svg/.html servibles
    ".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".yml", ".yaml", ".log", ".ini", ".cfg", ".conf", ".toml", ".env",
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".php", ".rb", ".sh", ".sql", ".html", ".css",
    ".docx", ".xlsx", ".xlsm", ".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".webp",
}
if MODO_WEB:                                # el servidor solo ve su espacio: ni Escritorio ni Documentos
    OUTPUT_DIR = WEB_ESPACIO
    DIRS_USUARIO = {}
    ALIAS_CARPETAS = {}
    ALLOWED_DIRS = [WEB_ESPACIO]
    CARPETA_RESPALDOS = os.path.join(WEB_ESPACIO, ".respaldos")

# Permiso para que pueda MIRAR tu pantalla (captura) cuando se lo pidas. La lista de
# ventanas abiertas (solo títulos) no depende de esto. La captura se envía al modelo
# de IA que uses (Groq/Claude), por eso se puede apagar aquí.
PERMITIR_PANTALLA = True

# --- Web ---
WEB_TIMEOUT = 15
WEB_MAX_CHARS = 3500        # cuánto texto de una página se le entrega al modelo
WEB_MAX_RESULTADOS = 5

# --- Voz de salida (TTS) ---
# edge-tts: voces neuronales de Microsoft, gratis. Requiere internet.
# Femeninas en español: "es-CL-CatalinaNeural" (Chile), "es-ES-ElviraNeural",
# "es-MX-DaliaNeural", "es-AR-ElenaNeural". Masculina chilena: "es-CL-LorenzoNeural".
TTS_VOICE = "es-CL-CatalinaNeural"
TTS_RATE = "+8%"

# --- Memoria y aprendizaje ---
DB_PATH = os.path.join(BASE_DIR, "memoria.sqlite3")      # copia local: siempre se usa, funciona sin internet
MAX_HISTORY_MESSAGES = 8                  # mensajes de la conversación que se le reenvían en cada turno
MAX_INSTRUCCIONES_EN_PROMPT = 40           # reglas permanentes que SIEMPRE ve (son pocas y deben cumplirse)
MAX_RECUERDOS_EN_PROMPT = 12               # datos tuyos: los más parecidos a lo que preguntas (+ los 4 más recientes)
MAX_LECCIONES_EN_PROMPT = 6                # correcciones pasadas relevantes
APRENDER = True                            # aprende sola de las conversaciones (en segundo plano)
APRENDER_CADA = 6                          # cada cuántos turnos reflexiona (o enseguida si dices «recuerda…», «siempre…»)

# Memoria en la NUBE (Postgres de Render). Se activa poniendo en ~/.config/jarvis/env:
#     JARVIS_DATABASE_URL=postgresql://usuario:clave@dpg-xxxx.oregon-postgres.render.com/base   (External Database URL)
# Sin esa variable todo se guarda solo en este equipo. La clave de la URL es privada: no la pongas en este archivo.
DATABASE_URL = os.environ.get("JARVIS_DATABASE_URL", "").strip()
# Al iniciar con la base local vacía (equipo nuevo, o el servidor de Render que se reinicia) se bajan estos mensajes.
NUBE_MENSAJES_INICIALES = 20000 if MODO_WEB else 200
NUBE_SYNC_SEGUNDOS = 60                    # cada cuánto revisa la nube (si hay algo nuevo, sube enseguida)
NUBE_TIMEOUT = 8                           # s máx. para conectarse a la nube


# --- Imágenes y video (generar y editar) ---
# Proveedores de imagen, en orden de prueba (los que necesitan clave y no la tienen se saltan solos):
#   "pollinations" gratis, sin clave (puede cambiar o limitarse)   "openai"  OPENAI_API_KEY (genera y EDITA con IA)
#   "huggingface"  HF_TOKEN                                       "local_sd" Stable Diffusion local (AUTOMATIC1111 --api)
# Claves en ~/.config/jarvis/env  (OPENAI_API_KEY=...  HF_TOKEN=...  REPLICATE_API_TOKEN=...)
IMAGEN_PROVEEDORES = ["pollinations", "openai", "huggingface", "local_sd"]
IMAGEN_TIMEOUT = 120
POLLINATIONS_URL = os.environ.get("POLLINATIONS_URL", "https://image.pollinations.ai/prompt")   # si cambian la dirección, ponla en env
POLLINATIONS_MODEL = "flux"
OPENAI_URL = "https://api.openai.com/v1"
OPENAI_IMAGE_MODEL = "gpt-image-1"
HF_IMAGE_URL = "https://router.huggingface.co/hf-inference/models/{modelo}"
HF_IMAGE_MODEL = "black-forest-labs/FLUX.1-schnell"
LOCAL_SD_URL = "http://127.0.0.1:7860"
LOCAL_SD_TIMEOUT = 300

# Video con IA (Replicate, de pago por uso). Los nombres de modelo cambian seguido: si da 404,
# busca uno de «text to video» / «image to video» en https://replicate.com/explore y cámbialo aquí.
REPLICATE_URL = "https://api.replicate.com/v1"
REPLICATE_VIDEO_MODEL = "wan-video/wan-2.2-t2v-fast"       # texto -> video
REPLICATE_VIDEO_I2V_MODEL = "wan-video/wan-2.2-i2v-fast"   # imagen (+ texto) -> video
VIDEO_TIMEOUT = 600        # s máx. esperando que la IA termine el video
VIDEO_POLL_SEG = 4
