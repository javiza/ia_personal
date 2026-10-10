"""
Genera los avatares ANIMADOS (GIF) de la peliroja a partir de assets/pelirroja_original.png.

  python3 crear_avatar_gifs.py

Crea en assets/:
  avatar.png             imagen fija (recorte de la cara)
  avatar_reposo.gif      flota suave
  avatar_escuchando.gif  se inclina hacia ti, con ondas de sonido
  avatar_pensando.gif    cabeza ladeada + nube de pensamiento con puntitos que se encienden
  avatar_hablando.gif    rebota al ritmo de la voz
Además crea las versiones LIVIANAS para el celular en web/img/ (GIFs de 240 px e iconos de la app instalable).
avatar_ui.py los usa solos (uno por estado). Si cambias la imagen original, vuelve a correr este script.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

AQUI = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(AQUI, "assets")
ORIGINAL = os.path.join(ASSETS, "pelirroja_original.png")
LADO = 320            # px de cada cuadro (el avatar en pantalla mide 150; así se ve nítido en pantallas HiDPI)
FRAMES = 30
MS = 45               # ms por cuadro


def _preparar() -> Image.Image:
    """Recorta cara + torso (y deja fuera la marca de agua de abajo a la derecha) y quita la marca por si acaso."""
    im = Image.open(ORIGINAL).convert("RGB")
    # La marca de agua está en y > 730; este recorte (0..640) ya la excluye.
    caja = (170, 0, 770, 600)
    return im.crop(caja).resize((LADO * 2, LADO * 2), Image.LANCZOS)   # el doble: se reduce al final (suaviza)


def _transformar(base: Image.Image, dx=0.0, dy=0.0, giro=0.0, escala=1.0, centro=(0.58, 0.42)) -> Image.Image:
    """Mueve / gira / escala la imagen sobre su propio fondo, girando alrededor de la cabeza."""
    w, h = base.size
    cx, cy = centro[0] * w, centro[1] * h
    # escala (relativa al centro de la cabeza)
    if escala != 1.0:
        base = base.resize((int(w * escala), int(h * escala)), Image.BICUBIC)
        cx, cy = cx * escala, cy * escala
    # giro alrededor de la cabeza
    base = base.rotate(giro, resample=Image.BICUBIC, center=(cx, cy), fillcolor=(160, 150, 205))
    # volver a un cuadro w×h, con la cabeza en su sitio + desplazamiento
    lienzo = Image.new("RGB", (w, h), (160, 150, 205))
    lienzo.paste(base, (int(centro[0] * w - cx + dx), int(centro[1] * h - cy + dy)))
    return lienzo


def _nube(dibujo: ImageDraw.ImageDraw, w, t, puntos_encendidos):
    """Nube de pensamiento arriba a la izquierda, con el rastro de burbujitas hacia la cabeza."""
    cx, cy = 0.245 * w, 0.185 * w
    a = 0.135 * w     # semieje horizontal
    b = 0.088 * w
    relleno, borde = (255, 255, 255, 235), (120, 105, 175, 255)
    # rastro de burbujas
    for k, (fx, fy, r) in enumerate([(0.345, 0.295, 0.014), (0.385, 0.345, 0.022)]):
        dibujo.ellipse([fx * w - r * w, fy * w - r * w, fx * w + r * w, fy * w + r * w], fill=relleno, outline=borde, width=3)
    # cuerpo de la nube = varios círculos
    for ox, oy, r in [(-0.7, 0.1, 0.62), (-0.25, -0.5, 0.7), (0.35, -0.45, 0.72), (0.75, 0.05, 0.62), (0.0, 0.35, 0.7)]:
        x, y, rr = cx + ox * a, cy + oy * b, r * b
        dibujo.ellipse([x - rr, y - rr, x + rr, y + rr], fill=borde)
    for ox, oy, r in [(-0.7, 0.1, 0.62), (-0.25, -0.5, 0.7), (0.35, -0.45, 0.72), (0.75, 0.05, 0.62), (0.0, 0.35, 0.7)]:
        x, y, rr = cx + ox * a, cy + oy * b, r * b - 4
        dibujo.ellipse([x - rr, y - rr, x + rr, y + rr], fill=relleno)
    # tres puntitos que se encienden uno a uno (· · ·)
    for i in range(3):
        encendido = i < puntos_encendidos
        px = cx + (i - 1) * 0.075 * w
        salto = -0.012 * w * math.sin(max(0.0, (t * 3 - i * 0.55)) * math.pi) if encendido else 0
        r = 0.021 * w
        col = (251, 160, 36, 255) if encendido else (200, 195, 225, 255)
        dibujo.ellipse([px - r, cy - r + salto, px + r, cy + r + salto], fill=col)


def _ondas(dibujo, w, t, lado):
    """Ondas de sonido (escuchando)."""
    cx, cy = (0.07 if lado == "izq" else 0.93) * w, 0.40 * w
    for i in range(3):
        fase = (t * 2 + i * 0.33) % 1.0
        r = (0.03 + 0.09 * fase) * w
        alfa = int(255 * (1 - fase))
        dibujo.arc([cx - r, cy - r, cx + r, cy + r], -50 if lado == "izq" else 130, 50 if lado == "izq" else 230,
                   fill=(74, 222, 128, alfa), width=5)


def _cuadros(estado: str, base: Image.Image) -> list[Image.Image]:
    salida = []
    for n in range(FRAMES):
        t = n / FRAMES                       # 0..1 (bucle perfecto: todo usa 2π·t o múltiplos)
        s = math.sin(2 * math.pi * t)
        c = math.cos(2 * math.pi * t)
        if estado == "reposo":
            im = _transformar(base, dy=6 * s, giro=1.2 * s, escala=1.0 + 0.012 * s)
        elif estado == "escuchando":
            im = _transformar(base, dx=-8 + 3 * s, dy=3 * c, giro=-4 + 1.5 * s, escala=1.03)
        elif estado == "pensando":
            # cabeza ladeada que cabecea despacio, como dudando
            im = _transformar(base, dx=-6, dy=5 * s, giro=-6 + 3.2 * s, escala=1.03)
        else:  # hablando
            rebote = abs(math.sin(2 * math.pi * t * 3))
            im = _transformar(base, dy=-10 * rebote, giro=1.8 * math.sin(2 * math.pi * t * 3 + 1), escala=1.0 + 0.025 * rebote)
        im = im.resize((LADO, LADO), Image.LANCZOS).convert("RGBA")

        capa = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)
        if estado == "pensando":
            _nube(d, LADO, t, 1 + int(t * 3.999))          # 1,2,3 puntitos y vuelve a empezar
        elif estado == "escuchando":
            _ondas(d, LADO, t, "izq")
        im = Image.alpha_composite(im, capa)
        salida.append(im.convert("RGB"))
    return salida


def _guardar_gif(cuadros, ruta, colores=200):
    # Paleta común (un solo juego de colores) = archivo más chico y sin parpadeos entre cuadros.
    maestro = cuadros[0].quantize(colors=colores, method=Image.MEDIANCUT)
    paleta = [c.quantize(palette=maestro, dither=Image.Dither.NONE) for c in cuadros]
    paleta[0].save(ruta, save_all=True, append_images=paleta[1:], duration=MS, loop=0, optimize=False, disposal=1)


def _iconos(base: Image.Image, carpeta: str):
    """Iconos de la app instalable (PWA): normal, «maskable» (con margen, Android recorta la forma) y el de iPhone."""
    fondo = (11, 18, 34)
    def icono(lado, relleno):
        lienzo = Image.new("RGB", (lado, lado), fondo)
        foto = base.resize((int(lado * relleno), int(lado * relleno)), Image.LANCZOS)
        mascara = Image.new("L", foto.size, 0)
        ImageDraw.Draw(mascara).ellipse([0, 0, foto.size[0] - 1, foto.size[1] - 1], fill=255)
        pos = ((lado - foto.size[0]) // 2, (lado - foto.size[1]) // 2)
        lienzo.paste(foto, pos, mascara)
        return lienzo
    icono(192, 0.92).save(os.path.join(carpeta, "icon-192.png"))
    icono(512, 0.92).save(os.path.join(carpeta, "icon-512.png"))
    icono(512, 0.70).save(os.path.join(carpeta, "icon-maskable-512.png"))
    icono(180, 0.92).save(os.path.join(carpeta, "apple-touch-icon.png"))


def exportar_web(base_hd: Image.Image):
    """GIFs livianos (240 px, 24 cuadros) para el celular: unos 300–500 KB cada uno en vez de 1,3 MB."""
    global LADO, FRAMES
    carpeta = os.path.join(AQUI, "web", "img")
    os.makedirs(carpeta, exist_ok=True)
    guardado = (LADO, FRAMES)
    LADO, FRAMES = 240, 24
    try:
        base = base_hd.resize((LADO * 2, LADO * 2), Image.LANCZOS)
        for estado in ("reposo", "escuchando", "pensando", "hablando"):
            ruta = os.path.join(carpeta, f"avatar_{estado}.gif")
            _guardar_gif(_cuadros(estado, base), ruta, colores=96)
            print(f"✓ {ruta}  ({os.path.getsize(ruta) // 1024} KB)")
    finally:
        LADO, FRAMES = guardado
    _iconos(base_hd, carpeta)
    print("✓ iconos de la app (web/img)")


def main():
    base = _preparar()
    # imagen fija (usada si no hay GIF y como respaldo)
    base.resize((512, 512), Image.LANCZOS).save(os.path.join(ASSETS, "avatar.png"))
    for estado in ("reposo", "escuchando", "pensando", "hablando"):
        ruta = os.path.join(ASSETS, f"avatar_{estado}.gif")
        _guardar_gif(_cuadros(estado, base), ruta)
        print(f"✓ {ruta}  ({os.path.getsize(ruta) // 1024} KB)")
    exportar_web(base)


if __name__ == "__main__":
    main()
