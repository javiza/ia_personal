"""
Copia de la memoria en la nube (Postgres, p. ej. el de Render). Corre en un hilo aparte:
la voz y el chat NUNCA esperan a la red. Si no hay conexión, todo sigue guardándose en este
equipo (memoria.py) y se sube solo cuando vuelva.

Se activa poniendo en ~/.config/jarvis/env:
    JARVIS_DATABASE_URL=postgresql://usuario:clave@host.render.com/base     (la «External Database URL»)

Qué hace en cada ciclo (cada NUBE_SYNC_SEGUNDOS, o enseguida cuando hay algo nuevo):
  1. crea las tablas jarvis_* si no existen (llevan prefijo para poder compartir la base con otras apps);
  2. SUBE lo nuevo o modificado (mensajes, instrucciones, hechos, lecciones);
  3. BAJA lo que haya en la nube que no tengas (otro equipo, o si borraste la carpeta del programa).
"""
import threading
import time
from urllib.parse import urlparse

import config
import memoria

_DDL = """
CREATE TABLE IF NOT EXISTS jarvis_conocimiento (
    uid TEXT PRIMARY KEY, tipo TEXT NOT NULL, texto TEXT NOT NULL, clave TEXT NOT NULL,
    creado TEXT NOT NULL, actualizado TEXT NOT NULL, activo BOOLEAN NOT NULL DEFAULT TRUE);
CREATE INDEX IF NOT EXISTS jarvis_conocimiento_act ON jarvis_conocimiento (actualizado);
CREATE TABLE IF NOT EXISTS jarvis_mensajes (
    uid TEXT PRIMARY KEY, ts TEXT NOT NULL, rol TEXT NOT NULL, contenido TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jarvis_mensajes_ts ON jarvis_mensajes (ts);
CREATE TABLE IF NOT EXISTS jarvis_borrados (uid TEXT PRIMARY KEY, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jarvis_borrados_ts ON jarvis_borrados (ts);
"""

_hilo = None
_despertar = threading.Event()
_estado = {"ok": False, "ultimo_ok": 0.0, "error": ""}


def configurada() -> bool:
    return bool(config.DATABASE_URL)


def avisar():
    """Hay algo nuevo que subir."""
    _despertar.set()


def iniciar():
    global _hilo
    if not configurada() or (_hilo and _hilo.is_alive()):
        return
    _hilo = threading.Thread(target=_bucle, daemon=True, name="jarvis-nube")
    _hilo.start()


def _url() -> str:
    """Render exige SSL desde fuera de su red; se agrega si la URL no lo dice."""
    url = config.DATABASE_URL.strip()
    host = urlparse(url).hostname or ""
    if "sslmode=" not in url and host not in ("localhost", "127.0.0.1", ""):
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _sincronizar(conn, extras):
    cur = conn.cursor()
    cur.execute(_DDL)
    conn.commit()

    # ---- subir
    filas = memoria.pendientes_conocimiento()
    if filas:
        extras.execute_values(cur, """
            INSERT INTO jarvis_conocimiento (uid, tipo, texto, clave, creado, actualizado, activo) VALUES %s
            ON CONFLICT (uid) DO UPDATE SET texto = EXCLUDED.texto, activo = EXCLUDED.activo,
                                            actualizado = EXCLUDED.actualizado
            WHERE jarvis_conocimiento.actualizado <= EXCLUDED.actualizado""",
                              [(u, t, x, c, cr, ac, bool(a)) for u, t, x, c, cr, ac, a in filas])
        conn.commit()
        memoria.marcar_conocimiento([(f[0], f[5]) for f in filas])

    # ---- borrados (primero, para que lo borrado no se vuelva a subir ni a bajar)
    borr = memoria.pendientes_borrados()
    if borr:
        extras.execute_values(cur, "INSERT INTO jarvis_borrados (uid, ts) VALUES %s ON CONFLICT (uid) DO NOTHING", borr)
        cur.execute("DELETE FROM jarvis_mensajes WHERE uid = ANY(%s)", ([b[0] for b in borr],))
        conn.commit()
        memoria.marcar_borrados([b[0] for b in borr])
    cursor = memoria.meta_get("nube_cursor_borrados")
    cur.execute("SELECT uid, ts FROM jarvis_borrados WHERE ts >= %s ORDER BY ts LIMIT 5000", (cursor,))
    ajenos = cur.fetchall()
    if ajenos:
        mayor = memoria.aplicar_remoto_borrados(ajenos)
        if mayor:
            memoria.meta_set("nube_cursor_borrados", mayor)

    while True:
        msgs = memoria.pendientes_mensajes(500)
        if not msgs:
            break
        extras.execute_values(cur, "INSERT INTO jarvis_mensajes (uid, ts, rol, contenido) VALUES %s "
                                   "ON CONFLICT (uid) DO NOTHING", msgs)
        conn.commit()
        memoria.marcar_mensajes([m[0] for m in msgs])

    # ---- bajar
    cursor = memoria.meta_get("nube_cursor_conocimiento")
    cur.execute("SELECT uid, tipo, texto, clave, creado, actualizado, activo FROM jarvis_conocimiento "
                "WHERE actualizado >= %s ORDER BY actualizado", (cursor,))
    nuevos = cur.fetchall()
    if nuevos:
        mayor = memoria.aplicar_remoto_conocimiento(nuevos)
        if mayor:
            memoria.meta_set("nube_cursor_conocimiento", mayor)

    cursor = memoria.meta_get("nube_cursor_mensajes")
    if cursor:
        cur.execute("SELECT uid, ts, rol, contenido FROM jarvis_mensajes WHERE ts > %s ORDER BY ts LIMIT 1000", (cursor,))
        msgs = cur.fetchall()
    else:      # equipo nuevo: solo lo más reciente, no toda la historia
        cur.execute("SELECT uid, ts, rol, contenido FROM jarvis_mensajes ORDER BY ts DESC LIMIT %s", (config.NUBE_MENSAJES_INICIALES,))
        msgs = cur.fetchall()[::-1]
    if msgs:
        mayor = memoria.aplicar_remoto_mensajes(msgs)
        if mayor:
            memoria.meta_set("nube_cursor_mensajes", mayor)


def _bucle():
    try:
        import psycopg2
        import psycopg2.extras as extras
    except ImportError:
        _estado["error"] = "falta la librería psycopg2-binary (abre con ./iniciar.sh para instalarla)"
        print(f"⚠️  Nube: {_estado['error']}")
        return

    fallos = 0
    while True:
        try:
            conn = psycopg2.connect(_url(), connect_timeout=config.NUBE_TIMEOUT, client_encoding="UTF8",
                                    options="-c statement_timeout=20000")
            try:
                _sincronizar(conn, extras)
            finally:
                conn.close()
            if not _estado["ok"] or fallos:
                print("☁️  Memoria sincronizada con la nube.")
            _estado.update(ok=True, ultimo_ok=time.time(), error="")
            fallos = 0
            espera = config.NUBE_SYNC_SEGUNDOS
        except Exception as e:
            fallos += 1
            motivo = str(e).strip().splitlines()[0][:160] if str(e).strip() else e.__class__.__name__
            _estado.update(ok=False, error=motivo)
            if fallos in (1, 10, 100):
                print(f"⚠️  Nube sin conexión ({motivo}). Sigo guardando en este equipo y reintento solo.")
            espera = min(config.NUBE_SYNC_SEGUNDOS * 2 ** min(fallos, 5), 600)
        if _despertar.wait(espera):
            time.sleep(1.5)            # agrupa lo que se guarde en los próximos instantes (pregunta + respuesta)
        _despertar.clear()


def estado_texto() -> str:
    if not configurada():
        return "Nube: sin configurar (guardo solo en este equipo; falta JARVIS_DATABASE_URL)."
    pend = memoria.resumen()["pendientes"]
    if _estado["ok"]:
        hace = int(time.time() - _estado["ultimo_ok"])
        return f"Nube: conectada, última sincronización hace {hace} s, pendientes por subir: {pend}."
    return (f"Nube: sin conexión ({_estado['error'] or 'conectando...'}). "
            f"Guardo aquí y sincronizo cuando vuelva; pendientes: {pend}.")
