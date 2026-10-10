"""
Text-to-Speech usando edge-tts: voces neuronales gratuitas de Microsoft,
mucho más naturales y claras que las voces robóticas de pyttsx3/espeak.

Requiere internet. Si no tienes internet en el equipo donde corre JARVIS,
revisa el README para la alternativa 100% offline (Piper TTS).
"""
import asyncio
import os
import queue
import re
import threading
import tempfile
import edge_tts
from playsound import playsound
import config

_lock = threading.Lock()   # un solo audio a la vez (voz y chat comparten esto)


async def _sintetizar(texto: str, ruta: str):
    comunicador = edge_tts.Communicate(texto, voice=config.TTS_VOICE, rate=config.TTS_RATE)
    await comunicador.save(ruta)


def _frases(texto: str) -> list[str]:
    """Parte en frases (agrupa las muy cortas) para empezar a hablar apenas está lista la primera."""
    crudas = [f.strip() for f in re.split(r"(?<=[.!?¡¿])\s+|\n+", texto) if f.strip()]
    grupos, actual = [], ""
    for f in crudas:
        actual = f"{actual} {f}".strip()
        if len(actual) >= 40:
            grupos.append(actual)
            actual = ""
    if actual:
        grupos.append(actual)
    return grupos or [texto]


def hablar(texto: str):
    """
    Sintetiza y reproduce EN PARALELO: mientras suena la frase 1 ya se genera la 2.
    Antes se generaba todo el audio y recién ahí empezaba a sonar (varios segundos de silencio).
    """
    if not texto:
        return
    print(f"🔊 JARVIS: {texto}")
    cola = queue.Queue(maxsize=2)
    base = os.path.join(tempfile.gettempdir(), f"jarvis_voz_{os.getpid()}")

    def productor():
        try:
            for i, frase in enumerate(_frases(texto)):
                ruta = f"{base}_{i % 3}.mp3"
                asyncio.run(_sintetizar(frase, ruta))
                cola.put(ruta)
        except Exception as e:
            cola.put(e)
        finally:
            cola.put(None)

    try:
        with _lock:
            threading.Thread(target=productor, daemon=True).start()
            while True:
                item = cola.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                playsound(item)
    except Exception as e:
        print(f"⚠️  No pude reproducir la voz ({e}). ¿Tienes internet? "
              f"Revisa el README para la alternativa offline.")
