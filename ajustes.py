"""
Ajustes que cambian mientras usas el asistente (nombre, posición del avatar).
Se guardan en ajustes.json junto al programa.
"""
import json
import os
import threading
import config

_RUTA = os.path.join(config.BASE_DIR, "ajustes.json")
_lock = threading.Lock()
_suscriptores = []   # funciones que se avisan cuando cambia el nombre (ej. la interfaz)


def _leer() -> dict:
    try:
        with open(_RUTA, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _escribir(datos: dict):
    with open(_RUTA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def obtener_nombre() -> str:
    return _leer().get("nombre") or config.NOMBRE_POR_DEFECTO


def limpiar_nombre(nombre: str) -> str:
    """Deja solo un nombre razonable: sin saltos de línea, máx. 30 caracteres."""
    nombre = " ".join((nombre or "").split()).strip(" .,;:!¡?¿\"'")
    return nombre[:30]


def guardar_nombre(nombre: str) -> str:
    nombre = limpiar_nombre(nombre)
    if not nombre:
        raise ValueError("El nombre no puede estar vacío.")
    with _lock:
        datos = _leer()
        datos["nombre"] = nombre
        _escribir(datos)
    for cb in list(_suscriptores):
        try:
            cb(nombre)
        except Exception:
            pass
    return nombre


def suscribir_cambio_nombre(callback):
    _suscriptores.append(callback)


def voz_activa() -> bool:
    """¿Se le habla por voz? False = modo solo escritura: no se abre el micrófono ni se escucha «Hey Jarvis»."""
    return bool(_leer().get("voz_activa", True))


def guardar_voz_activa(activa: bool):
    with _lock:
        datos = _leer()
        datos["voz_activa"] = bool(activa)
        _escribir(datos)


def leer_respuestas() -> bool:
    """¿Leer en voz alta las respuestas a lo que escribes en el chat?"""
    return bool(_leer().get("leer_respuestas", False))


def guardar_leer_respuestas(valor: bool):
    with _lock:
        datos = _leer()
        datos["leer_respuestas"] = bool(valor)
        _escribir(datos)


def obtener_posicion():
    pos = _leer().get("posicion")
    if isinstance(pos, list) and len(pos) == 2:
        return int(pos[0]), int(pos[1])
    return None


def guardar_posicion(x: int, y: int):
    with _lock:
        datos = _leer()
        datos["posicion"] = [int(x), int(y)]
        _escribir(datos)


def tema() -> str:
    """Tema de la interfaz de escritorio: 'oscuro' (por defecto) o 'claro'."""
    t = _leer().get("tema", "oscuro")
    return t if t in ("claro", "oscuro") else "oscuro"


def guardar_tema(valor: str):
    with _lock:
        datos = _leer()
        datos["tema"] = "claro" if valor == "claro" else "oscuro"
        _escribir(datos)


def chat_desde() -> str:
    """Marca de tiempo (ISO) desde la que se muestra la conversación en pantalla. Vacía = se muestra todo.
    Se guarda al pulsar «Limpiar pantalla»; el historial completo NO se borra."""
    return str(_leer().get("chat_desde", "") or "")


def guardar_chat_desde(marca: str):
    with _lock:
        datos = _leer()
        datos["chat_desde"] = marca or ""
        _escribir(datos)
