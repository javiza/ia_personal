"""
Aprender de las conversaciones (en segundo plano, sin hacerte esperar).

Cada ciertos turnos —o enseguida si dices algo como «recuerda…», «siempre…», «no me gusta…»— un
modelo barato lee lo último que hablaron y extrae lo que vale la pena recordar para siempre:
reglas que le das (instruccion), datos tuyos (hecho) y correcciones (leccion). Eso se guarda en la
memoria (y de ahí a la nube) y vuelve a entrar en su cabeza en las próximas conversaciones.

Seguridad: solo se analiza lo que TÚ dijiste y lo que ella respondió; nunca el contenido de páginas
web, archivos o imágenes (así un texto malicioso no puede «enseñarle» reglas). Contraseñas, claves y
tarjetas se descartan en memoria.guardar().
"""
import json
import re
import threading

import config
import llm
import memoria

_RE_EXPLICITO = re.compile(
    r"\b(recuerda|recuérd\w+|no olvides|acuérdate|apunta|anota|a partir de ahora|de ahora en adelante|"
    r"desde ahora|siempre|nunca|jamás|prefiero|me gusta|no me gusta|odio|me llamo|mi nombre|trabajo en|"
    r"vivo en|no me hables|no hagas|deja de|en vez de|así no|eso está mal|te equivocaste|corrígete|"
    r"no es lo que pedí|mejor hazlo)\b", re.I)

_SISTEMA = ("Eres el módulo de memoria de un asistente personal. Lees un fragmento de conversación y decides qué "
            "conviene recordar para siempre. Respondes SOLO con un arreglo JSON, sin explicaciones ni markdown.")

_PROMPT = """CONOCIMIENTO YA GUARDADO (no lo repitas):
{guardado}

CONVERSACIÓN RECIENTE:
{conversacion}

Extrae como máximo 3 elementos NUEVOS y DURADEROS, cada uno como {{"tipo": "...", "texto": "..."}}:
- "instruccion": una regla permanente que el usuario le pide al asistente (cómo responder, qué hacer o evitar, tono, formato). Redáctala como orden corta: «Responde siempre en frases cortas».
- "hecho": algo estable sobre el usuario o su mundo (gustos, proyectos, herramientas, personas, rutinas). Redáctalo como «El usuario ...».
- "leccion": una corrección del usuario a un error del asistente, o algo que salió mal, para no repetirlo. Redáctala como «Cuando ..., haz ...».

NO guardes: saludos, preguntas sueltas, cosas del momento (hora, clima de hoy), resultados de herramientas, ni datos sensibles (contraseñas, claves, tarjetas, documentos). Usa solo lo que dijo el USUARIO. Si no hay nada que valga la pena, responde [].
Responde solo el arreglo JSON."""

_lock = threading.Lock()
_buffer: list[tuple[str, str]] = []
_turnos = 0
_trabajando = False


def observar(usuario: str, asistente: str):
    """Se llama tras cada respuesta buena. Decide si toca reflexionar y lo hace en un hilo aparte."""
    global _turnos, _trabajando
    if not config.APRENDER:
        return
    with _lock:
        _buffer.append((usuario, asistente))
        del _buffer[:-config.APRENDER_CADA * 2]
        _turnos += 1
        toca = bool(_RE_EXPLICITO.search(usuario)) or _turnos >= config.APRENDER_CADA
        if not toca or _trabajando:
            return
        lote = list(_buffer)
        _buffer.clear()
        _turnos = 0
        _trabajando = True
    threading.Thread(target=_reflexionar, args=(lote,), daemon=True, name="jarvis-aprender").start()


def _extraer_json(texto: str) -> list:
    texto = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S)
    m = re.search(r"\[.*\]", texto, re.S)
    if not m:
        return []
    try:
        datos = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return datos if isinstance(datos, list) else []


def _reflexionar(lote):
    global _trabajando
    try:
        guardado = []
        for tipo in memoria.TIPOS:
            guardado += [f"[{tipo}] {t}" for t in memoria.listar(tipo, 25)]
        conversacion = "\n".join(f"Usuario: {u[:400]}\nAsistente: {a[:400]}" for u, a in lote)
        crudo = llm.completar(_SISTEMA, _PROMPT.format(guardado="\n".join(guardado) or "(nada todavía)",
                                                       conversacion=conversacion), max_tokens=350)
        nuevos = 0
        for item in _extraer_json(crudo)[:3]:
            if not isinstance(item, dict):
                continue
            tipo, texto = item.get("tipo"), item.get("texto")
            if tipo in memoria.TIPOS and isinstance(texto, str) and memoria.guardar(tipo, texto) == "nuevo":
                nuevos += 1
                print(f"🧠 Aprendí ({tipo}): {texto[:120]}")
        if not nuevos and crudo is None:
            print("🧠 No pude reflexionar ahora (ningún cerebro disponible); lo intento más tarde.")
    except Exception as e:
        print(f"🧠 Error al aprender: {e}")
    finally:
        _trabajando = False
