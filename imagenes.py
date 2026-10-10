"""
Fotos: inspeccionar, editar (siempre guardando una copia nueva salvo que se pida
sobrescribir, y con respaldo) y preparar imágenes para que el modelo las 'vea'.
"""
import io
import os

import numpy as np
from PIL import ExifTags, Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import rutas

EXTENSIONES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif")
_FORMATOS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


def abrir(destino: str) -> Image.Image:
    img = Image.open(destino)
    img = ImageOps.exif_transpose(img)   # respeta la rotación de las fotos de celular
    return img


def preparar_para_modelo(img: Image.Image, lado_max: int = 1568) -> tuple[bytes, str]:
    """Reduce y comprime a JPEG para enviarla al modelo de visión. Devuelve (bytes, media_type)."""
    img = img.convert("RGB")
    img.thumbnail((lado_max, lado_max))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def inspeccionar(destino: str) -> str:
    """Datos técnicos y de calidad de la foto (sin usar IA)."""
    try:
        img = Image.open(destino)
        formato, modo = img.format, img.mode
        exif = img.getexif()
        img = ImageOps.exif_transpose(img)
        ancho, alto = img.size
        rgb = img.convert("RGB")
    except Exception as e:
        return f"No pude abrir la imagen: {e}"

    tamano_kb = os.path.getsize(destino) / 1024
    partes = [f"{ancho}x{alto} píxeles ({ancho * alto / 1e6:.1f} megapíxeles), formato {formato}, "
              f"modo {modo}, {tamano_kb:.0f} KB."]

    gris = np.asarray(rgb.convert("L").resize((min(ancho, 512), min(alto, 512))), dtype=np.float32)
    brillo = float(gris.mean())
    nivel = "muy oscura" if brillo < 60 else "algo oscura" if brillo < 95 else \
            "muy clara/sobreexpuesta" if brillo > 200 else "con buena exposición"
    # nitidez: varianza del cambio entre píxeles vecinos (heurística simple)
    dx, dy = np.diff(gris, axis=1), np.diff(gris, axis=0)
    nitidez = float(dx.var() + dy.var())
    nit = "borrosa" if nitidez < 40 else "poco nítida" if nitidez < 120 else "nítida"
    partes.append(f"Brillo medio {brillo:.0f}/255 ({nivel}); se ve {nit} (índice {nitidez:.0f}).")

    try:
        pal = rgb.resize((64, 64)).quantize(5)
        colores = pal.getpalette()[:15]
        cuentas = sorted(pal.getcolors(), reverse=True)
        dom = [f"#{colores[i*3]:02x}{colores[i*3+1]:02x}{colores[i*3+2]:02x}" for _, i in cuentas[:3]]
        partes.append("Colores dominantes: " + ", ".join(dom) + ".")
    except Exception:
        pass

    nombres = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    datos = [f"{k}: {nombres[k]}" for k in ("Make", "Model", "DateTime") if nombres.get(k)]
    if datos:
        partes.append("Metadatos: " + "; ".join(str(d) for d in datos) + ".")
    if exif.get_ifd(0x8825):
        partes.append("Contiene ubicación GPS en sus metadatos (cuidado si la vas a compartir).")
    return " ".join(partes)


def _fuente(tamano: int):
    for nombre in ("DejaVuSans-Bold.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            continue
    return ImageFont.load_default()


def editar(origen: str, destino_dir_resolver, **p) -> str:
    """
    Aplica los cambios pedidos en este orden fijo: recortar, rotar, voltear,
    redimensionar, color (brillo/contraste/saturación/nitidez), blanco y negro,
    desenfoque, texto. Guarda en un archivo nuevo (o sobrescribe con respaldo).
    """
    try:
        img = abrir(origen)
    except Exception as e:
        return f"No pude abrir la imagen: {e}"
    hechos = []

    caja = p.get("recortar")
    if caja:
        if len(caja) != 4:
            return "Para recortar necesito 4 números: izquierda, arriba, derecha, abajo (en píxeles)."
        izq, arr, der, aba = (int(v) for v in caja)
        izq, arr = max(0, izq), max(0, arr)
        der, aba = min(img.width, der), min(img.height, aba)
        if der <= izq or aba <= arr:
            return f"Recorte inválido para una imagen de {img.width}x{img.height}."
        img = img.crop((izq, arr, der, aba))
        hechos.append("recortada")

    if p.get("rotar"):
        img = img.rotate(-float(p["rotar"]), expand=True)   # positivo = sentido del reloj
        hechos.append(f"rotada {p['rotar']}°")
    if p.get("voltear") == "horizontal":
        img = ImageOps.mirror(img); hechos.append("volteada horizontal")
    elif p.get("voltear") == "vertical":
        img = ImageOps.flip(img); hechos.append("volteada vertical")

    ancho, alto = p.get("ancho"), p.get("alto")
    if ancho or alto:
        if ancho and not alto:
            alto = round(img.height * int(ancho) / img.width)
        elif alto and not ancho:
            ancho = round(img.width * int(alto) / img.height)
        ancho, alto = int(ancho), int(alto)
        if not (0 < ancho <= 12000 and 0 < alto <= 12000):
            return "Tamaño fuera de rango (máximo 12000 píxeles por lado)."
        img = img.resize((ancho, alto), Image.LANCZOS)
        hechos.append(f"redimensionada a {ancho}x{alto}")

    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    for clave, clase, etiqueta in (("brillo", ImageEnhance.Brightness, "brillo"),
                                   ("contraste", ImageEnhance.Contrast, "contraste"),
                                   ("saturacion", ImageEnhance.Color, "saturación"),
                                   ("nitidez", ImageEnhance.Sharpness, "nitidez")):
        if p.get(clave) not in (None, 1, 1.0):
            img = clase(img).enhance(float(p[clave])); hechos.append(f"{etiqueta} x{p[clave]}")
    if p.get("blanco_y_negro"):
        img = ImageOps.grayscale(img).convert("RGB"); hechos.append("blanco y negro")
    if p.get("desenfoque"):
        img = img.filter(ImageFilter.GaussianBlur(float(p["desenfoque"]))); hechos.append("desenfocada")

    if p.get("texto"):
        img = img.convert("RGB")
        dib = ImageDraw.Draw(img)
        fuente = _fuente(max(16, img.width // 18))
        caja_t = dib.textbbox((0, 0), p["texto"], font=fuente)
        tw, th = caja_t[2] - caja_t[0], caja_t[3] - caja_t[1]
        pos = p.get("posicion_texto", "abajo")
        x = (img.width - tw) // 2
        y = {"arriba": 20, "centro": (img.height - th) // 2}.get(pos, img.height - th - 30)
        dib.text((x, y), p["texto"], font=fuente, fill="white", stroke_width=max(2, img.width // 400),
                 stroke_fill="black")
        hechos.append("texto agregado")

    if not hechos:
        return "No indicaste ningún cambio para aplicar."

    fmt_pedido = (p.get("formato") or "").lower().lstrip(".")
    base, ext_orig = os.path.splitext(origen)
    ext = "." + (fmt_pedido if fmt_pedido in _FORMATOS else ext_orig.lstrip(".").lower())
    if ext.lstrip(".") not in _FORMATOS:          # gif, bmp, tiff... se guardan como PNG
        ext = ".png"
    formato = _FORMATOS[ext.lstrip(".")]
    if p.get("sobrescribir") and ext == ext_orig.lower():
        salida = origen
        respaldo = rutas.respaldar(origen)
    else:
        salida = destino_dir_resolver(p.get("nombre_salida"), base, ext)
        respaldo = None
        if salida is None:
            return "No tengo permiso para guardar ahí."

    if formato == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")
    try:
        img.save(salida, format=formato, **({"quality": 92} if formato in ("JPEG", "WEBP") else {}))
    except Exception as e:
        return f"No pude guardar la imagen: {e}"
    extra = f" (respaldo del original en {respaldo})" if respaldo else ""
    return f"Listo: imagen {', '.join(hechos)}. Guardada en {salida}{extra}"
