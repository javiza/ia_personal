# Jarvis — asistente de voz con avatar

Palabra de activación («Hey Jarvis») o clic en el avatar, voz neuronal, un modelo con herramientas reales
(archivos, web, fotos, video, pantalla) y **memoria que aprende y vive en la nube**.

## Instalar y abrir

```bash
sudo apt install libportaudio2 libxcb-cursor0 wmctrl xdotool   # una vez (micrófono, avatar, ventanas)
./iniciar.sh                                                  # crea el entorno, instala lo que falte y abre
```

`iniciar.sh` revisa las librerías en cada arranque y **instala solo las que falten** (ya no se cae con
`No module named ...`). Si algo queda a medias: `./iniciar.sh --reinstalar`. Si se cae por otro motivo, se
reabre solo; si lo cierras tú («adiós», clic derecho > Salir, Ctrl+C) se queda cerrado.
Registro: `~/.cache/jarvis/jarvis.log`. Para que se abra al iniciar sesión: `./instalar_autoinicio.sh`.

## Memoria: instrucciones permanentes y aprendizaje

Guarda tres cosas, y las tres sobreviven a reinicios:

| Tipo | Qué es | Cómo se crea |
|---|---|---|
| **Reglas** | Cómo quieres que se comporte | «a partir de ahora responde corto», «siempre entrégame el código en un archivo» |
| **Datos** | Cosas tuyas: proyectos, gustos, gente | «mi backend de turismo está en Render» |
| **Lecciones** | Errores que cometió y no debe repetir | Las deduce sola cuando la corriges |

- Las **reglas** se le muestran siempre; los **datos** y **lecciones**, solo los que vienen al caso (así el prompt no crece).
- **Aprende sola**: cada 6 turnos (`APRENDER_CADA`), o enseguida si dices «recuerda…», «siempre…», «no me gusta…», un modelo
  barato revisa lo hablado y guarda lo duradero. Va en segundo plano: no demora las respuestas. Solo analiza lo que dijiste
  tú y lo que ella contestó, **nunca** el texto de páginas o archivos, para que nadie pueda «enseñarle» reglas con un sitio malicioso.
- Nunca guarda contraseñas, claves de API, tarjetas ni RUT.
- Pídele: «¿qué recuerdas de mí?» / «¿qué reglas te di?» (`ver_memoria`) · «olvida lo de …» (`olvidar_recuerdo`).

### Base de datos en la nube (Render)

Todo se guarda **primero en tu PC** (`memoria.sqlite3`, rápido y funciona sin internet) y un hilo lo copia a Postgres en
segundo plano. Si la nube está caída, no se nota; se sube sola cuando vuelva. Un segundo equipo con la misma URL ve lo mismo.

1. Render → **New → PostgreSQL**. Cuando esté lista, copia la **External Database URL**.
2. Pégala en `~/.config/jarvis/env`:
   ```
   JARVIS_DATABASE_URL=postgresql://usuario:clave@dpg-xxxx.oregon-postgres.render.com/base
   ```
3. Abre `./iniciar.sh`. Pregúntale «¿está mi memoria en la nube?»; o mira en el log `☁️ Memoria sincronizada con la nube`.

Usa tablas con prefijo `jarvis_`, así puedes compartir la base con otra app. **Ojo:** las bases *gratis* de Render caducan a los
30 días (y se borran 14 días después); con un plan pagado no. Como tu PC guarda su propia copia, si caduca no pierdes nada:
creas otra base, cambias la URL y todo se vuelve a subir.

## Cerebro

`ORDEN_CEREBROS` en `config.py` (se prueban en orden; si uno falla pasa al siguiente):
- `"ollama"` local, sin límites ni filtros de nube: `ollama pull hermes3:8b`. Sin GPU es lento: si tarda más de 45 s lo salta 10 min.
- `"groq"` nube gratis: `GROQ_API_KEY=...` en `~/.config/jarvis/env`.
- `"anthropic"` Claude (de pago): `ANTHROPIC_API_KEY=...`.

Respuestas rápidas sí o sí: `ORDEN_CEREBROS = ["groq", "ollama"]`. Si **nunca** quieres que algo salga a una nube (tampoco el
aprendizaje automático): `["ollama"]`.

## Qué puede hacer

- **Web**: `buscar_en_web`, `leer_pagina_web` (bloquea direcciones privadas).
- **Archivos** (solo en Escritorio, Documentos, Descargas, Imágenes y `~/JarvisArchivos`): leer/crear/editar txt, Word, Excel, PDF,
  con respaldo antes de sobrescribir y verificación en disco. «Escritorio/x.txt» va a tu escritorio real.
- **Proyectos**: `listar_arbol`, `leer_zip`, `buscar_en_archivos` («revisa la carpeta turismo en proyectos del escritorio»).
- **Fotos**: inspeccionar, analizar con visión, editar (recortar, rotar, brillo, texto, blanco y negro…) sin tocar el original.
- **Imagen y video**: generar (Pollinations gratis, OpenAI, Hugging Face, Stable Diffusion local), video con IA (Replicate),
  animar una imagen, unir y editar video con ffmpeg. Claves en `~/.config/jarvis/env`.
- **Pantalla**: `ver_ventanas`, `ver_pantalla` (solo cuando se lo pides; la captura se envía al modelo que uses; apágalo con `PERMITIR_PANTALLA = False`).
- **Nombre**: «a partir de ahora te llamas Aria». La palabra de activación sigue siendo «Hey Jarvis».
- **Avatar**: cambia `assets/avatar.png`, o deja un `avatar.gif` (también uno por estado: `avatar_reposo.gif`, `avatar_escuchando.gif`…).

## Problemas frecuentes

- **`Fatal Python error: none_dealloc`**: PySide6 6.12 con Python 3.10. Ya está fijado en `requirements.txt` (`<6.12`); si lo actualizaste: `./iniciar.sh --reinstalar`.
- **Graba siempre 15 s**: sube `SILENCE_THRESHOLD` en `config.py` (0.015 → 0.03). **No se activa**: baja `WAKEWORD_THRESHOLD`; **se activa sola**: súbelo.
- **Avatar no aparece / error `xcb`**: `sudo apt install libxcb-cursor0`. En Wayland, `ver_ventanas`/`ver_pantalla` solo van bien en una sesión Xorg.
- **Groq `404 model_not_found`**: retiraron un modelo; edita `GROQ_MODELOS` / `GROQ_VISION_MODEL` en `config.py`.
- **Voz `403`**: `pip install --upgrade edge-tts` (necesita internet).
- **«Nube sin conexión» en el log**: revisa que la URL sea la *External* (no la Internal), que el servicio esté activo y que no haya caducado (plan gratis).
# ia_personal
