"""
Diagnóstico de generación de imágenes: prueba CADA proveedor por separado y dice por qué falla.
Uso (con tu entorno): ./venv/bin/python probar_imagen.py        (o:  python3 probar_imagen.py)
"""
import os
import sys
import tempfile

import config
import medios

print("Orden de proveedores:", ", ".join(config.IMAGEN_PROVEEDORES))
print("Claves: OPENAI_API_KEY", "sí" if os.environ.get("OPENAI_API_KEY") else "NO",
      "| HF_TOKEN", "sí" if os.environ.get("HF_TOKEN") else "NO",
      "| POLLINATIONS_KEY", "sí" if os.environ.get("POLLINATIONS_KEY") else "no (opcional)")
print()
bien = []
for nombre in config.IMAGEN_PROVEEDORES:
    fn = medios._GENERADORES.get(nombre)
    if not fn:
        continue
    destino = os.path.join(tempfile.gettempdir(), f"prueba_{nombre}.png")
    print(f"→ {nombre} …", end=" ", flush=True)
    try:
        medios._bytes_a_png(fn("a cute green alien, simple drawing, white background", 512, 512), destino)
        print(f"OK  ({destino})")
        bien.append(nombre)
    except medios.ProveedorFallo as e:
        print(f"FALLA: {e}")
    except Exception as e:
        print(f"FALLA: {e.__class__.__name__}: {e}")
print()
if bien:
    print("Funcionan:", ", ".join(bien))
else:
    print("Ninguno funciona. Lo más simple: crea un token gratis en https://huggingface.co/settings/tokens\n"
          "(permiso «Make calls to Inference Providers») y agrega a ~/.config/jarvis/env:   HF_TOKEN=hf_xxx")
    sys.exit(1)
