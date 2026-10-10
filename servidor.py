"""
Versión WEB / CELULAR de Jarvis: un servidor (FastAPI) + una app instalable (PWA) en web/.

  Local:    JARVIS_WEB_CLAVE=miclave uvicorn servidor:app --port 8000      -> http://localhost:8000
  Render:   ver render.yaml y el README (sección «En el celular»).

Usa el MISMO cerebro, memoria e historial que la versión de escritorio (nucleo.Asistente). Diferencias:
  - Acceso protegido con una clave (JARVIS_WEB_CLAVE): sin ella el servidor no atiende a nadie.
  - Modo web: solo herramientas seguras (buscar en internet, leer páginas, clima, memoria). Nada de archivos/pantalla.
  - La voz usa el micrófono y el altavoz del teléfono (el navegador); si el navegador no sabe dictar,
    el audio se manda a /api/transcribir (Whisper de Groq).
"""
import hashlib
import hmac
import os
import threading
import time

os.environ["JARVIS_MODO_WEB"] = "1"      # antes de importar config/tools

import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import ajustes
import config
import memoria

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, "web")

CLAVE = os.environ.get("JARVIS_WEB_CLAVE", "").strip()
SECRETO = (os.environ.get("JARVIS_SECRETO", "").strip() or hashlib.sha256(("jarvis-web|" + CLAVE).encode()).hexdigest())
COOKIE = "jarvis_sesion"
DURACION = 30 * 24 * 3600
MAX_TEXTO = 4000
MAX_AUDIO = 8 * 1024 * 1024

app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None, openapi_url=None)

_asistente = None
_asistente_lock = threading.Lock()


def asistente():
    """El asistente se crea la primera vez que se usa (así el servidor arranca rápido y Render ve que está vivo)."""
    global _asistente
    with _asistente_lock:
        if _asistente is None:
            import nucleo
            _asistente = nucleo.Asistente()
        return _asistente


# ------------------------------------------------------------------ acceso (clave + cookie firmada)
def _firmar(exp: int) -> str:
    firma = hmac.new(SECRETO.encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{firma}"


def _token_valido(token: str) -> bool:
    try:
        exp, firma = token.split(".", 1)
        esperado = hmac.new(SECRETO.encode(), exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(firma, esperado) and int(exp) > time.time()
    except (ValueError, AttributeError):
        return False


def exigir_sesion(request: Request):
    if not CLAVE:
        raise HTTPException(503, "El servidor no tiene JARVIS_WEB_CLAVE configurada.")
    if not _token_valido(request.cookies.get(COOKIE, "")):
        raise HTTPException(401, "Falta iniciar sesión.")


_intentos: dict[str, list] = {}       # ip -> [fallos, inicio]
_intentos_lock = threading.Lock()


def _bloqueado(ip: str) -> bool:
    with _intentos_lock:
        fallos, inicio = _intentos.get(ip, [0, time.time()])
        if time.time() - inicio > 600:
            _intentos.pop(ip, None)
            return False
        return fallos >= 6


def _fallo(ip: str):
    with _intentos_lock:
        fallos, inicio = _intentos.get(ip, [0, time.time()])
        _intentos[ip] = [fallos + 1, inicio]


@app.post("/api/login")
async def login(request: Request, response: Response):
    if not CLAVE:
        raise HTTPException(503, "El servidor no tiene JARVIS_WEB_CLAVE configurada.")
    ip = request.client.host if request.client else "?"
    if _bloqueado(ip):
        raise HTTPException(429, "Demasiados intentos. Espera 10 minutos.")
    try:
        datos = await request.json()
    except Exception:
        raise HTTPException(400, "Petición inválida.")
    if not hmac.compare_digest(str(datos.get("clave", "")).encode(), CLAVE.encode()):
        _fallo(ip)
        raise HTTPException(401, "Clave incorrecta.")
    seguro = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, _firmar(int(time.time()) + DURACION), max_age=DURACION, httponly=True,
                    samesite="lax", secure=seguro, path="/")
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ------------------------------------------------------------------ API
@app.get("/salud")
def salud():
    return {"ok": True}


@app.get("/api/estado", dependencies=[Depends(exigir_sesion)])
def estado():
    nube_txt = ""
    try:
        import nube
        nube_txt = nube.estado_texto()
    except Exception:
        pass
    return {"nombre": ajustes.obtener_nombre(), "prompts": memoria.contar_prompts(), "nube": nube_txt,
            "dictado_servidor": bool(os.environ.get("GROQ_API_KEY"))}


@app.post("/api/chat", dependencies=[Depends(exigir_sesion)])
async def chat(request: Request):
    try:
        datos = await request.json()
    except Exception:
        raise HTTPException(400, "Petición inválida.")
    texto = " ".join(str(datos.get("texto", "")).split())[:MAX_TEXTO]
    if not texto:
        raise HTTPException(400, "Escribe algo.")
    import anyio

    def _responder():
        a = asistente()
        respuesta = a.responder(texto)
        return respuesta, a.ultimo_ok

    try:
        respuesta, ok = await anyio.to_thread.run_sync(_responder)
    except Exception as e:
        print(f"⚠️  /api/chat: {e}")
        return {"respuesta": "Tuve un problema pensando la respuesta. Intenta de nuevo.", "ok": False,
                "nombre": ajustes.obtener_nombre()}
    return {"respuesta": respuesta, "ok": ok, "nombre": ajustes.obtener_nombre()}


@app.get("/api/historial", dependencies=[Depends(exigir_sesion)])
def historial(limite: int = 150):
    limite = max(1, min(limite, 500))
    return {"mensajes": [{"fecha": f, "quien": q, "texto": t} for f, q, t in memoria.mensajes_para_chat(limite)]}


@app.get("/api/prompts", dependencies=[Depends(exigir_sesion)])
def prompts(q: str = "", limite: int = 400):
    """Todo lo que el usuario ha pedido (el más nuevo primero), opcionalmente filtrado por texto."""
    limite = max(1, min(limite, 5000))
    todos = memoria.todos_los_prompts(5000)
    plano = memoria._sin_acentos(q.strip())
    if plano:
        todos = [(f, t) for f, t in todos if plano in memoria._sin_acentos(t)]
    todos.reverse()
    return {"total": len(todos), "prompts": [{"fecha": f, "texto": t} for f, t in todos[:limite]]}


@app.post("/api/transcribir", dependencies=[Depends(exigir_sesion)])
async def transcribir(request: Request):
    """Respaldo para navegadores sin dictado: recibe el audio grabado y lo pasa a texto con Whisper (Groq)."""
    clave = os.environ.get("GROQ_API_KEY", "")
    if not clave:
        raise HTTPException(501, "El servidor no tiene GROQ_API_KEY para transcribir audio.")
    audio = await request.body()
    if not audio or len(audio) > MAX_AUDIO:
        raise HTTPException(400, "Audio vacío o demasiado largo.")
    tipo = request.headers.get("content-type", "audio/webm").split(";")[0]
    ext = {"audio/mp4": "m4a", "audio/aac": "aac", "audio/ogg": "ogg", "audio/wav": "wav"}.get(tipo, "webm")
    import anyio

    def _llamar():
        return requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                             headers={"Authorization": f"Bearer {clave}"},
                             files={"file": (f"voz.{ext}", audio, tipo)},
                             data={"model": "whisper-large-v3-turbo", "language": "es", "temperature": "0"},
                             timeout=60)
    try:
        r = await anyio.to_thread.run_sync(_llamar)
    except requests.RequestException:
        raise HTTPException(502, "No pude contactar el servicio de transcripción.")
    if r.status_code != 200:
        raise HTTPException(502, f"La transcripción falló ({r.status_code}).")
    return {"texto": (r.json().get("text") or "").strip()}


# ------------------------------------------------------------------ app instalable (PWA)
_SIN_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
def inicio():
    return FileResponse(os.path.join(WEB, "index.html"), headers=_SIN_CACHE)


@app.get("/sw.js")
def service_worker():
    return FileResponse(os.path.join(WEB, "sw.js"), media_type="application/javascript", headers=_SIN_CACHE)


@app.get("/manifest.webmanifest")
def manifiesto():
    return FileResponse(os.path.join(WEB, "manifest.webmanifest"), media_type="application/manifest+json",
                        headers=_SIN_CACHE)


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.on_event("startup")
def _arranque():
    if not CLAVE:
        print("⛔ Falta JARVIS_WEB_CLAVE: el servidor NO atenderá a nadie hasta que la configures.")
    try:
        memoria.iniciar()            # base local + sincronización con Postgres (si hay JARVIS_DATABASE_URL)
    except Exception as e:
        print(f"⚠️  Memoria: {e}")
    print(f"🌐 Jarvis web listo · cerebros: {' → '.join(config.ORDEN_CEREBROS)} · "
          f"nube: {'sí' if config.DATABASE_URL else 'no'}")
