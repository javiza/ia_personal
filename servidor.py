"""
Versión WEB / CELULAR de Jarvis: un servidor (FastAPI) + una app instalable (PWA) en web/.

  Local:    JARVIS_WEB_CLAVE=miclave uvicorn servidor:app --port 8000      -> http://localhost:8000
  Render:   ver render.yaml y el README (sección «En el celular»).

DOS MODOS (variable JARVIS_MODO):
  nube (por defecto) ... el servidor (p. ej. Render) NO es tu computador: solo herramientas seguras y archivos dentro
                         de su «espacio». Es lo que usa render.yaml.
  pc .................... el servidor corre EN TU COMPUTADOR con TODAS las herramientas (tus carpetas, la papelera del
                         sistema, pantalla, ventanas...). Tu celular, tablet u otro PC lo usan como control remoto con esta
                         misma app instalable. Exige una clave de 12 caracteres o más. Ver README, «Jarvis en todos tus dispositivos».

Usa el MISMO cerebro, memoria e historial que la versión de escritorio (nucleo.Asistente). Diferencias:
  - Acceso protegido con una clave (JARVIS_WEB_CLAVE): sin ella el servidor no atiende a nadie.
  - Modo web: herramientas seguras (buscar en internet, leer páginas, clima, memoria) y archivos SOLO dentro del
    «espacio» (espacio.py): ahí subes (📎) lo que quieres que lea/edite y descargas (📁) lo que ella crea. Nada de pantalla.
  - La voz usa el micrófono y el altavoz del teléfono (el navegador); si el navegador no sabe dictar,
    el audio se manda a /api/transcribir (Whisper de Groq).
"""
import hashlib
import hmac
import os
import threading
import time

MODO = os.environ.get("JARVIS_MODO", "nube").strip().lower()
PC = MODO == "pc"
if PC:                                    # tu computador: todas las herramientas; lo subido cae en ~/JarvisArchivos
    os.environ.pop("JARVIS_MODO_WEB", None)
    os.environ.setdefault("JARVIS_ESPACIO", os.path.join(os.path.expanduser("~"), "JarvisArchivos"))
else:                                     # servidor en la nube: modo seguro
    os.environ["JARVIS_MODO_WEB"] = "1"   # antes de importar config/tools

import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import ajustes
import config
import espacio
import memoria
import papelera

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, "web")

CLAVE = os.environ.get("JARVIS_WEB_CLAVE", "").strip()
CLAVE_MIN_PC = 12                         # en modo PC la clave abre TU computador: no se acepta una corta
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


def _problema_clave():
    if not CLAVE:
        return "El servidor no tiene JARVIS_WEB_CLAVE configurada."
    if PC and len(CLAVE) < CLAVE_MIN_PC:
        return f"En modo PC la clave (JARVIS_WEB_CLAVE) debe tener al menos {CLAVE_MIN_PC} caracteres."
    return ""


def exigir_sesion(request: Request):
    if _problema_clave():
        raise HTTPException(503, _problema_clave())
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
    if _problema_clave():
        raise HTTPException(503, _problema_clave())
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
            "dictado_servidor": bool(os.environ.get("GROQ_API_KEY")),
            "max_archivo": config.WEB_MAX_ARCHIVO, "extensiones": sorted(config.WEB_EXT_PERMITIDAS),
            "modo": "pc" if PC else "nube",
            "papelera": {"tipo": papelera.tipo(), "listar": papelera.puede_listar(), "restaurar": papelera.puede_restaurar()}}


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


# ------------------------------------------------------------------ archivos (subir, listar, descargar, borrar)
@app.post("/api/subir", dependencies=[Depends(exigir_sesion)])
async def subir(request: Request, nombre: str = ""):
    """Recibe UN archivo como cuerpo crudo (sin multipart) y lo guarda en el espacio de trabajo."""
    limpio = espacio.nombre_seguro(nombre)
    if not espacio.extension_ok(limpio):
        raise HTTPException(415, "Ese tipo de archivo no está permitido (se aceptan documentos, texto, código, imágenes y .zip).")
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > config.WEB_MAX_ARCHIVO:
        raise HTTPException(413, f"El archivo supera el máximo de {config.WEB_MAX_ARCHIVO // (1024 * 1024)} MB.")
    if len(espacio.listar(config.WEB_MAX_ARCHIVOS + 1)) >= config.WEB_MAX_ARCHIVOS:
        raise HTTPException(507, "El espacio está lleno de archivos: borra alguno.")
    libre = config.WEB_MAX_TOTAL - espacio.usado()
    if libre <= 0:
        raise HTTPException(507, "El espacio de archivos está lleno: borra alguno.")
    final = espacio.nombre_libre(limpio)
    base = espacio.raiz()
    temporal = os.path.join(base, f".subiendo-{os.getpid()}-{int(time.time() * 1000)}")
    total = 0
    try:
        with open(temporal, "wb") as f:
            async for trozo in request.stream():
                total += len(trozo)
                if total > config.WEB_MAX_ARCHIVO:
                    raise HTTPException(413, f"El archivo supera el máximo de {config.WEB_MAX_ARCHIVO // (1024 * 1024)} MB.")
                if total > libre:
                    raise HTTPException(507, "No queda espacio para ese archivo: borra alguno.")
                f.write(trozo)
        if total == 0:
            raise HTTPException(400, "El archivo está vacío.")
        os.replace(temporal, os.path.join(base, final))
    finally:
        if os.path.exists(temporal):
            os.remove(temporal)
    return {"nombre": final, "bytes": total}


@app.get("/api/archivos", dependencies=[Depends(exigir_sesion)])
def archivos():
    return {"archivos": espacio.listar(), "usado": espacio.usado(), "maximo": config.WEB_MAX_TOTAL}


@app.get("/api/archivos/descargar", dependencies=[Depends(exigir_sesion)])
def descargar(ruta: str):
    real = espacio.ruta_segura(ruta)
    if real is None:
        raise HTTPException(404, "No encontré ese archivo.")
    return FileResponse(real, filename=os.path.basename(real), media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@app.post("/api/archivos/borrar", dependencies=[Depends(exigir_sesion)])
async def borrar_archivos(request: Request):
    """
    Manda archivos a la papelera (se pueden restaurar desde 🗑 Papelera).
    Cuerpo: {"ruta": "informe.docx"}  ·  {"todo": true}  ·  con "definitivo": true no pasa por la papelera
    (solo lo usa la app al quitar un adjunto que acabas de subir y no enviaste).
    """
    try:
        datos = await request.json()
    except Exception:
        raise HTTPException(400, "Petición inválida.")
    definitivo = datos.get("definitivo") is True and datos.get("todo") is not True
    if datos.get("todo") is True:
        rutas_ = [a["ruta"] for a in espacio.listar()]
    else:
        rutas_ = [str(datos.get("ruta", ""))]
    import anyio

    def _borrar():
        n, fallos = 0, []
        with _lock_papelera:
            for r in rutas_:
                real = espacio.ruta_segura(r)
                if not real:
                    continue
                try:
                    if definitivo:
                        os.remove(real)
                    else:
                        papelera.enviar(real)
                    n += 1
                except Exception as e:
                    fallos.append(f"{os.path.basename(real)}: {e}")
        return n, fallos

    n, fallos = await anyio.to_thread.run_sync(_borrar)
    if not n and fallos:
        raise HTTPException(500, "No pude mandarlo a la papelera: " + "; ".join(fallos))
    if not n and datos.get("todo") is not True:
        raise HTTPException(404, "No encontré ese archivo.")
    return {"borrados": n, "fallos": fallos}


# ------------------------------------------------------------------ papelera (ver, restaurar, eliminar para siempre)
_lock_papelera = threading.Lock()


def _id_publico(e) -> str:
    """Identificador opaco: así el navegador nunca manda (ni ve) rutas reales del disco, y solo se puede tocar lo que está en la papelera."""
    return hashlib.sha256(e.id.encode("utf-8", "replace")).hexdigest()[:24]


def _ruta_visible(ruta):
    if not ruta:
        return ""
    if not PC:                                           # en la nube no se revelan rutas del servidor
        try:
            return os.path.relpath(ruta, os.path.realpath(config.WEB_ESPACIO)).replace(os.sep, "/")
        except ValueError:
            return os.path.basename(ruta)
    return ruta


def _json_entrada(e) -> dict:
    return {"id": _id_publico(e), "nombre": e.nombre, "carpeta": e.es_carpeta, "bytes": e.tamano, "aprox": e.aprox,
            "origen": _ruta_visible(e.origen), "fecha": e.fecha.strftime("%d/%m/%Y %H:%M") if e.fecha else ""}


def _info_papelera() -> dict:
    return {"tipo": papelera.tipo(), "listar": papelera.puede_listar(), "restaurar": papelera.puede_restaurar()}


@app.get("/api/papelera", dependencies=[Depends(exigir_sesion)])
async def ver_papelera():
    import anyio

    def _leer():
        base = _info_papelera()
        if not papelera.puede_listar():
            return {**base, "items": [], "mensaje": papelera.aviso_no_soportado("ver la papelera")}
        try:
            with _lock_papelera:
                entradas = papelera.listar()
        except (PermissionError, NotImplementedError) as e:
            return {**base, "items": [], "mensaje": str(e)}
        return {**base, "items": [_json_entrada(e) for e in entradas[:500]], "total": len(entradas),
                "bytes": sum(e.tamano for e in entradas)}
    return await anyio.to_thread.run_sync(_leer)


async def _cuerpo_ids(request: Request):
    try:
        datos = await request.json()
    except Exception:
        raise HTTPException(400, "Petición inválida.")
    if datos.get("todo") is True:
        return None
    ids = datos.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids) or len(ids) > 5000:
        raise HTTPException(400, "Indica qué elementos.")
    return set(ids)


@app.post("/api/papelera/restaurar", dependencies=[Depends(exigir_sesion)])
async def restaurar_de_papelera(request: Request):
    """Cuerpo: {"ids": [...]}. Devuelve cada cosa a su carpeta original (nunca pisa algo existente)."""
    ids = await _cuerpo_ids(request)
    if ids is None:
        raise HTTPException(400, "Indica qué elementos.")
    if not papelera.puede_restaurar():
        raise HTTPException(501, papelera.aviso_no_soportado("restaurar"))
    import anyio

    def _hacer():
        hechos, fallos = 0, []
        with _lock_papelera:
            for e in papelera.listar():
                if _id_publico(e) not in ids:
                    continue
                try:
                    papelera.restaurar(e)
                    hechos += 1
                except Exception as ex:
                    fallos.append(f"{e.nombre}: {ex}")
        return {"restaurados": hechos, "fallos": fallos}
    return await anyio.to_thread.run_sync(_hacer)


@app.post("/api/papelera/borrar", dependencies=[Depends(exigir_sesion)])
async def borrar_de_papelera(request: Request):
    """Cuerpo: {"ids": [...]} o {"todo": true}. ELIMINA PARA SIEMPRE (la app lo confirma con el usuario antes)."""
    ids = await _cuerpo_ids(request)
    if not papelera.puede_listar():
        raise HTTPException(501, papelera.aviso_no_soportado("borrar definitivamente"))
    import anyio

    def _hacer():
        hechos, fallos = 0, []
        with _lock_papelera:
            for e in papelera.listar():
                if ids is not None and _id_publico(e) not in ids:
                    continue
                try:
                    papelera.borrar_definitivo(e)
                    hechos += 1
                except Exception as ex:
                    fallos.append(f"{e.nombre}: {ex}")
        return {"borrados": hechos, "fallos": fallos}
    return await anyio.to_thread.run_sync(_hacer)


@app.get("/api/historial", dependencies=[Depends(exigir_sesion)])
def historial(limite: int = 150):
    limite = max(1, min(limite, 500))
    return {"mensajes": [{"fecha": f, "quien": q, "texto": t}
                         for f, q, t in memoria.mensajes_para_chat(limite, ajustes.chat_desde())]}


@app.post("/api/pantalla/limpiar", dependencies=[Depends(exigir_sesion)])
def limpiar_pantalla():
    """«Limpiar pantalla»: la conversación anterior deja de mostrarse. El historial NO se borra (sigue en 📜 y en la memoria)."""
    ajustes.guardar_chat_desde(memoria._ahora())
    return {"ok": True}


@app.get("/api/prompts", dependencies=[Depends(exigir_sesion)])
def prompts(q: str = "", limite: int = 400):
    """Todo lo que el usuario ha pedido (el más nuevo primero), opcionalmente filtrado por texto."""
    limite = max(1, min(limite, 5000))
    todos = memoria.prompts_con_id(5000)
    plano = memoria._sin_acentos(q.strip())
    if plano:
        todos = [(u, f, t) for u, f, t in todos if plano in memoria._sin_acentos(t)]
    todos.reverse()
    return {"total": len(todos), "prompts": [{"id": u, "fecha": f, "texto": t} for u, f, t in todos[:limite]]}


@app.post("/api/prompts/borrar", dependencies=[Depends(exigir_sesion)])
async def borrar_prompts(request: Request):
    """
    Borra pedidos del historial (y la respuesta que dieron), también de la nube.
    Cuerpo: {"ids": [...]}  ·  {"q": "texto"} (todos los que coinciden)  ·  {"todo": true}
    """
    try:
        datos = await request.json()
    except Exception:
        raise HTTPException(400, "Petición inválida.")
    import anyio

    def _borrar():
        if datos.get("todo") is True:
            n = memoria.borrar_todo_el_historial()
        elif str(datos.get("q", "")).strip():
            plano = memoria._sin_acentos(str(datos["q"]).strip())
            ids = [u for u, _, t in memoria.prompts_con_id(5000) if plano in memoria._sin_acentos(t)]
            n = memoria.borrar_prompts(ids)
        else:
            ids = datos.get("ids")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise HTTPException(400, "Indica qué borrar.")
            n = memoria.borrar_prompts(ids[:5000])
        if _asistente is not None:                 # la conversación en curso también los olvida
            _asistente.recargar_historial()
        return n

    return {"borrados": await anyio.to_thread.run_sync(_borrar)}


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


@app.get("/instalar")
def pagina_instalar():
    """Página pública con los pasos para instalar la app en cada aparato (no muestra nada privado)."""
    return FileResponse(os.path.join(WEB, "instalar.html"), headers=_SIN_CACHE)


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
    if _problema_clave():
        print(f"⛔ {_problema_clave()} El servidor NO atenderá a nadie hasta que la configures.")
    if PC:
        print("🖥️  Modo PC: este servidor controla TU computador (archivos, papelera, pantalla). "
              "Úsalo solo por una red privada (Tailscale) o desde esta misma máquina.")
    try:
        memoria.iniciar()            # base local + sincronización con Postgres (si hay JARVIS_DATABASE_URL)
    except Exception as e:
        print(f"⚠️  Memoria: {e}")
    print(f"🌐 Jarvis web listo ({'modo PC' if PC else 'modo nube'}) · cerebros: {' → '.join(config.ORDEN_CEREBROS)} · "
          f"nube: {'sí' if config.DATABASE_URL else 'no'}")
