#!/usr/bin/env python3
"""
Agrega Gemini (Google AI Studio, capa gratis) como cerebro de respaldo en tu proyecto.

Uso (desde la carpeta del proyecto, donde están llm.py y config.py):
    python3 aplicar_gemini.py

- Hace copias de seguridad: llm.py.bak y config.py.bak
- No pisa tus otros cambios: solo inserta bloques y cambia ORDEN_CEREBROS.
- Es seguro ejecutarlo dos veces (no duplica nada).
"""
import re
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
LLM, CFG = AQUI / "llm.py", AQUI / "config.py"


def respaldar(ruta):
    """Copia de seguridad una sola vez: nunca pisa tu respaldo original."""
    destino = Path(str(ruta) + ".bak")
    if not destino.exists():
        shutil.copy(ruta, destino)


def reemplazar_una_vez(texto, ancla, nuevo, nombre):
    if texto.count(ancla) != 1:
        sys.exit(f"✖ No encontré el punto exacto para «{nombre}» en tu archivo "
                 f"(¿lo modificaste?). No cambié nada más.")
    return texto.replace(ancla, nuevo)


# ------------------------------------------------------------------ llm.py
FUNCION_GEMINI = '''def _preguntar_gemini(historial, modelo, bitacora):
    """Gemini por su endpoint compatible con OpenAI: mismo formato de mensajes y herramientas que Groq."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise _SinCapacidad("falta GEMINI_API_KEY")
    mensajes = list(historial)
    herramientas = _tools_formato_openai(_tools_activas(historial))
    for vuelta in range(config.MAX_TURNOS_TOOL + 1):
        ultima = vuelta == config.MAX_TURNOS_TOOL
        if ultima:
            mensajes.append({"role": "user", "content": _NOTA_CIERRE})
        cuerpo = {"model": modelo, "messages": _compactar(mensajes), "temperature": 0.3}
        if not ultima:
            cuerpo["tools"] = herramientas
        resp = _post(config.GEMINI_URL, cuerpo,
                     headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                     timeout=config.GEMINI_TIMEOUT)
        msg = resp.json()["choices"][0]["message"]
        tool_calls = msg.get("tool_calls")
        if not tool_calls or ultima:
            texto = (msg.get("content") or "").strip()
            return re.sub(r"<thought>.*?</thought>", "", texto, flags=re.S).strip() or None
        for i, tc in enumerate(tool_calls):          # Gemini a veces devuelve el id vacío
            tc["id"] = tc.get("id") or f"call_{vuelta}_{i}"
        mensajes.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            mensajes.append({"role": "tool", "tool_call_id": tc["id"], "name": tc["function"]["name"],
                             "content": _ejecutar(tc["function"]["name"], args, bitacora)})
    return None


'''

VISION_GEMINI = '''    if backend == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise _SinCapacidad("falta GEMINI_API_KEY")
        r = _post(config.GEMINI_URL,
                  {"model": config.GEMINI_MODELOS[0], "messages": [{"role": "user", "content": [
                      {"type": "text", "text": pregunta},
                      {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}]}]},
                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                  timeout=config.GEMINI_TIMEOUT)
        return (r.json()["choices"][0]["message"].get("content") or "").strip()

'''

COMPLETAR_GEMINI = '''            if backend == "gemini":
                api_key = os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    continue
                for modelo in list(reversed(config.GEMINI_MODELOS)):          # primero el más liviano
                    try:
                        r = _post(config.GEMINI_URL,
                                  {"model": modelo, "messages": mensajes, "max_tokens": max_tokens + 600,
                                   "temperature": 0.1},
                                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                                  timeout=config.GEMINI_TIMEOUT)
                    except _SinCapacidad:
                        continue
                    texto = (r.json()["choices"][0]["message"].get("content") or "").strip()
                    if texto:
                        return texto
            elif backend == "groq":
'''


def parchear_llm():
    t = LLM.read_text(encoding="utf-8")
    if "_preguntar_gemini" in t:
        print("• llm.py ya tenía Gemini: sin cambios.")
        return
    respaldar(LLM)
    t = reemplazar_una_vez(t, "def _preguntar_anthropic(historial, modelo, bitacora):",
                           FUNCION_GEMINI + "def _preguntar_anthropic(historial, modelo, bitacora):",
                           "función de Gemini")
    t = reemplazar_una_vez(
        t, '_FUNCIONES = {"ollama": _preguntar_ollama, "groq": _preguntar_groq, "anthropic": _preguntar_anthropic}',
        '_FUNCIONES = {"ollama": _preguntar_ollama, "groq": _preguntar_groq,\n'
        '              "gemini": _preguntar_gemini, "anthropic": _preguntar_anthropic}', "tabla de cerebros")
    t = reemplazar_una_vez(
        t, '        elif backend == "anthropic":\n            cadena.append(("anthropic", config.ANTHROPIC_MODEL))',
        '        elif backend == "gemini":\n            cadena += [("gemini", m) for m in config.GEMINI_MODELOS]\n'
        '        elif backend == "anthropic":\n            cadena.append(("anthropic", config.ANTHROPIC_MODEL))', "cadena")
    t = reemplazar_una_vez(t, '    if backend == "groq":\n        api_key = os.environ.get("GROQ_API_KEY")\n'
                              '        if not api_key:\n            raise _SinCapacidad("falta GROQ_API_KEY")\n'
                              '        r = _post("https://api.groq.com/openai/v1/chat/completions",\n'
                              '                  {"model": config.GROQ_VISION_MODEL',
                           VISION_GEMINI + '    if backend == "groq":\n        api_key = os.environ.get("GROQ_API_KEY")\n'
                              '        if not api_key:\n            raise _SinCapacidad("falta GROQ_API_KEY")\n'
                              '        r = _post("https://api.groq.com/openai/v1/chat/completions",\n'
                              '                  {"model": config.GROQ_VISION_MODEL', "visión")
    # Tareas en segundo plano (aprender de la charla): primero Gemini, para no gastar el cupo de Groq.
    t = reemplazar_una_vez(t, '    for backend in ("groq", "anthropic", "ollama"):',
                           '    for backend in ("gemini", "groq", "anthropic", "ollama"):', "tareas internas")
    t = reemplazar_una_vez(t, '            if backend == "groq":\n                api_key = os.environ.get("GROQ_API_KEY")\n'
                              '                if not api_key:\n                    continue\n'
                              '                for modelo in list(reversed(config.GROQ_MODELOS))[:3]:',
                           COMPLETAR_GEMINI + '                api_key = os.environ.get("GROQ_API_KEY")\n'
                              '                if not api_key:\n                    continue\n'
                              '                for modelo in list(reversed(config.GROQ_MODELOS))[:3]:', "completar")
    LLM.write_text(t, encoding="utf-8")
    print("✔ llm.py actualizado (copia en llm.py.bak).")


# ------------------------------------------------------------------ config.py
BLOQUE_CFG = '''
# Gemini (Google AI Studio, capa gratis). Clave en ~/.config/jarvis/env:  GEMINI_API_KEY=...
# Se usa su endpoint compatible con OpenAI. Si un modelo da 404, mira los nombres vigentes en
# https://ai.google.dev/gemini-api/docs/models y cámbialos aquí.
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODELOS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]   # cada uno tiene su propio cupo gratis
GEMINI_TIMEOUT = 60
'''


def parchear_config():
    t = CFG.read_text(encoding="utf-8")
    respaldar(CFG)
    if "GEMINI_MODELOS" not in t:
        m = re.search(r'^ANTHROPIC_MODEL\s*=.*$', t, flags=re.M)
        if not m:
            sys.exit("✖ No encontré ANTHROPIC_MODEL en config.py; pega el bloque de Gemini a mano.")
        t = t[:m.end()] + "\n" + BLOQUE_CFG + t[m.end():]
    # orden de cerebros: groq -> gemini -> claude (si hay clave) -> ollama
    t, n = re.subn(r'^ORDEN_CEREBROS\s*=\s*\[.*?\].*$',
                   'ORDEN_CEREBROS = ["groq", "gemini", "anthropic", "ollama"]   # los que no tienen clave se saltan solos',
                   t, count=1, flags=re.M)
    if not n:
        sys.exit("✖ No encontré la línea ORDEN_CEREBROS en config.py.")
    # menos tokens por petición (el límite de Groq es por tokens/minuto)
    for nombre, valor in (("MAX_HISTORY_MESSAGES", 8), ("MAX_CHARS_RESULTADO_TOOL", 3000), ("WEB_MAX_CHARS", 3500)):
        t = re.sub(rf'^({nombre}\s*=\s*)\d+', rf'\g<1>{valor}', t, count=1, flags=re.M)
    CFG.write_text(t, encoding="utf-8")
    print("✔ config.py actualizado (copia en config.py.bak).")


if __name__ == "__main__":
    for f in (LLM, CFG):
        if not f.exists():
            sys.exit(f"✖ No encuentro {f.name}. Ejecuta este script dentro de la carpeta del proyecto.")
    parchear_llm()
    parchear_config()
    print("\nListo. Falta solo:\n  1) Consigue una clave gratis en https://aistudio.google.com/apikey\n"
          "  2) Agrégala a ~/.config/jarvis/env:   GEMINI_API_KEY=tu_clave\n  3) ./iniciar.sh")
