"""
Wake word: escucha el micrófono en segundo plano y detecta "Hey Jarvis" con
openWakeWord (local, sin cuenta). También se puede activar con un clic en el avatar.
"""
import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model
import config

FRAME_SAMPLES = 1280  # bloques de ~80ms a 16kHz


def crear_detector():
    openwakeword.utils.download_models(model_names=[config.WAKEWORD_MODEL])
    return Model(wakeword_models=[config.WAKEWORD_MODEL])


def esperar_wake_word(modelo, evento_manual=None, evento_salir=None, depurar=False) -> bool:
    """
    Bloquea hasta oír la palabra de activación (o hasta que evento_manual se active,
    por ejemplo con un clic en el avatar). Devuelve False si se pidió cerrar el programa.
    """
    modelo.reset()
    contador = 0
    with sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=FRAME_SAMPLES) as stream:
        while True:
            if evento_salir is not None and evento_salir.is_set():
                return False
            if evento_manual is not None and evento_manual.is_set():
                evento_manual.clear()
                return True

            bloque, _ = stream.read(FRAME_SAMPLES)
            predicciones = modelo.predict(bloque.flatten().astype(np.int16))
            score = max(predicciones.values()) if predicciones else 0.0

            contador += 1
            if depurar and contador % 12 == 0:
                print(f"   [debug] score: {score:.3f} (umbral: {config.WAKEWORD_THRESHOLD})")

            if score > config.WAKEWORD_THRESHOLD:
                return True
