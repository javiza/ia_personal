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

## Voz o escritura (interruptor)

Tú decides cómo darle las indicaciones: **🎙️ Voz activada** (te escucha con «Hey Jarvis» o clic en el avatar) o **🔇 Voz apagada · solo escritura**
(no abre el micrófono; un clic en el avatar abre el chat). Se cambia con el botón verde/rojo del chat, la insignia 🎙️ del avatar
o clic derecho > *Voz activada*. Se recuerda al reiniciar (`ajustes.json`). Con la voz apagada, «Leer en voz alta las respuestas»
sigue siendo opcional (también se recuerda).

## Papelera del sistema

Cuando le pides borrar algo, **va a la papelera real de tu computador** (la misma que ves en el explorador de archivos),
no a una carpeta propia. Funciona con archivos y carpetas, y se puede hablar con ella de la papelera:

| Dices | Qué hace |
|---|---|
| «borra la foto.png» / «elimina la carpeta viejos» | La manda a la papelera (te muestra qué y espera tu «sí») |
| «muéstrame lo que hay en la papelera» | Lista con número, tamaño, fecha y de dónde venía cada cosa |
| «restaura foto.png» / «restaura el 2» | La devuelve a su carpeta original (nunca pisa algo que ya exista) |
| «borra foto.png para siempre» / «vacía la papelera» | Eliminación definitiva, **irreversible**; te lo avisa y pide confirmación |

Borrar y eliminar para siempre siempre piden confirmación en tu **siguiente** mensaje. No toca `.env`, `memoria.sqlite3`,
`ajustes.json`, `.git/`, el código del programa ni las carpetas base (Escritorio, Documentos...).
Soporte: **Linux** completo · **macOS** enviar, ver y borrar definitivo (restaurar: desde el Finder) · **Windows** solo enviar.
Restaurar solo devuelve a carpetas permitidas (`config.ALLOWED_DIRS`).
En la versión **nube/Render** no existe una papelera de sistema, así que usa una papelera propia y oculta dentro del espacio de
archivos (`espacio/.papelera`); funciona igual (🗑 Papelera en la app, o hablándole).

## Jarvis en todos tus dispositivos (app instalable)

La app web es una **PWA**: se instala desde el navegador en iPhone/iPad, Android, Windows, Mac, Linux y ChromeOS, abre en su
propia ventana, se adapta a pantalla chica, tablet y escritorio (también en horizontal) y abre aunque no haya conexión.
Pasos por aparato: abre **`/instalar`** en tu Jarvis (o toca «Cómo instalar» en la pantalla de acceso). Mantén pulsado el icono
instalado para los atajos **Papelera · Archivos · Historial**.

Hay dos formas de usarla, y la diferencia importa:

| | **Modo nube** (Render, lo de `render.yaml`) | **Modo PC** (`./iniciar.sh --servidor`) |
|---|---|---|
| Dónde corre | En un servidor de internet | En **tu computador** |
| Archivos | Solo su «espacio» (lo que subes y crea) | Tus carpetas reales (Escritorio, Documentos…); lo que subes cae en `~/JarvisArchivos` |
| Papelera | La del espacio (`espacio/.papelera`) | **La papelera real de tu computador** |
| Pantalla, ventanas, video, imágenes IA… | No (un servidor no tiene tu pantalla) | **Sí, todo** |
| Disponible si tu PC está apagado | Sí | No |

**Para no perder ninguna función desde el celular, usa el modo PC**: el celular es solo el control remoto y todo se ejecuta en tu PC.

### Modo PC paso a paso (Linux/macOS)

1. En `~/.config/jarvis/env` pon una clave **larga** (12+ caracteres; el servidor se niega a abrir con una más corta):
   `JARVIS_WEB_CLAVE=una-frase-larga-y-unica`
2. En el PC: `./iniciar.sh --servidor` (queda en `http://127.0.0.1:8000`, solo visible desde ese computador).
3. Para llegar desde el celular **sin abrir tu PC a internet** usa [Tailscale](https://tailscale.com) (gratis, red privada):
   instálalo en el PC y en el celular con la misma cuenta y en el PC ejecuta `tailscale serve --bg 8000`.
   Te da una dirección `https://tu-pc.….ts.net` que solo abren tus aparatos. **Hace falta https** para instalar la app y usar el
   micrófono; por eso no sirve `http://192.168.x.x`.
4. En el celular abre esa dirección → `/instalar` → instalar. Entras con tu clave.

⚠️ El modo PC da control de tus archivos a quien tenga la clave y la dirección. No lo publiques en internet abierto (ni con
túneles públicos): úsalo solo por Tailscale o desde el mismo PC. Windows: el servidor corre igual
(`set JARVIS_MODO=pc` y `uvicorn servidor:app`), pero la papelera de Windows solo permite *enviar* (ver arriba).

## Recuerda todos tus prompts

Todo lo que pides (por voz o por escrito, incluso lo que falló por falta de internet) queda guardado en `memoria.sqlite3` (y en la nube si la configuraste).

- **Chat**: al abrirlo muestra la conversación anterior. **↑ / ↓** en la caja de texto recorren tus pedidos pasados (como una terminal).
- **📜 Historial**: lista y buscador de *todo* lo que has pedido; doble clic lo vuelve a poner en la caja.
- **Borrar**: en el historial, 🗑 borra un pedido (en el escritorio: selecciona uno o varios y pulsa **Supr** o el botón), **«Borrar los que coinciden»** borra todo lo que muestra la búsqueda (útil para borrar un tema entero) y **«Borrar todo»** vacía el historial. Siempre pide confirmación y también borra la respuesta que dio. El borrado llega a la nube (y a tu otro dispositivo) y no reaparece. Lo que ella *aprendió* de ti (reglas, datos, lecciones) no se toca: para eso, «olvida lo de …».
- **Por voz**: «¿qué te pedí ayer sobre turismo?», «¿cuál fue mi último pedido?» (herramienta `buscar_en_historial`).
- Además, antes de responder se le muestran hasta 3 pedidos antiguos parecidos al actual, para que tenga contexto sin llenar el prompt.

## En el celular (app web instalable) — GitHub → Render

`servidor.py` + la carpeta `web/` son la versión para teléfono: se instala como una app (icono en la pantalla de inicio,
pantalla completa), con la peliroja animada, el interruptor voz/escritura y el historial. Usa el mismo cerebro y la misma memoria.

**1. Súbela a GitHub** (desde esta carpeta; `.gitignore` ya deja fuera tu memoria, ajustes, claves y el entorno virtual):
```bash
git add -A && git commit -m "Versión web/celular" && git push
```
**2. Despliégala en Render**: *New + → Blueprint* → elige tu repositorio (usa `render.yaml`). Render te pedirá 3 valores:

| Variable | Qué poner |
|---|---|
| `JARVIS_WEB_CLAVE` | La clave con la que entrarás desde el celular. **Hazla larga**: sin ella nadie entra, con ella cualquiera que la sepa usa tus claves de IA. |
| `GROQ_API_KEY` | Tu clave de Groq (el cerebro; también transcribe tu voz si el navegador no sabe dictar). |
| `JARVIS_DATABASE_URL` | La URL de tu Postgres de Render (la misma del escritorio: así el celular y el PC comparten memoria e historial). Sin ella, el servidor olvida todo cada vez que se reinicia. |

(Opcional: `ANTHROPIC_API_KEY`. `JARVIS_NOMBRE` ya viene como Mackena.) Cuando termine, Render te da una dirección `https://jarvis-xxxx.onrender.com`.

**3. Instálala**: ábrela en el celular, entra con tu clave y
- **Android (Chrome)**: botón **📲 Instalar** de la app (o menú ⋮ → *Instalar aplicación*).
- **iPhone (Safari)**: *Compartir → Agregar a pantalla de inicio*.

Cosas a saber:
- **Voz**: toca la peliroja o el botón 🎙️ y habla; contesta con el altavoz del teléfono. Funciona mejor en Chrome (Android). No hay «Hey Jarvis» en el celular (el navegador no puede escuchar en segundo plano): se toca para hablar. Con **🔇 Voz apagada** solo escribes.
- **Solo en el celular**: buscar en internet, leer páginas, clima, memoria e historial. Archivos, fotos, video y pantalla son del computador (el servidor no toca nada suyo a propósito).
- El plan gratis de Render **duerme el servicio** tras 15 min sin uso: la primera vez tarda ~30 s en despertar.
- ¿Quieres un `.apk` de verdad (Play Store o instalar el archivo)? Con la dirección de Render, [PWABuilder](https://www.pwabuilder.com) lo genera sin tocar el código.
- Probar en tu PC antes: `pip install -r requirements-web.txt` y `JARVIS_WEB_CLAVE=algo uvicorn servidor:app --port 8000` → http://localhost:8000 (el micrófono solo funciona en `localhost` o `https`).

## Archivos: subir, editar y crear (celular y computador)

**En el celular / web** hay un espacio de trabajo propio en el servidor (`espacio/`, o `JARVIS_ESPACIO`). Es lo **único** que la asistente puede tocar desde la web.

- **📎** (junto a la caja de texto, o arrastrando archivos en el PC) sube uno o varios archivos: texto, código, `.docx`, `.xlsx`, `.pdf`, `.zip` e imágenes (máx. 15 MB c/u, 150 MB en total).
- Pídele lo que quieras: «resume el PDF», «cámbiale el título al Word», «pasa esta tabla a Excel», «crea un informe en Word sobre …». Ella lee, edita (con respaldo, conservando el formato del Word cuando se puede) y crea `.txt/.md/código`, Word, Excel y PDF.
- Cada archivo que crea o modifica aparece en el chat con un enlace **⬇** para descargarlo. **📁 Archivos** lista, descarga y borra todo.
- Seguridad: nombres saneados, tipos permitidos (nada ejecutable ni `.svg`), sin salir de la carpeta (`..` y enlaces bloqueados), descargas siempre como adjunto, y todo requiere tu clave.
- **Ojo en Render gratis:** el disco se borra en cada reinicio o deploy. Descarga lo importante, o con un plan pagado monta un *Disk* y pon `JARVIS_ESPACIO=/var/data/espacio`.

**En el computador** el botón **📎** del chat adjunta archivos: si ya están en Escritorio/Documentos/Descargas/Imágenes usa esa ruta; si no, los copia a `~/JarvisArchivos` (el original no se toca) y escribe la ruta en la caja para que completes la orden.

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
- **Avatar animado (la peliroja)**: un GIF por estado en `assets/` — `avatar_reposo.gif`, `avatar_escuchando.gif`, `avatar_pensando.gif` (con nube de pensamiento) y `avatar_hablando.gif`. Se regeneran desde `assets/pelirroja_original.png` con `python3 crear_avatar_gifs.py`. Para usar tus propios GIF, reemplaza esos archivos. El chat muestra la misma animación grande arriba.

## Problemas frecuentes

- **«No puedo generar la imagen en este momento»**: el modelo resume el error y esconde la causa. Ejecuta `./venv/bin/python probar_imagen.py`: prueba cada proveedor y dice cuál falla y por qué (sin conexión, falta clave, límite…). Cada herramienta que usa también queda escrita en `~/.cache/jarvis/jarvis.log` (líneas `🔧 generar_imagen(...) -> ...`). La salida más estable: `HF_TOKEN=hf_...` (gratis en huggingface.co/settings/tokens) en `~/.config/jarvis/env`.
- **`Fatal Python error: none_dealloc`**: PySide6 6.12 con Python 3.10. Ya está fijado en `requirements.txt` (`<6.12`); si lo actualizaste: `./iniciar.sh --reinstalar`.
- **Graba siempre 15 s**: sube `SILENCE_THRESHOLD` en `config.py` (0.015 → 0.03). **No se activa**: baja `WAKEWORD_THRESHOLD`; **se activa sola**: súbelo.
- **Avatar no aparece / error `xcb`**: `sudo apt install libxcb-cursor0`. En Wayland, `ver_ventanas`/`ver_pantalla` solo van bien en una sesión Xorg.
- **Groq `404 model_not_found`**: retiraron un modelo; edita `GROQ_MODELOS` / `GROQ_VISION_MODEL` en `config.py`.
- **Voz `403`**: `pip install --upgrade edge-tts` (necesita internet).
- **«Nube sin conexión» en el log**: revisa que la URL sea la *External* (no la Internal), que el servicio esté activo y que no haya caducado (plan gratis).
# ia_personal

## Ventana de prompt retraída (versión de PC)
Al iniciar, el chat queda retraído como un botón redondo 💬 que se arrastra por toda la pantalla (recuerda dónde lo dejas en `ajustes.json`).
Clic en el botón = despliega el chat; «➖ Retraer» o la X del chat = vuelve a ser botón. Clic derecho en el botón: abrir chat / salir.
