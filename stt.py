"""
Speech-to-Text usando faster-whisper (corre 100% local, sin internet).
"""
from faster_whisper import WhisperModel
import numpy as np
import config

_modelo = None


def _cargar_modelo():
    global _modelo
    if _modelo is None:
        print(f"⏳ Cargando modelo Whisper '{config.WHISPER_MODEL_SIZE}' (solo la primera vez)...")
        # device="cpu" funciona en cualquier equipo. Si tienes GPU NVIDIA, cambia a "cuda".
        _modelo = WhisperModel(config.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _modelo


def transcribir(audio: np.ndarray) -> str:
    """Convierte un array de audio (float32, 16kHz, mono) a texto."""
    if audio.size == 0:
        return ""

    # Menos de ~0.5 s o casi sin volumen = ruido: Whisper «inventa» frases con eso (en tu historial
    # aparecían discursos que nunca dijiste) y además cada una se mandaba al modelo y gastaba tiempo.
    if audio.size < config.SAMPLE_RATE * 0.5 or float(np.sqrt(np.mean(audio ** 2))) < 0.004:
        return ""

    modelo = _cargar_modelo()
    segmentos, _info = modelo.transcribe(
        audio,
        language=config.WHISPER_LANGUAGE,
        beam_size=1,                      # antes 5: ~3x más lento y apenas mejora con frases cortas
        condition_on_previous_text=False,  # evita bucles/alucinaciones entre segmentos
        no_speech_threshold=0.6,
        # vad_filter descarta tramos sin voz (silencio, ruido de fondo) antes
        # de transcribir: mejora la precisión y de paso acelera el proceso.
        vad_filter=config.WHISPER_VAD_FILTER,
    )
    buenos = [seg.text.strip() for seg in segmentos
              if seg.no_speech_prob < 0.6 and seg.avg_logprob > -1.0 and seg.compression_ratio < 2.4]
    return " ".join(buenos).strip()


def precargar():
    """Carga Whisper en segundo plano al iniciar: la primera pregunta ya no espera la carga."""
    import threading
    threading.Thread(target=_cargar_modelo, daemon=True).start()
