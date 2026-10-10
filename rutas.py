"""
Única puerta de entrada al disco: valida que toda ruta quede dentro de
config.ALLOWED_DIRS (resolviendo '..' y enlaces simbólicos) y hace respaldo
antes de sobrescribir algo.
"""
import datetime
import os
import shutil
import config


def _dentro_de_permitidos(ruta_absoluta: str) -> bool:
    real = os.path.realpath(ruta_absoluta)
    for base in config.ALLOWED_DIRS:
        base_real = os.path.realpath(base)
        if real == base_real or real.startswith(base_real + os.sep):
            return True
    return False


def _traducir_alias(ruta: str) -> str:
    """
    «Escritorio/notas.txt», «desktop\\notas.txt» o «/home/tu/Desktop/notas.txt» -> la carpeta REAL
    (config.DIRS_USUARIO). Sin esto, «Escritorio/x.txt» se creaba como una carpeta nueva
    dentro de ~/JarvisArchivos y el archivo nunca aparecía en el escritorio.
    """
    home = os.path.expanduser("~")
    absoluta = os.path.isabs(ruta)
    if absoluta:
        try:
            rel = os.path.relpath(ruta, home)
        except ValueError:                      # otro disco en Windows
            return ruta
        if rel.startswith(".."):
            return ruta
        partes = [p for p in rel.replace("\\", "/").split("/") if p]
    else:
        partes = [p for p in ruta.replace("\\", "/").split("/") if p]
    if not partes:
        return ruta
    clave = config.ALIAS_CARPETAS.get(partes[0].lower())
    if not clave:
        return ruta
    return os.path.join(config.DIRS_USUARIO[clave], *partes[1:])


def resolver_ruta(ruta: str, extension_default: str = None, para_crear: bool = False):
    """
    Convierte 'ruta' (relativa o absoluta) en ruta absoluta validada.
    - Si empieza por Escritorio/Documentos/Descargas/Imágenes (o Desktop...), va a esa carpeta real.
    - Relativa: se busca/crea dentro de config.OUTPUT_DIR; si no existe ahí pero sí
      en otra carpeta permitida, usa esa (ej. 'foto.jpg' en Descargas).
    - Devuelve None si queda fuera de las carpetas permitidas.
    """
    ruta = os.path.expanduser((ruta or "").strip())
    if not ruta:
        return None
    if extension_default and not ruta.lower().endswith(extension_default):
        ruta += extension_default
    ruta = _traducir_alias(ruta)

    if os.path.isabs(ruta):
        destino = os.path.abspath(ruta)
    else:
        destino = os.path.abspath(os.path.join(config.OUTPUT_DIR, ruta))
        if not para_crear and not os.path.exists(destino):
            for base in config.ALLOWED_DIRS:
                alt = os.path.abspath(os.path.join(base, ruta))
                if os.path.exists(alt):
                    destino = alt
                    break

    if not _dentro_de_permitidos(destino):
        return None
    if para_crear:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
    return destino


def respaldar(destino: str):
    """Si el archivo existe, guarda una copia con fecha en la carpeta de respaldos."""
    if not os.path.isfile(destino):
        return None
    os.makedirs(config.CARPETA_RESPALDOS, exist_ok=True)
    sello = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    copia = os.path.join(config.CARPETA_RESPALDOS, f"{sello}_{os.path.basename(destino)}")
    shutil.copy2(destino, copia)
    return copia
