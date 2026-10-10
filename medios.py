"""
Imágenes y video: generar (IA) y editar (IA + ffmpeg).

Este módulo NO decide rutas: recibe destinos ya validados por rutas.resolver_ruta()
(tools.py se encarga). Todo acceso a disco de entrada/salida pasa por esas rutas permitidas.

IMÁGENES (generar / editar con IA): proveedores en config.IMAGEN_PROVEEDORES, se prueban en orden
y se saltan los que no tienen clave:
    pollinations  gratis, sin clave (puede cambiar o limitar)
    openai        OPENAI_API_KEY   (gpt-image-1: genera y EDITA con instrucciones)
    huggingface   HF_TOKEN         (FLUX u otro modelo)
    local_sd      Stable Diffusion local (AUTOMATIC1111 con --api) en LOCAL_SD_URL: genera y edita (img2img)
VIDEO IA: Replicate (REPLICATE_API_TOKEN), de pago por uso; el modelo se cambia en config.
VIDEO LOCAL (gratis, sin IA): animar una imagen (zoom/paneo) y armar videos con varias imágenes.
EDITAR VIDEO: ffmpeg (cortar, unir, velocidad, texto, audio, rotar, GIF...).
"""
import base64
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse

import requests

import config


class ProveedorFallo(Exception):
    """Un proveedor no pudo atender (sin clave, límite, error...). Se prueba el siguiente."""


# =============================================================== utilidades
def _bytes_a_png(datos: bytes, destino: str):
    """Valida que sean los bytes de una imagen real y la guarda (el formato sale de la extensión)."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except Exception:
        raise ProveedorFallo("la respuesta no era una imagen válida")
    ext = os.path.splitext(destino)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img = img.convert("RGB")
        img.save(destino, quality=92)
    else:
        img.save(destino)


def _post(url, **kw):
    kw.setdefault("timeout", config.IMAGEN_TIMEOUT)
    try:
        r = requests.post(url, **kw)
    except requests.exceptions.Timeout:
        raise ProveedorFallo("tardó demasiado")
    except requests.exceptions.RequestException as e:
        raise ProveedorFallo(f"sin conexión ({e.__class__.__name__})")
    _revisar(r)
    return r


def _revisar(r):
    if r.status_code in (401, 403):
        raise ProveedorFallo("clave rechazada o sin permiso")
    if r.status_code == 402:
        raise ProveedorFallo("sin saldo")
    if r.status_code == 429:
        raise ProveedorFallo("límite de uso")
    if r.status_code >= 400:
        raise ProveedorFallo(f"error {r.status_code}: {(r.text or '')[:140]}")


def _b64_o_url(item: dict) -> bytes:
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        try:
            return requests.get(item["url"], timeout=config.IMAGEN_TIMEOUT).content
        except requests.exceptions.RequestException as e:
            raise ProveedorFallo(f"no pude descargar la imagen ({e.__class__.__name__})")
    raise ProveedorFallo("respuesta sin imagen")


# =================================================== generar imagen (proveedores)
def _img_pollinations(prompt, ancho, alto):
    url = f"{config.POLLINATIONS_URL}/{urllib.parse.quote(prompt)}"
    try:
        r = requests.get(url, params={"width": ancho, "height": alto, "model": config.POLLINATIONS_MODEL,
                                      "nologo": "true", "private": "true", "seed": int(time.time()) % 100000},
                         timeout=config.IMAGEN_TIMEOUT)
    except requests.exceptions.Timeout:
        raise ProveedorFallo("tardó demasiado")
    except requests.exceptions.RequestException as e:
        raise ProveedorFallo(f"sin conexión ({e.__class__.__name__})")
    _revisar(r)
    if "image" not in r.headers.get("Content-Type", "image"):
        raise ProveedorFallo("no devolvió una imagen")
    return r.content


def _img_openai(prompt, ancho, alto):
    clave = os.environ.get("OPENAI_API_KEY")
    if not clave:
        raise ProveedorFallo("falta OPENAI_API_KEY")
    tam = "1024x1024" if abs(ancho - alto) < 200 else ("1536x1024" if ancho > alto else "1024x1536")
    r = _post(f"{config.OPENAI_URL}/images/generations",
              headers={"Authorization": f"Bearer {clave}"},
              json={"model": config.OPENAI_IMAGE_MODEL, "prompt": prompt, "size": tam, "n": 1})
    return _b64_o_url(r.json()["data"][0])


def _img_huggingface(prompt, ancho, alto):
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise ProveedorFallo("falta HF_TOKEN")
    r = _post(config.HF_IMAGE_URL.format(modelo=config.HF_IMAGE_MODEL),
              headers={"Authorization": f"Bearer {token}"},
              json={"inputs": prompt, "parameters": {"width": ancho, "height": alto}})
    return r.content


def _img_local_sd(prompt, ancho, alto):
    r = _post(f"{config.LOCAL_SD_URL}/sdapi/v1/txt2img",
              json={"prompt": prompt, "width": min(ancho, 1024), "height": min(alto, 1024), "steps": 25},
              timeout=config.LOCAL_SD_TIMEOUT)
    return base64.b64decode(r.json()["images"][0])


_GENERADORES = {"pollinations": _img_pollinations, "openai": _img_openai,
                "huggingface": _img_huggingface, "local_sd": _img_local_sd}


def generar_imagen(prompt: str, destino: str, ancho: int = 1024, alto: int = 1024) -> str:
    """Genera una imagen y la guarda en 'destino'. Devuelve el nombre del proveedor que la hizo."""
    fallos = []
    for nombre in config.IMAGEN_PROVEEDORES:
        fn = _GENERADORES.get(nombre)
        if not fn:
            continue
        try:
            _bytes_a_png(fn(prompt, ancho, alto), destino)
            return nombre
        except ProveedorFallo as e:
            fallos.append(f"{nombre}: {e}")
        except Exception as e:
            fallos.append(f"{nombre}: {e.__class__.__name__}")
    raise RuntimeError("; ".join(fallos) or "no hay proveedores de imagen configurados")


# ============================================ editar imagen con IA (instrucción)
def _edit_openai(origen, instruccion):
    clave = os.environ.get("OPENAI_API_KEY")
    if not clave:
        raise ProveedorFallo("falta OPENAI_API_KEY")
    with open(origen, "rb") as f:
        r = _post(f"{config.OPENAI_URL}/images/edits", headers={"Authorization": f"Bearer {clave}"},
                  data={"model": config.OPENAI_IMAGE_MODEL, "prompt": instruccion},
                  files={"image": (os.path.basename(origen), f, "image/png")})
    return _b64_o_url(r.json()["data"][0])


def _edit_local_sd(origen, instruccion):
    with open(origen, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    r = _post(f"{config.LOCAL_SD_URL}/sdapi/v1/img2img",
              json={"init_images": [b64], "prompt": instruccion, "denoising_strength": 0.5, "steps": 25},
              timeout=config.LOCAL_SD_TIMEOUT)
    return base64.b64decode(r.json()["images"][0])


_EDITORES = {"openai": _edit_openai, "local_sd": _edit_local_sd}


def editar_imagen_ia(origen: str, instruccion: str, destino: str) -> str:
    fallos = []
    for nombre in config.IMAGEN_PROVEEDORES:
        fn = _EDITORES.get(nombre)
        if not fn:
            continue
        try:
            _bytes_a_png(fn(origen, instruccion), destino)
            return nombre
        except ProveedorFallo as e:
            fallos.append(f"{nombre}: {e}")
        except Exception as e:
            fallos.append(f"{nombre}: {e.__class__.__name__}")
    if not fallos:
        raise RuntimeError("para editar con IA hace falta OPENAI_API_KEY o Stable Diffusion local "
                           "(pon 'openai' o 'local_sd' en IMAGEN_PROVEEDORES)")
    raise RuntimeError("; ".join(fallos))


# ==================================================================== ffmpeg
def ffmpeg_exe():
    """ffmpeg del sistema, o el que trae el paquete imageio-ffmpeg (no hace falta instalarlo aparte)."""
    ruta = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
    if ruta:
        return ruta
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


_SIN_FFMPEG = ("No encuentro ffmpeg. Instálalo con «sudo apt install ffmpeg» o con "
               "«pip install imageio-ffmpeg» y vuelve a intentarlo.")


def _correr(args, timeout=1800):
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError(_SIN_FFMPEG)
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error"] + [str(a) for a in args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg tardó demasiado y lo detuve")
    if r.returncode != 0:
        raise RuntimeError("ffmpeg falló: " + (r.stderr or "").strip().splitlines()[-1][:300]
                           if (r.stderr or "").strip() else "ffmpeg falló")


def _info_cruda(ruta):
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError(_SIN_FFMPEG)
    r = subprocess.run([exe, "-hide_banner", "-i", ruta], capture_output=True, text=True, timeout=60)
    return r.stderr or ""


def info_video(ruta: str) -> dict:
    txt = _info_cruda(ruta)
    d = {"duracion": None, "ancho": None, "alto": None, "fps": None, "audio": "Audio:" in txt, "video": "Video:" in txt}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", txt)
    if m:
        d["duracion"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", txt)
    if m:
        d["ancho"], d["alto"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"([\d.]+) fps", txt)
    if m:
        d["fps"] = float(m.group(1))
    return d


def describir_video(ruta: str) -> str:
    d = info_video(ruta)
    if not d["video"] and not d["audio"]:
        return "No parece un archivo de video/audio válido."
    peso = os.path.getsize(ruta) / 1_048_576
    partes = [f"{os.path.basename(ruta)}: {peso:.1f} MB"]
    if d["duracion"] is not None:
        partes.append(f"{d['duracion']:.1f} s")
    if d["ancho"]:
        partes.append(f"{d['ancho']}x{d['alto']}")
    if d["fps"]:
        partes.append(f"{d['fps']:g} fps")
    partes.append("con audio" if d["audio"] else "sin audio")
    return ", ".join(partes)


def _seg(valor):
    """5, '5.5', '01:30' o '00:01:30' -> segundos."""
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip().replace(",", ".")
    if ":" in txt:
        total = 0.0
        for p in txt.split(":"):
            total = total * 60 + float(p)
        return total
    return float(txt)


def _fuente():
    for c in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf"):
        if os.path.isfile(c):
            return c
    return None


def _cadena_atempo(v):
    """atempo solo admite 0.5-2.0 por filtro: se encadenan."""
    partes = []
    while v > 2.0:
        partes.append("atempo=2.0"); v /= 2.0
    while v < 0.5:
        partes.append("atempo=0.5"); v /= 0.5
    partes.append(f"atempo={v:.4f}")
    return ",".join(partes)


def editar_video(origen: str, destino: str, *, inicio=None, fin=None, velocidad=None, quitar_audio=False,
                 audio=None, volumen=None, texto=None, posicion_texto="abajo", ancho=None, alto=None,
                 rotar=None, voltear=None, blanco_y_negro=False, brillo=None, fps=None, formato=None) -> str:
    """Aplica en UNA pasada lo pedido. Devuelve un resumen de lo aplicado."""
    ini, fi = _seg(inicio), _seg(fin)
    if ini is not None and fi is not None and fi <= ini:
        raise RuntimeError("el 'fin' debe ser mayor que el 'inicio'")
    ext = os.path.splitext(destino)[1].lower()
    fmt = (formato or ext.lstrip(".")).lower()
    aplicado = []
    entrada = []
    if ini is not None:
        entrada += ["-ss", ini]; aplicado.append(f"desde {ini:g}s")
    entrada += ["-i", origen]
    if audio:
        entrada += ["-i", audio]
    salida = []
    if fi is not None:
        salida += ["-t", (fi - (ini or 0))]; aplicado.append(f"hasta {fi:g}s")

    if fmt in ("mp3", "wav", "m4a", "aac", "ogg"):       # solo extraer el audio
        salida += ["-vn"]
        if fmt == "mp3":
            salida += ["-q:a", 2]
        _correr(entrada + salida + [destino])
        return "audio extraído"

    vf, af = [], []
    if rotar:
        r = int(rotar) % 360
        vf.append({90: "transpose=1", 180: "transpose=1,transpose=1", 270: "transpose=2"}.get(r) or "null")
        aplicado.append(f"rotado {r}°")
    if voltear:
        vf.append("hflip" if str(voltear).startswith("h") else "vflip"); aplicado.append(f"volteado {voltear}")
    if ancho or alto:
        vf.append(f"scale={int(ancho) if ancho else -2}:{int(alto) if alto else -2}"); aplicado.append("redimensionado")
    if blanco_y_negro:
        vf.append("hue=s=0"); aplicado.append("blanco y negro")
    if brillo is not None:
        vf.append(f"eq=brightness={max(-1.0, min(1.0, float(brillo) - 1.0)):.2f}"); aplicado.append("brillo")
    if velocidad and float(velocidad) != 1.0:
        v = float(velocidad)
        if not 0.1 <= v <= 16:
            raise RuntimeError("la velocidad debe estar entre 0.1 y 16")
        vf.append(f"setpts=PTS/{v:.4f}"); af.append(_cadena_atempo(v)); aplicado.append(f"velocidad x{v:g}")
    archivo_texto = None
    if texto:
        fnt = _fuente()
        fd, archivo_texto = tempfile.mkstemp(suffix=".txt", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        y = {"arriba": "h*0.06", "centro": "(h-text_h)/2"}.get(posicion_texto, "h-text_h-h*0.06")
        esc = lambda s: s.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        dt = f"drawtext=textfile='{esc(archivo_texto)}':fontcolor=white:fontsize=h/18:borderw=3:bordercolor=black:x=(w-text_w)/2:y={y}"
        if fnt:
            dt += f":fontfile='{esc(fnt)}'"
        vf.append(dt); aplicado.append("texto")
    if fps and fmt != "gif":
        vf.append(f"fps={int(fps)}")
    if volumen is not None and not quitar_audio:
        af.append(f"volume={float(volumen):g}"); aplicado.append(f"volumen x{float(volumen):g}")

    args = list(entrada)
    if fmt == "gif":
        vf += ["fps=12", "scale='min(480,iw)':-2:flags=lanczos"]
        aplicado.append("GIF")
        args += salida + ["-vf", ",".join(vf), "-an", "-loop", 0, destino]
        try:
            _correr(args)
        finally:
            if archivo_texto and os.path.exists(archivo_texto):
                os.remove(archivo_texto)
        return ", ".join(aplicado) or "convertido"

    if vf:
        args += ["-vf", ",".join(vf)]
    if audio:                                      # el audio nuevo reemplaza al original
        args += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]; aplicado.append("audio agregado")
        if af:
            args += ["-af", ",".join(af)]
    elif quitar_audio:
        args += ["-an"]; aplicado.append("sin audio")
    elif af and info_video(origen)["audio"]:
        args += ["-af", ",".join(af)]
    args += salida
    if fmt == "webm":
        args += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", 32]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", 23, "-pix_fmt", "yuv420p", "-c:a", "aac"]
    args += [destino]
    try:
        _correr(args)
    finally:
        if archivo_texto and os.path.exists(archivo_texto):
            os.remove(archivo_texto)
    return ", ".join(aplicado) or "convertido"


def unir_videos(origenes: list, destino: str):
    """Une varios videos (aunque tengan distinta resolución o alguno no tenga audio)."""
    if len(origenes) < 2:
        raise RuntimeError("necesito al menos 2 videos para unir")
    d0 = info_video(origenes[0])
    w, h = (d0["ancho"] or 1280), (d0["alto"] or 720)
    w, h = w - w % 2, h - h % 2
    tmp = tempfile.mkdtemp(prefix="jarvis_unir_")
    try:
        normalizados = []
        for i, o in enumerate(origenes):
            salida = os.path.join(tmp, f"{i:03d}.mp4")
            tiene_audio = info_video(o)["audio"]
            filtro = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                      f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v]")
            args = ["-i", o]
            if tiene_audio:
                args += ["-filter_complex", filtro, "-map", "[v]", "-map", "0:a:0"]
            else:
                args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex", filtro,
                         "-map", "[v]", "-map", "1:a:0", "-shortest"]
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", 23, "-c:a", "aac", "-ar", 44100, "-ac", 2, salida]
            _correr(args)
            normalizados.append(salida)
        lista = os.path.join(tmp, "lista.txt")
        with open(lista, "w", encoding="utf-8") as f:
            for n in normalizados:
                f.write(f"file '{n}'\n")
        _correr(["-f", "concat", "-safe", 0, "-i", lista, "-c", "copy", destino])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ====================================================== video desde imágenes (local)
_EFECTOS = ("acercar", "alejar", "panoramica")


def animar_imagen(origen: str, destino: str, segundos: float = 5, efecto: str = "acercar", audio: str = None):
    """Convierte UNA imagen en un video con movimiento de cámara suave (zoom/paneo). Local y gratis."""
    segundos = max(1.0, min(float(segundos or 5), 60.0))
    efecto = efecto if efecto in _EFECTOS else "acercar"
    fps = 30
    n = int(segundos * fps)
    if efecto == "alejar":
        z = "if(eq(on,0),1.3,max(zoom-0.0009,1.0))"; xy = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif efecto == "panoramica":
        z = "1.25"; xy = f"x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'"
    else:
        z = "min(zoom+0.0009,1.3)"; xy = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    vf = (f"scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,"
          f"zoompan=z='{z}':{xy}:d={n}:s=1280x720:fps={fps},format=yuv420p")
    args = ["-loop", 1, "-i", origen]
    if audio:
        args += ["-i", audio]
    args += ["-vf", vf, "-t", segundos]
    if audio:
        args += ["-map", "0:v:0", "-map", "1:a:0", "-shortest", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", 23, "-pix_fmt", "yuv420p", destino]
    _correr(args)


def video_desde_imagenes(imagenes: list, destino: str, segundos_por_imagen: float = 4, audio: str = None):
    if not imagenes:
        raise RuntimeError("no hay imágenes")
    tmp = tempfile.mkdtemp(prefix="jarvis_vid_")
    try:
        clips = []
        for i, img in enumerate(imagenes):
            c = os.path.join(tmp, f"{i:03d}.mp4")
            animar_imagen(img, c, segundos_por_imagen, _EFECTOS[i % len(_EFECTOS)])
            clips.append(c)
        final = destino
        if len(clips) == 1:
            shutil.copy(clips[0], final)
        else:
            unir_videos(clips, final)
        if audio:
            con_audio = os.path.join(tmp, "audio.mp4")
            _correr(["-i", final, "-i", audio, "-map", "0:v:0", "-map", "1:a:0", "-shortest",
                     "-c:v", "copy", "-c:a", "aac", con_audio])
            shutil.copy(con_audio, final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ video con IA (Replicate)
def generar_video_ia(prompt: str, destino: str, imagen: str = None, segundos: float = 5) -> str:
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise RuntimeError("falta REPLICATE_API_TOKEN")
    modelo = config.REPLICATE_VIDEO_I2V_MODEL if imagen else config.REPLICATE_VIDEO_MODEL
    entrada = {"prompt": prompt}
    if imagen:
        with open(imagen, "rb") as f:
            entrada["image"] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    cab = {"Authorization": f"Bearer {token}", "Prefer": "wait=30"}
    try:
        r = _post(f"{config.REPLICATE_URL}/models/{modelo}/predictions", headers=cab,
                  json={"input": entrada}, timeout=60)
        pred = r.json()
        limite = time.time() + config.VIDEO_TIMEOUT
        while pred.get("status") not in ("succeeded", "failed", "canceled"):
            if time.time() > limite:
                raise RuntimeError(f"la generación tardó más de {config.VIDEO_TIMEOUT // 60} min y la dejé")
            time.sleep(config.VIDEO_POLL_SEG)
            rr = requests.get(pred["urls"]["get"], headers={"Authorization": f"Bearer {token}"}, timeout=30)
            _revisar(rr)
            pred = rr.json()
    except ProveedorFallo as e:
        raise RuntimeError(f"replicate: {e}")
    if pred.get("status") != "succeeded":
        raise RuntimeError(f"replicate: {str(pred.get('error') or pred.get('status'))[:200]}")
    salida = pred.get("output")
    url = salida[0] if isinstance(salida, list) and salida else salida
    if not isinstance(url, str):
        raise RuntimeError("replicate no devolvió un video")
    try:
        datos = requests.get(url, timeout=300).content
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"no pude descargar el video ({e.__class__.__name__})")
    with open(destino, "wb") as f:
        f.write(datos)
    return f"replicate:{modelo}"
