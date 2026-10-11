"""
Espacio de archivos de la versión WEB/CELULAR.

Es la ÚNICA carpeta que la asistente puede tocar desde el celular: ahí caen los archivos que subes (📎) y los que
ella crea o edita; desde ahí los descargas. Nada fuera de esta carpeta es accesible.
"""
import os
import re
import time

import config

_PROHIBIDOS = re.compile(r"[^\w.\- ()]", re.UNICODE)


def raiz() -> str:
    os.makedirs(config.WEB_ESPACIO, exist_ok=True)
    return os.path.realpath(config.WEB_ESPACIO)


def extension_ok(nombre: str) -> bool:
    return os.path.splitext(nombre)[1].lower() in config.WEB_EXT_PERMITIDAS


def nombre_seguro(nombre: str) -> str:
    """Solo el nombre (sin carpetas), sin caracteres raros, sin puntos al inicio."""
    n = os.path.basename((nombre or "").replace("\\", "/")).strip().lstrip(".")
    n = _PROHIBIDOS.sub("_", n)[:120].strip()
    return n or "archivo"


def nombre_libre(nombre: str) -> str:
    """Si ya existe un archivo con ese nombre, agrega (2), (3)... para no pisarlo."""
    base, ext = os.path.splitext(nombre)
    candidato, i = nombre, 2
    while os.path.exists(os.path.join(raiz(), candidato)):
        candidato = f"{base} ({i}){ext}"
        i += 1
    return candidato


def ruta_segura(rel: str):
    """Ruta absoluta de un archivo EXISTENTE dentro del espacio, o None si intenta salirse."""
    rel = (rel or "").replace("\\", "/").strip().strip("/")
    partes = [p for p in rel.split("/") if p]
    if not partes or any(p in (".", "..") or p.startswith(".") for p in partes):
        return None
    base = raiz()
    real = os.path.realpath(os.path.join(base, *partes))
    if not real.startswith(base + os.sep) or not os.path.isfile(real):
        return None
    return real


def listar(limite: int = 500) -> list:
    """Archivos del espacio (subcarpetas incluidas; las ocultas, como los respaldos, no), el más nuevo primero."""
    base = raiz()
    salida = []
    for carpeta, subs, archivos in os.walk(base):
        subs[:] = [d for d in subs if not d.startswith(".")]
        for f in archivos:
            if f.startswith("."):
                continue
            ruta = os.path.join(carpeta, f)
            try:
                st = os.stat(ruta)
            except OSError:
                continue
            salida.append({"ruta": os.path.relpath(ruta, base).replace(os.sep, "/"),
                           "bytes": st.st_size, "mtime": int(st.st_mtime),
                           "fecha": time.strftime("%d/%m %H:%M", time.localtime(st.st_mtime))})
    salida.sort(key=lambda x: x["mtime"], reverse=True)
    return salida[:limite]


def usado() -> int:
    total = 0
    for carpeta, _, archivos in os.walk(raiz()):
        for f in archivos:
            try:
                total += os.path.getsize(os.path.join(carpeta, f))
            except OSError:
                pass
    return total


def para_prompt(maximo: int = 30) -> str:
    """Una línea con los archivos disponibles, para que el modelo sepa qué hay sin tener que listarlos."""
    nombres = [a["ruta"] for a in listar(maximo)]
    return ", ".join(nombres) if nombres else "(vacío)"
