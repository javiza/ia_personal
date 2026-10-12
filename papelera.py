"""
Papelera REAL del sistema operativo (la misma que ves en el explorador de archivos).

  enviar(ruta) ........... manda un archivo o carpeta a la papelera del sistema
  listar() ............... qué hay dentro de la papelera
  restaurar(entrada) ..... lo devuelve a su carpeta original
  borrar_definitivo(e) ... lo elimina para siempre (NO se puede deshacer)

Soporte:
  Linux ... todo (estándar freedesktop: ~/.local/share/Trash y las papeleras de discos externos).
  macOS ... enviar, listar y borrar definitivo. Restaurar NO: macOS no guarda de dónde vino cada archivo
            en un sitio que un programa pueda leer; se restaura desde el Finder («Devolver»).
  Windows . solo enviar (con send2trash). Listar/restaurar/borrar definitivo: desde la Papelera de reciclaje.

Enviar usa la librería Send2Trash (requirements.txt), que sabe hacerlo bien en cada sistema.
"""
import datetime
import os
import shutil
import sys
import urllib.parse

LINUX = sys.platform.startswith("linux")
MAC = sys.platform == "darwin"
WINDOWS = sys.platform.startswith("win")

_TOPE_RECORRIDO = 20000          # al medir carpetas, máximo de elementos a contar (para no colgarse con carpetas enormes)


class Entrada:
    """Una cosa que está en la papelera."""
    __slots__ = ("id", "nombre", "origen", "fecha", "tamano", "aprox", "es_carpeta", "_info", "_raiz")

    def __init__(self, id, nombre, origen, fecha, tamano, aprox, es_carpeta, info=None, raiz=None):
        self.id = id                  # ruta real del archivo dentro de la papelera (identifica la entrada)
        self.nombre = nombre          # nombre original (sin prefijos raros)
        self.origen = origen          # carpeta+nombre donde estaba; None si el sistema no lo guarda
        self.fecha = fecha            # datetime del borrado, o None
        self.tamano = tamano          # bytes
        self.aprox = aprox            # True si el tamaño de una carpeta es solo aproximado
        self.es_carpeta = es_carpeta
        self._info = info             # Linux: ruta del .trashinfo
        self._raiz = raiz             # Linux: carpeta de la papelera a la que pertenece


# ---------------------------------------------------------------- capacidades
def puede_listar() -> bool:
    return LINUX or MAC


def puede_restaurar() -> bool:
    return LINUX


def aviso_no_soportado(accion: str) -> str:
    if MAC and accion == "restaurar":
        return "En macOS no puedo restaurar desde aquí: abre la Papelera y usa clic derecho > «Devolver»."
    if WINDOWS:
        return f"En Windows todavía no puedo {accion} desde aquí: hazlo desde la Papelera de reciclaje."
    return f"Este sistema no permite {accion} desde aquí."


# ---------------------------------------------------------------- enviar
def enviar(ruta: str) -> None:
    """Manda 'ruta' (archivo o carpeta) a la papelera del sistema. Lanza excepción si no se pudo."""
    try:
        from send2trash import send2trash
    except ImportError:
        raise RuntimeError("falta la librería Send2Trash. Cierra y abre con ./iniciar.sh (la instala sola) "
                           "o ejecuta: pip install Send2Trash")
    send2trash(os.fspath(ruta))
    if os.path.lexists(ruta):
        raise OSError("el sistema no la movió a la papelera")


# ---------------------------------------------------------------- utilidades
def medir(ruta: str):
    """(bytes, aproximado?) de un archivo o carpeta. Una carpeta enorme se corta en _TOPE_RECORRIDO elementos."""
    try:
        if os.path.islink(ruta) or not os.path.isdir(ruta):
            return os.lstat(ruta).st_size, False
        total, contados = 0, 0
        for base, dirs, archivos in os.walk(ruta):
            for a in archivos:
                contados += 1
                if contados > _TOPE_RECORRIDO:
                    return total, True
                try:
                    total += os.lstat(os.path.join(base, a)).st_size
                except OSError:
                    pass
        return total, False
    except OSError:
        return 0, False


def _es_carpeta_real(ruta: str) -> bool:
    return os.path.isdir(ruta) and not os.path.islink(ruta)


def _borrar_del_disco(ruta: str) -> None:
    if _es_carpeta_real(ruta):
        shutil.rmtree(ruta)
    else:
        os.remove(ruta)


# ---------------------------------------------------------------- Linux (estándar freedesktop)
def _papeleras_linux():
    """[(carpeta_papelera, carpeta_raiz_del_disco_o_None)]: la de tu usuario + las de discos montados."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    res = [(os.path.join(base, "Trash"), None)]
    uid = os.getuid()
    home = os.path.expanduser("~")
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            montajes = [l.split()[1].replace("\\040", " ") for l in f if len(l.split()) > 1]
    except OSError:
        montajes = []
    for mp in dict.fromkeys(montajes):
        if not (mp == "/" or mp.startswith(("/media", "/mnt", "/run/media")) or mp.startswith(home + os.sep)):
            continue
        for cand in (os.path.join(mp, ".Trash", str(uid)), os.path.join(mp, f".Trash-{uid}")):
            if os.path.isdir(os.path.join(cand, "info")) and (cand, mp) not in res:
                res.append((cand, mp))
    return res


def _leer_info(ruta_info: str):
    path = fecha = None
    try:
        with open(ruta_info, encoding="utf-8", errors="replace") as f:
            for linea in f:
                if linea.startswith("Path="):
                    path = urllib.parse.unquote(linea[5:].rstrip("\n"))
                elif linea.startswith("DeletionDate="):
                    fecha = linea[13:].strip()
    except OSError:
        return None, None
    try:
        fecha = datetime.datetime.fromisoformat(fecha) if fecha else None
    except ValueError:
        fecha = None
    return path, fecha


def _listar_linux():
    entradas = []
    for papelera, raiz in _papeleras_linux():
        carpeta_info = os.path.join(papelera, "info")
        carpeta_files = os.path.join(papelera, "files")
        try:
            nombres = os.listdir(carpeta_info)
        except OSError:
            continue
        for n in nombres:
            if not n.endswith(".trashinfo"):
                continue
            clave = n[:-len(".trashinfo")]
            guardado = os.path.join(carpeta_files, clave)
            if not os.path.lexists(guardado):
                continue                                   # info huérfana: el explorador tampoco la muestra
            path, fecha = _leer_info(os.path.join(carpeta_info, n))
            if path and raiz and not os.path.isabs(path):  # en discos externos la ruta viene relativa al disco
                path = os.path.join(raiz, path)
            tam, aprox = medir(guardado)
            entradas.append(Entrada(guardado, os.path.basename(path) if path else clave, path, fecha,
                                    tam, aprox, _es_carpeta_real(guardado),
                                    os.path.join(carpeta_info, n), papelera))
    return entradas


def _limpiar_directorysizes(papelera: str, clave: str) -> None:
    """Las carpetas en la papelera tienen una caché de tamaño; al sacarlas hay que quitar su línea (mejor esfuerzo)."""
    ruta = os.path.join(papelera, "directorysizes")
    try:
        with open(ruta, encoding="utf-8") as f:
            lineas = f.readlines()
        quedan = [l for l in lineas if l.rstrip("\n").split(" ", 2)[-1] != urllib.parse.quote(clave)]
        if len(quedan) != len(lineas):
            with open(ruta, "w", encoding="utf-8") as f:
                f.writelines(quedan)
    except OSError:
        pass


def _verificar_dentro(e: Entrada) -> None:
    """Seguridad: solo se toca algo que de verdad esté dentro de la carpeta files/ de una papelera."""
    files = os.path.realpath(os.path.join(e._raiz, "files"))
    if os.path.realpath(os.path.dirname(e.id)) != files:
        raise PermissionError("esa entrada no está dentro de la papelera")


def _restaurar_linux(e: Entrada) -> str:
    _verificar_dentro(e)
    if not e.origen:
        raise OSError("la papelera no guarda de dónde venía")
    destino = e.origen
    if os.path.lexists(destino):                           # nunca pisar algo que ya existe
        base, ext = os.path.splitext(e.origen)
        destino, n = f"{base}_restaurado{ext}", 2
        while os.path.lexists(destino):
            destino, n = f"{base}_restaurado{n}{ext}", n + 1
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.move(e.id, destino)
    try:
        os.remove(e._info)
    except OSError:
        pass
    _limpiar_directorysizes(e._raiz, os.path.basename(e.id))
    return destino


def _borrar_linux(e: Entrada) -> None:
    _verificar_dentro(e)
    _borrar_del_disco(e.id)
    try:
        os.remove(e._info)
    except OSError:
        pass
    _limpiar_directorysizes(e._raiz, os.path.basename(e.id))


# ---------------------------------------------------------------- macOS
def _listar_mac():
    papelera = os.path.join(os.path.expanduser("~"), ".Trash")
    entradas = []
    try:
        nombres = os.listdir(papelera)
    except OSError:                                        # macOS puede negar el acceso sin permiso de «Acceso total al disco»
        raise PermissionError("macOS no me deja leer la Papelera (da «Acceso total al disco» a Terminal/Python).")
    for n in nombres:
        if n == ".DS_Store":
            continue
        ruta = os.path.join(papelera, n)
        tam, aprox = medir(ruta)
        try:
            fecha = datetime.datetime.fromtimestamp(os.lstat(ruta).st_ctime)
        except OSError:
            fecha = None
        entradas.append(Entrada(ruta, n, None, fecha, tam, aprox, _es_carpeta_real(ruta)))
    return entradas


def _borrar_mac(e: Entrada) -> None:
    papelera = os.path.realpath(os.path.join(os.path.expanduser("~"), ".Trash"))
    if os.path.realpath(os.path.dirname(e.id)) != papelera:
        raise PermissionError("esa entrada no está dentro de la papelera")
    _borrar_del_disco(e.id)


# ---------------------------------------------------------------- API pública
def listar():
    """Entradas de la papelera, la más reciente primero."""
    if LINUX:
        entradas = _listar_linux()
    elif MAC:
        entradas = _listar_mac()
    else:
        raise NotImplementedError(aviso_no_soportado("ver la papelera"))
    entradas.sort(key=lambda e: (e.fecha or datetime.datetime.min, e.nombre), reverse=True)
    return entradas


def restaurar(e: Entrada) -> str:
    """Devuelve la entrada a su lugar y retorna la ruta final."""
    if not LINUX:
        raise NotImplementedError(aviso_no_soportado("restaurar"))
    return _restaurar_linux(e)


def borrar_definitivo(e: Entrada) -> None:
    """Elimina la entrada para siempre."""
    if LINUX:
        _borrar_linux(e)
    elif MAC:
        _borrar_mac(e)
    else:
        raise NotImplementedError(aviso_no_soportado("borrar definitivamente"))
