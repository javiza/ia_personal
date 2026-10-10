"""
Memoria persistente (SQLite local + copia en la nube, ver nube.py).

Qué se guarda:
  - mensajes:     lo que se dijo (para retomar la conversación al reiniciar).
  - conocimiento: lo que ella APRENDE de ti, de tres tipos:
        instruccion  reglas permanentes que le das («responde siempre corto», «cuando diga X haz Y»)
        hecho        datos duraderos sobre ti y tu mundo («trabaja con Next.js», «su hija se llama Ana»)
        leccion      correcciones: errores que cometió y no debe repetir

Todo se guarda PRIMERO en este equipo (rápido, funciona sin internet) y nube.py lo copia a Postgres
en segundo plano. Nada de aquí espera nunca a la red. Los borrados son «suaves» (activo=0) para que
también se propaguen a la nube.
"""
import datetime
import math
import re
import sqlite3
import threading
import unicodedata
import uuid
from collections import Counter

import config

TIPOS = ("hecho", "instruccion", "leccion")
_MAX_TEXTO = 300

_init_lock = threading.Lock()
_listo = False


def _ahora() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ base local
def _conectar():
    global _listo
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    if not _listo:
        with _init_lock:
            if not _listo:
                _preparar(conn)
                _listo = True
    return conn


def _columnas(conn, tabla):
    return {f[1] for f in conn.execute(f"PRAGMA table_info({tabla})")}


def _preparar(conn):
    """Crea las tablas y migra lo que dejaron versiones anteriores (sin perder nada)."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")      # lector y sincronizador a la vez sin «database is locked»
    except sqlite3.DatabaseError:
        pass
    conn.execute("""CREATE TABLE IF NOT EXISTS mensajes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, rol TEXT NOT NULL, contenido TEXT NOT NULL)""")
    cols = _columnas(conn, "mensajes")
    if "uid" not in cols:
        conn.execute("ALTER TABLE mensajes ADD COLUMN uid TEXT")
    if "sync" not in cols:
        conn.execute("ALTER TABLE mensajes ADD COLUMN sync INTEGER NOT NULL DEFAULT 0")
    for (i,) in conn.execute("SELECT id FROM mensajes WHERE uid IS NULL").fetchall():
        conn.execute("UPDATE mensajes SET uid=? WHERE id=?", (uuid.uuid4().hex, i))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS mensajes_uid ON mensajes(uid)")

    conn.execute("""CREATE TABLE IF NOT EXISTS conocimiento (
        uid TEXT PRIMARY KEY, tipo TEXT NOT NULL, texto TEXT NOT NULL, clave TEXT NOT NULL,
        creado TEXT NOT NULL, actualizado TEXT NOT NULL,
        activo INTEGER NOT NULL DEFAULT 1, sync INTEGER NOT NULL DEFAULT 0,
        UNIQUE (tipo, clave))""")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    # «Lápidas»: mensajes borrados a propósito. Se suben a la nube para que otros equipos también los borren
    # y para que no «reaparezcan» al bajar la copia de la nube.
    conn.execute("CREATE TABLE IF NOT EXISTS borrados (uid TEXT PRIMARY KEY, ts TEXT NOT NULL, sync INTEGER NOT NULL DEFAULT 0)")

    # Versiones anteriores guardaban los datos duraderos en la tabla «hechos»: se pasan una sola vez.
    antigua = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hechos'").fetchone()
    migrado = conn.execute("SELECT v FROM meta WHERE k='hechos_migrados'").fetchone()
    if antigua and not migrado:
        for ts, texto in conn.execute("SELECT timestamp, texto FROM hechos").fetchall():
            conn.execute("INSERT OR IGNORE INTO conocimiento (uid, tipo, texto, clave, creado, actualizado) "
                         "VALUES (?, 'hecho', ?, ?, ?, ?)", (uuid.uuid4().hex, texto, _clave(texto), ts, ts))
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('hechos_migrados', '1')")
    conn.commit()


def _avisar_nube():
    try:
        import nube
        nube.avisar()
    except Exception:
        pass


def iniciar():
    """Prepara la base local y arranca la copia en la nube (si hay JARVIS_DATABASE_URL). Nunca falla."""
    try:
        _conectar().close()
    except Exception as e:
        print(f"⚠️  Memoria local: {e}")
    try:
        import nube
        nube.iniciar()
    except Exception as e:
        print(f"⚠️  Memoria en la nube desactivada: {e}")


def meta_get(k, defecto=""):
    conn = _conectar()
    try:
        f = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return f[0] if f else defecto
    finally:
        conn.close()


def meta_set(k, v):
    conn = _conectar()
    conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ texto: claves, palabras y filtros
def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


_PARADAS = set("""el la los las un una unos unas de del al y o u e a en con por para que se su sus mi mis tu tus
lo le les me te nos es son ser fue ha han he hay como mas pero si no ya muy sobre entre este esta estos estas ese esa
usuario siempre cuando donde quien cual cuales todo toda todos todas sus""".split())


def _tokens(texto: str) -> list[str]:
    """Palabras «raíz» (primeras 5 letras): así «proyectos» y «proyecto» coinciden."""
    palabras = re.findall(r"[a-z0-9ñ]+", _sin_acentos(texto or ""))
    return [p[:5] for p in palabras if len(p) > 2 and p not in _PARADAS]


def _clave(texto: str) -> str:
    return " ".join(re.findall(r"[a-z0-9ñ]+", _sin_acentos(texto or "")))


_RE_SENSIBLE = re.compile(
    r"(contrase[ñn]a|password|passwd|\bcvv\b|api[_ -]?key|\bsecret\b|token de acceso|\bsk-[A-Za-z0-9]{10,}|\bgsk_\w+"
    r"|(?:\d[ -]?){13,19}|\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b)", re.I)


def es_sensible(texto: str) -> bool:
    """Contraseñas, claves de API, números de tarjeta, RUT: nunca se guardan (ni local ni en la nube)."""
    return bool(_RE_SENSIBLE.search(texto or ""))


def _parecidos(a: set, b: set) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= 0.8


# ------------------------------------------------------------------ mensajes
def guardar_mensaje(rol: str, contenido: str):
    conn = _conectar()
    conn.execute("INSERT INTO mensajes (timestamp, rol, contenido, uid, sync) VALUES (?, ?, ?, ?, 0)",
                 (_ahora(), rol, contenido, uuid.uuid4().hex))
    conn.commit()
    conn.close()
    _avisar_nube()


def cargar_historial_reciente(limite: int = None) -> list[dict]:
    limite = limite or config.MAX_HISTORY_MESSAGES
    conn = _conectar()
    # 'user_error' = prompts que no se pudieron responder: se guardan para el historial, pero no van al modelo.
    filas = conn.execute("SELECT rol, contenido FROM mensajes WHERE rol IN ('user','assistant') "
                         "ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    conn.close()
    filas.reverse()
    # Se descartan avisos de error y salidas rotas guardadas por versiones anteriores: el modelo
    # las imitaba («Llegué al límite…», «hola.txt creado» sin haberlo creado, bucles de «…»).
    malos = ("llegué al límite", "el modelo respondió error", "no pude pensar la respuesta",
             "se agotó el uso gratuito", "me enredé usando", "tuve un problema")
    limpias = []
    for rol, contenido in filas:
        bajo = contenido.lower()
        if rol == "assistant" and (any(x in bajo for x in malos) or contenido.count(" ") > 5
                                   or contenido.count("…") > 8):
            if limpias and limpias[-1]["role"] == "user":
                limpias.pop()            # y la pregunta que se quedó sin respuesta buena
            continue
        limpias.append({"role": rol, "content": contenido})
    return limpias


# ------------------------------------------------------------------ historial de prompts (todo lo que has pedido)
ROLES_PROMPT = ("user", "user_error")


def guardar_prompt_fallido(contenido: str):
    """Un prompt que no obtuvo respuesta (sin internet, límite del modelo…) también se recuerda."""
    conn = _conectar()
    conn.execute("INSERT INTO mensajes (timestamp, rol, contenido, uid, sync) VALUES (?, 'user_error', ?, ?, 0)",
                 (_ahora(), contenido, uuid.uuid4().hex))
    conn.commit()
    conn.close()
    _avisar_nube()


def _hora_local(ts: str) -> str:
    try:
        d = datetime.datetime.fromisoformat(ts).astimezone()
        return d.strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return ts[:16]


def todos_los_prompts(limite: int = 5000) -> list[tuple[str, str]]:
    """[(fecha legible, texto)] de TODO lo que el usuario ha pedido, del más antiguo al más reciente."""
    conn = _conectar()
    try:
        filas = conn.execute("SELECT timestamp, contenido FROM mensajes WHERE rol IN ('user','user_error') "
                             "ORDER BY timestamp DESC, id DESC LIMIT ?", (limite,)).fetchall()
    finally:
        conn.close()
    filas.reverse()
    return [(_hora_local(ts), c) for ts, c in filas]


def mensajes_para_chat(limite: int = 150) -> list[tuple[str, str, str]]:
    """[(fecha, quien, texto)] de la conversación anterior, para mostrarla al abrir el chat."""
    conn = _conectar()
    try:
        filas = conn.execute("SELECT timestamp, rol, contenido FROM mensajes ORDER BY timestamp DESC, id DESC LIMIT ?",
                             (limite,)).fetchall()
    finally:
        conn.close()
    filas.reverse()
    quien = {"user": "tu", "user_error": "tu", "assistant": "ella"}
    return [(_hora_local(ts), quien.get(rol, "aviso"), c) for ts, rol, c in filas if rol in quien]


def contar_prompts() -> int:
    conn = _conectar()
    try:
        return conn.execute("SELECT COUNT(*) FROM mensajes WHERE rol IN ('user','user_error')").fetchone()[0]
    finally:
        conn.close()


def buscar_prompts(consulta: str, k: int = 8, con_respuesta: bool = True) -> list[dict]:
    """
    Busca en TODO el historial lo más parecido a 'consulta' (palabras compartidas, dando más peso a las poco comunes).
    Sin consulta devuelve los últimos k. Cada resultado: {fecha, prompt, respuesta}.
    """
    conn = _conectar()
    try:
        filas = conn.execute("SELECT id, timestamp, rol, contenido FROM mensajes WHERE rol IN ('user','user_error','assistant') "
                             "ORDER BY timestamp, id").fetchall()
    finally:
        conn.close()
    prompts = [(i, ts, c) for i, ts, rol, c in filas if rol in ROLES_PROMPT]
    if not prompts:
        return []
    respuesta_de = {}
    if con_respuesta:
        for n, (i, ts, rol, c) in enumerate(filas):
            if rol in ROLES_PROMPT and n + 1 < len(filas) and filas[n + 1][2] == "assistant":
                respuesta_de[i] = filas[n + 1][3]
    q = set(_tokens(consulta))
    if q:
        docs = [set(_tokens(c)) for _, _, c in prompts]
        df = Counter(w for d in docs for w in d)
        puntos = sorted(((sum(math.log(1 + len(docs) / df[w]) for w in q & d), n)
                         for n, d in enumerate(docs) if q & d), reverse=True)
        elegidos = sorted(n for _, n in puntos[:k])
    else:
        elegidos = list(range(max(0, len(prompts) - k), len(prompts)))
    return [{"fecha": _hora_local(prompts[n][1]), "prompt": prompts[n][2],
             "respuesta": respuesta_de.get(prompts[n][0], "")} for n in elegidos]


def prompts_relacionados(consulta: str, k: int = 3, excluir_recientes: int = 12) -> list[str]:
    """Prompts ANTIGUOS (fuera de la ventana de conversación actual) parecidos a lo que se pide ahora."""
    conn = _conectar()
    try:
        filas = conn.execute("SELECT contenido FROM mensajes WHERE rol IN ('user','user_error') AND id NOT IN "
                             "(SELECT id FROM mensajes ORDER BY id DESC LIMIT ?) ORDER BY id", (excluir_recientes,)).fetchall()
    finally:
        conn.close()
    textos = [f[0] for f in filas]
    q = set(_tokens(consulta))
    if not textos or not q:
        return []
    docs = [set(_tokens(t)) for t in textos]
    df = Counter(w for d in docs for w in d)
    puntos = sorted(((sum(math.log(1 + len(docs) / df[w]) for w in q & d), n)
                     for n, d in enumerate(docs) if len(q & d) >= 2), reverse=True)
    return [textos[n][:200] for _, n in puntos[:k]]


# ------------------------------------------------------------------ borrar del historial
def prompts_con_id(limite: int = 5000) -> list[tuple[str, str, str]]:
    """[(uid, fecha legible, texto)] de lo que el usuario ha pedido, del más antiguo al más reciente."""
    conn = _conectar()
    try:
        filas = conn.execute("SELECT uid, timestamp, contenido FROM mensajes WHERE rol IN ('user','user_error') "
                             "ORDER BY timestamp DESC, id DESC LIMIT ?", (limite,)).fetchall()
    finally:
        conn.close()
    filas.reverse()
    return [(u, _hora_local(ts), c) for u, ts, c in filas]


def _eliminar(conn, uids) -> int:
    uids = list(dict.fromkeys(uids))
    ahora = _ahora()
    for i in range(0, len(uids), 500):
        lote = uids[i:i + 500]
        conn.executemany("INSERT OR IGNORE INTO borrados (uid, ts, sync) VALUES (?, ?, 0)", [(u, ahora) for u in lote])
        conn.execute(f"DELETE FROM mensajes WHERE uid IN ({','.join('?' * len(lote))})", lote)
    conn.commit()
    return len(uids)


def borrar_prompts(uids) -> int:
    """
    Borra esos pedidos Y la respuesta que les dio (el mensaje que viene justo después). Se borra también de la nube
    y de la memoria de la conversación en curso. Devuelve cuántos pedidos se borraron.
    (Lo que ella «aprendió» de ti —reglas, datos, lecciones— no se toca: eso se gestiona con «olvida lo de…».)
    """
    objetivo = set(uids or [])
    if not objetivo:
        return 0
    conn = _conectar()
    try:
        filas = conn.execute("SELECT uid, rol FROM mensajes ORDER BY timestamp, id").fetchall()
        borrar, n = [], 0
        for i, (uid, rol) in enumerate(filas):
            if uid in objetivo and rol in ROLES_PROMPT:
                borrar.append(uid)
                n += 1
                if i + 1 < len(filas) and filas[i + 1][1] == "assistant":
                    borrar.append(filas[i + 1][0])
        if borrar:
            _eliminar(conn, borrar)
    finally:
        conn.close()
    if n:
        _avisar_nube()
    return n


def borrar_todo_el_historial() -> int:
    """Borra TODOS los mensajes (pedidos y respuestas). Devuelve cuántos pedidos había."""
    conn = _conectar()
    try:
        n = conn.execute("SELECT COUNT(*) FROM mensajes WHERE rol IN ('user','user_error')").fetchone()[0]
        uids = [u for (u,) in conn.execute("SELECT uid FROM mensajes").fetchall()]
        if uids:
            _eliminar(conn, uids)
    finally:
        conn.close()
    if uids:
        _avisar_nube()
    return n


def pendientes_borrados():
    conn = _conectar()
    try:
        return conn.execute("SELECT uid, ts FROM borrados WHERE sync=0").fetchall()
    finally:
        conn.close()


def marcar_borrados(uids):
    conn = _conectar()
    conn.executemany("UPDATE borrados SET sync=1 WHERE uid=?", [(u,) for u in uids])
    conn.commit()
    conn.close()


def aplicar_remoto_borrados(filas) -> str:
    """Otro equipo borró estos mensajes: se borran aquí también. Devuelve el mayor 'ts'."""
    conn = _conectar()
    mayor = ""
    try:
        for uid, ts in filas:
            mayor = max(mayor, ts)
            conn.execute("INSERT OR IGNORE INTO borrados (uid, ts, sync) VALUES (?, ?, 1)", (uid, ts))
            conn.execute("DELETE FROM mensajes WHERE uid=?", (uid,))
        conn.commit()
    finally:
        conn.close()
    return mayor


# ------------------------------------------------------------------ conocimiento
def guardar(tipo: str, texto: str) -> str:
    """
    Guarda una instrucción, un hecho o una lección.
    Devuelve: 'nuevo' | 'repetido' (ya lo sabía, o casi igual) | 'sensible' | 'vacio'.
    """
    if tipo not in TIPOS:
        raise ValueError(f"tipo desconocido: {tipo}")
    texto = " ".join((texto or "").split())[:_MAX_TEXTO]
    if len(texto) < 4:
        return "vacio"
    if es_sensible(texto):
        return "sensible"
    clave, ahora = _clave(texto), _ahora()
    conn = _conectar()
    try:
        fila = conn.execute("SELECT uid, activo FROM conocimiento WHERE tipo=? AND clave=?", (tipo, clave)).fetchone()
        if fila and fila[1]:
            return "repetido"
        if fila:                                    # estaba borrado: se reactiva
            conn.execute("UPDATE conocimiento SET texto=?, activo=1, actualizado=?, sync=0 WHERE uid=?",
                         (texto, ahora, fila[0]))
        else:
            nuevos = set(_tokens(texto))
            for (t,) in conn.execute("SELECT texto FROM conocimiento WHERE tipo=? AND activo=1", (tipo,)):
                if _parecidos(nuevos, set(_tokens(t))):
                    return "repetido"
            conn.execute("INSERT INTO conocimiento (uid, tipo, texto, clave, creado, actualizado) VALUES (?,?,?,?,?,?)",
                         (uuid.uuid4().hex, tipo, texto, clave, ahora, ahora))
        conn.commit()
    finally:
        conn.close()
    _avisar_nube()
    return "nuevo"


def _filas(tipo: str):
    conn = _conectar()
    try:
        return conn.execute("SELECT texto, actualizado FROM conocimiento WHERE tipo=? AND activo=1 "
                            "ORDER BY actualizado, rowid", (tipo,)).fetchall()
    finally:
        conn.close()


def listar(tipo: str, limite: int = 60) -> list[str]:
    return [t for t, _ in _filas(tipo)][-limite:]


def instrucciones() -> list[str]:
    """Todas las reglas permanentes (son pocas y siempre deben cumplirse)."""
    return listar("instruccion", config.MAX_INSTRUCCIONES_EN_PROMPT)


def relevantes(consulta: str, tipo: str, k: int, recientes: int = 0) -> list[str]:
    """
    Los k conocimientos más parecidos a lo que se pregunta (por palabras compartidas, dando más peso a
    las poco comunes) + los más recientes. Así el prompt no crece aunque ella sepa mil cosas.
    """
    textos = [t for t, _ in _filas(tipo)]
    if len(textos) <= k + recientes:
        return textos
    docs = [set(_tokens(t)) for t in textos]
    df = Counter(w for d in docs for w in d)
    q = set(_tokens(consulta))
    puntos = sorted(((sum(math.log(1 + len(docs) / df[w]) for w in q & d), i) for i, d in enumerate(docs) if q & d),
                    reverse=True)
    elegidos = [i for _, i in puntos[:k]]
    for i in range(len(textos) - 1, len(textos) - 1 - recientes, -1):
        if i not in elegidos:
            elegidos.append(i)
    return [textos[i] for i in sorted(elegidos)]


def olvidar(fragmento: str, tipo: str = None) -> int:
    """Borra (de forma suave) lo que contenga 'fragmento'. Devuelve cuántos."""
    fragmento = (fragmento or "").strip()
    if len(fragmento) < 3:
        return 0
    conn = _conectar()
    sql = "UPDATE conocimiento SET activo=0, actualizado=?, sync=0 WHERE activo=1 AND texto LIKE ?"
    args = [_ahora(), f"%{fragmento}%"]
    if tipo:
        sql += " AND tipo=?"
        args.append(tipo)
    n = conn.execute(sql, args).rowcount
    conn.commit()
    conn.close()
    if n:
        _avisar_nube()
    return n


def resumen() -> dict:
    conn = _conectar()
    try:
        cuenta = dict(conn.execute("SELECT tipo, COUNT(*) FROM conocimiento WHERE activo=1 GROUP BY tipo").fetchall())
        pend = conn.execute("SELECT (SELECT COUNT(*) FROM conocimiento WHERE sync=0) + "
                            "(SELECT COUNT(*) FROM mensajes WHERE sync=0)").fetchone()[0]
        mensajes = conn.execute("SELECT COUNT(*) FROM mensajes").fetchone()[0]
    finally:
        conn.close()
    return {"cuenta": cuenta, "pendientes": pend, "mensajes": mensajes}


# ------------------------------------------------------------------ interfaz para nube.py
def pendientes_conocimiento():
    conn = _conectar()
    try:
        return conn.execute("SELECT uid, tipo, texto, clave, creado, actualizado, activo FROM conocimiento "
                            "WHERE sync=0").fetchall()
    finally:
        conn.close()


def pendientes_mensajes(limite=500):
    conn = _conectar()
    try:
        return conn.execute("SELECT uid, timestamp, rol, contenido FROM mensajes WHERE sync=0 ORDER BY id LIMIT ?",
                            (limite,)).fetchall()
    finally:
        conn.close()


def marcar_conocimiento(pares):
    """pares: [(uid, actualizado)]. Solo se marca si no cambió mientras se subía."""
    conn = _conectar()
    conn.executemany("UPDATE conocimiento SET sync=1 WHERE uid=? AND actualizado=?", pares)
    conn.commit()
    conn.close()


def marcar_mensajes(uids):
    conn = _conectar()
    conn.executemany("UPDATE mensajes SET sync=1 WHERE uid=?", [(u,) for u in uids])
    conn.commit()
    conn.close()


def aplicar_remoto_conocimiento(filas) -> str:
    """Mezcla lo que hay en la nube (otro equipo, o una copia anterior). Gana el más reciente. Devuelve el mayor 'actualizado'."""
    conn = _conectar()
    mayor = ""
    try:
        for uid, tipo, texto, clave, creado, actualizado, activo in filas:
            mayor = max(mayor, actualizado)
            local = conn.execute("SELECT actualizado FROM conocimiento WHERE uid=?", (uid,)).fetchone()
            if local:
                if actualizado > local[0]:
                    conn.execute("UPDATE conocimiento SET texto=?, activo=?, actualizado=?, sync=1 WHERE uid=?",
                                 (texto, int(bool(activo)), actualizado, uid))
            elif not conn.execute("SELECT 1 FROM conocimiento WHERE tipo=? AND clave=?", (tipo, clave)).fetchone():
                conn.execute("INSERT INTO conocimiento (uid, tipo, texto, clave, creado, actualizado, activo, sync) "
                             "VALUES (?,?,?,?,?,?,?,1)", (uid, tipo, texto, clave, creado, actualizado, int(bool(activo))))
        conn.commit()
    finally:
        conn.close()
    return mayor


def aplicar_remoto_mensajes(filas) -> str:
    conn = _conectar()
    mayor = ""
    try:
        for uid, ts, rol, contenido in filas:
            mayor = max(mayor, ts)
            if conn.execute("SELECT 1 FROM borrados WHERE uid=?", (uid,)).fetchone():
                continue                    # lo borraste a propósito: no vuelve
            conn.execute("INSERT OR IGNORE INTO mensajes (timestamp, rol, contenido, uid, sync) VALUES (?,?,?,?,1)",
                         (ts, rol, contenido, uid))
        conn.commit()
    finally:
        conn.close()
    return mayor
