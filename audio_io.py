"""
Captura de audio del micrófono: graba desde que hablas hasta que callas.
"""
import sounddevice as sd
import numpy as np
import config


def grabar_hasta_silencio() -> np.ndarray:
    """
    Graba automáticamente desde que empiezas a hablar hasta que te quedas
    en silencio por config.SILENCE_DURATION segundos. No requiere presionar
    ninguna tecla — se usa después de detectar la wake word.
    """
    bloque_seg = 0.1  # analiza el audio en trozos de 100ms
    tam_bloque = int(config.SAMPLE_RATE * bloque_seg)
    bloques_silencio_para_parar = int(config.SILENCE_DURATION / bloque_seg)
    max_bloques = int(config.MAX_RECORD_SECONDS / bloque_seg)

    grabacion = []
    empezo_a_hablar = False
    bloques_de_silencio_seguidos = 0

    with sd.InputStream(
        samplerate=config.SAMPLE_RATE,
        channels=config.CHANNELS,
        dtype="float32",
    ) as stream:
        for _ in range(max_bloques):
            bloque, _overflow = stream.read(tam_bloque)
            grabacion.append(bloque.copy())

            energia = float(np.sqrt(np.mean(bloque ** 2)))  # RMS = volumen aproximado

            if energia > config.SILENCE_THRESHOLD:
                empezo_a_hablar = True
                bloques_de_silencio_seguidos = 0
            elif empezo_a_hablar:
                bloques_de_silencio_seguidos += 1
                if bloques_de_silencio_seguidos >= bloques_silencio_para_parar:
                    break

    if not grabacion or not empezo_a_hablar:
        return np.zeros((0,), dtype=np.float32)

    audio = np.concatenate(grabacion, axis=0).flatten()
    print(f"✅ Grabación de {len(audio) / config.SAMPLE_RATE:.1f} segundos capturada.")
    return audio
