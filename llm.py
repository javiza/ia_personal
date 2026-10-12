"""
El "cerebro": manda la conversación al modelo y devuelve la respuesta final.

Backends intercambiables (Ollama local, Groq, Claude), todos con herramientas y visión.
Se prueban en el orden de config.ORDEN_CEREBROS: si uno no puede atender (límite de uso,
sin internet, Ollama apagado, modelo retirado) se pasa solo al siguiente.
"""
import base64
import json
import os
import re
import time

import requests

import config
import tools


class _SinCapacidad(Exception):
    """Este cerebro no puede atender ahora (límite, apagado, retirado...). Hay que probar otro."""


# ------------------------------------------------------------------ utilidades
def _ultimo_mensaje_usuario(historial) -> str:
    for m in reversed(historial):
        if m.get("role") == "user" and isinstance(m.get("content"), str) \
                and not m["content"].startswith("[Nota interna"):
            return m["content"]
    return ""


def _tools_activas(historial):
    """Solo las herramientas que vienen al caso (prompt más corto = respuesta más rápida)."""
    return tools.herramientas_para(_ultimo_mensaje_usuario(historial))


def _tools_formato_openai(lista=None):
    """Ollama y Groq usan el formato tipo OpenAI para 'tools'; Anthropic usa input_schema."""
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in (lista if lista is not None else tools.TOOLS)]


def _es_basura(texto: str) -> bool:
    """Detecta la salida rota de un modelo (bucles de «… … …», espacios raros)."""
    if not texto:
        return False
    raros = len(re.findall(r"[…\u00a0\u202f]|\.{3}", texto))
    return raros > 8 or (len(texto) > 80 and raros / len(texto) > 0.08)


def _compactar(mensajes):
    """
    Ahorra tokens: en cada vuelta se reenvía TODO lo anterior, así que los resultados de
    herramientas de pasos ya superados se acortan. El último paso se deja completo.
    """
    idx = [i for i, m in enumerate(mensajes) if m.get("role") == "assistant"]
    if not idx:
        return mensajes
    limite, ultimo = config.MAX_CHARS_TOOL_ANTIGUO, idx[-1]
    salida = []
    for i, m in enumerate(mensajes):
        if m.get("role") == "tool" and i < ultimo and len(m.get("content") or "") > limite:
            m = {**m, "content": m["content"][:limite] + " …[recortado]"}
        salida.append(m)
    return salida


def _segundos_de_espera(resp) -> float:
    """Cuánto pide esperar el servidor tras un 429 (cabecera Retry-After o texto 'try again in 7.6s')."""
    try:
        return float(resp.headers.get("retry-after"))
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in (?:(\d+)m)?\s*([\d.]+)s", resp.text or "")
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 9999.0


def _post(url, cuerpo, headers=None, timeout=90, etiqueta=""):
    """
    POST con manejo de errores común. Si hay límite de uso (429) y la espera es corta,
    espera y reintenta; si es larga, lanza _SinCapacidad para pasar al siguiente cerebro.
    """
    for intento in range(3):
        try:
            resp = requests.post(url, headers=headers, json=cuerpo, timeout=timeout)
        except requests.exceptions.ConnectionError:
            raise _SinCapacidad("sin conexión")
        except requests.exceptions.Timeout:
            raise _SinCapacidad("tardó demasiado")
        if resp.status_code == 429:
            espera = _segundos_de_espera(resp)
            if espera <= config.ESPERA_MAX_REINTENTO and intento < 2:
                time.sleep(espera + 0.5)
                continue
            raise _SinCapacidad(f"límite de uso (espera {espera:.0f}s)" if espera < 9999 else "límite de uso")
        if resp.status_code in (401, 403):
            raise _SinCapacidad("clave rechazada")
        if resp.status_code >= 500:
            raise _SinCapacidad(f"error del servidor {resp.status_code}")
        if resp.status_code >= 400:
            raise _SinCapacidad(f"error {resp.status_code}: {(resp.text or '')[:160]}")
        return resp
    raise _SinCapacidad("límite de uso")


def _ejecutar(nombre, args, bitacora):
    """Ejecuta una herramienta y la anota, por si hay que seguir con otro cerebro sin repetirla."""
    resultado = tools.ejecutar_tool(nombre, args)
    bitacora.append(f"{nombre}({json.dumps(args, ensure_ascii=False)[:150]}) -> {resultado[:250]}")
    print(f"🔧 {nombre}({json.dumps(args, ensure_ascii=False)[:120]}) -> {resultado[:300]}")   # queda en ~/.cache/jarvis/jarvis.log
    return resultado


# ------------------------------------------------------------------ backends
_NOTA_CIERRE = ("[Nota interna: ya no puedes usar más herramientas. Responde AHORA al usuario con lo que "
               "averiguaste hasta aquí: resumen claro, problemas encontrados y qué recomiendas; si algo quedó "
               "sin revisar, dilo en una frase.]")

_ollama_pausa_hasta = 0.0       # mientras no pase este instante, Ollama se salta (fue demasiado lento)


def _ollama_en_pausa() -> bool:
    return time.time() < _ollama_pausa_hasta


def _pausar_ollama():
    global _ollama_pausa_hasta
    if not any(b != "ollama" for b in config.ORDEN_CEREBROS):
        # Ollama es el ÚNICO cerebro: saltarlo dejaría al asistente mudo 10 min. Se sigue intentando con él.
        print("⏳ Ollama fue lento y no hay otro cerebro de respaldo: sigo intentando con él en la próxima pregunta "
              "(usa un modelo más chico, GPU, o sube OLLAMA_TIMEOUT_PRIMER_TOKEN en config.py).")
        return
    _ollama_pausa_hasta = time.time() + config.OLLAMA_PAUSA_TRAS_LENTITUD
    print(f"⏸️  Ollama fue muy lento: lo salto {config.OLLAMA_PAUSA_TRAS_LENTITUD // 60} min "
          f"(usa un modelo más chico o GPU, o pon 'groq' primero en ORDEN_CEREBROS).")


def precalentar_ollama():
    """Carga el modelo en memoria al iniciar (en segundo plano) para que la 1.ª pregunta no espere."""
    if "ollama" not in config.ORDEN_CEREBROS:
        return

    def _carga():
        try:
            requests.post(config.OLLAMA_URL, json={"model": config.OLLAMA_MODEL, "messages": [],
                                                   "keep_alive": config.OLLAMA_KEEP_ALIVE}, timeout=180)
        except Exception:
            pass
    import threading
    threading.Thread(target=_carga, daemon=True).start()


def _ollama_chat(cuerpo, limite):
    """
    Una vuelta con Ollama en STREAMING y con tope de tiempo. Antes era stream=False con
    timeout=300: si el modelo iba lento, cada pregunta esperaba 5 minutos antes de pasar a Groq.
    """
    restante = limite - time.time()
    if restante <= 1:
        raise _SinCapacidad("tardó demasiado")
    try:
        r = requests.post(config.OLLAMA_URL, json={**cuerpo, "stream": True}, stream=True,
                          timeout=(3.05, min(config.OLLAMA_TIMEOUT_PRIMER_TOKEN, restante)))
    except requests.exceptions.ConnectionError:
        raise _SinCapacidad("sin conexión")
    except requests.exceptions.Timeout:
        raise _SinCapacidad("tardó demasiado")
    if r.status_code >= 400:
        texto = r.text or ""
        r.close()
        raise _SinCapacidad(f"error {r.status_code}: {texto[:160]}")
    partes, llamadas = [], []
    try:
        for linea in r.iter_lines():
            if time.time() > limite:
                raise _SinCapacidad("tardó demasiado")
            if not linea:
                continue
            dato = json.loads(linea)
            if dato.get("error"):
                raise _SinCapacidad(f"error 500: {str(dato['error'])[:160]}")
            m = dato.get("message") or {}
            partes.append(m.get("content") or "")
            llamadas += m.get("tool_calls") or []
            if dato.get("done"):
                break
    except requests.exceptions.RequestException as e:
        raise _SinCapacidad("tardó demasiado" if "timed out" in str(e).lower() else "sin conexión")
    finally:
        r.close()
    msg = {"role": "assistant", "content": "".join(partes)}
    if llamadas:
        msg["tool_calls"] = llamadas
    return msg


def _preguntar_ollama(historial, modelo, bitacora):
    mensajes = list(historial)
    herramientas = _tools_formato_openai(_tools_activas(historial))
    con_tools = True
    tope_tarea = time.time() + config.OLLAMA_TIMEOUT_TAREA
    for vuelta in range(config.MAX_TURNOS_TOOL + 1):
        limite = min(time.time() + config.OLLAMA_TIMEOUT_TOTAL, tope_tarea)   # cada vuelta tiene su propio tope
        ultima = vuelta == config.MAX_TURNOS_TOOL
        if ultima:                       # se acabaron las vueltas: que responda con lo que ya averiguó
            mensajes.append({"role": "user", "content": _NOTA_CIERRE})
            con_tools = False
        cuerpo = {"model": modelo, "messages": _compactar(mensajes),
                  "keep_alive": config.OLLAMA_KEEP_ALIVE,
                  "options": {"num_ctx": config.OLLAMA_NUM_CTX,
                              "num_predict": config.OLLAMA_MAX_TOKENS_RESPUESTA,
                              "temperature": config.OLLAMA_TEMPERATURA,
                              "repeat_penalty": config.OLLAMA_REPEAT_PENALTY}}
        if con_tools:
            cuerpo["tools"] = herramientas
        try:
            msg = _ollama_chat(cuerpo, limite)
        except _SinCapacidad as e:
            texto = str(e)
            if "sin conexión" in texto:
                raise _SinCapacidad("Ollama no está corriendo (ábrelo con: ollama serve)")
            if "404" in texto or "not found" in texto:
                raise _SinCapacidad(f"modelo no descargado (ollama pull {modelo})")
            if con_tools and "tool" in texto.lower():       # modelo sin soporte de herramientas
                con_tools = False
                continue
            if "tardó demasiado" in texto:
                _pausar_ollama()
            raise
        tool_calls = msg.get("tool_calls")
        if not tool_calls or ultima:
            return (msg.get("content") or "").strip() or None
        mensajes.append(msg)
        for tc in tool_calls:
            nombre = tc["function"]["name"]
            args = tc["function"].get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {}
            t_tool = time.time()
            mensajes.append({"role": "tool", "name": nombre, "content": _ejecutar(nombre, args, bitacora)})
            tope_tarea += time.time() - t_tool     # generar un video puede tardar minutos: no cuenta como «Ollama lento»
    return None


def _preguntar_groq(historial, modelo, bitacora):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise _SinCapacidad("falta GROQ_API_KEY")
    mensajes = list(historial)
    herramientas = _tools_formato_openai(_tools_activas(historial))
    reintento_tool = True
    for vuelta in range(config.MAX_TURNOS_TOOL + 1):
        ultima = vuelta == config.MAX_TURNOS_TOOL
        cuerpo = {"model": modelo, "messages": _compactar(mensajes)}
        if ultima:
            mensajes.append({"role": "user", "content": _NOTA_CIERRE})
            cuerpo["messages"] = _compactar(mensajes)
        else:
            cuerpo["tools"] = herramientas
        if "gpt-oss" in modelo:
            cuerpo["reasoning_effort"] = config.GROQ_REASONING_EFFORT
        try:
            resp = _post("https://api.groq.com/openai/v1/chat/completions", cuerpo,
                         headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        except _SinCapacidad as e:
            # El modelo inventó un nombre de herramienta («lista_archivos»): Groq lo rechaza con 400.
            # Antes eso tumbaba el modelo entero y pasaba al siguiente (lento); ahora reintenta una vez.
            if reintento_tool and ("not in request.tools" in str(e) or "tool_use_failed" in str(e)
                                   or "tool call validation" in str(e)):
                reintento_tool = False
                nombres = ", ".join(t["function"]["name"] for t in herramientas)
                mensajes.append({"role": "user", "content":
                                 "[Nota interna: usa EXACTAMENTE estos nombres de herramienta: " + nombres + "]"})
                continue
            raise
        msg = resp.json()["choices"][0]["message"]
        tool_calls = msg.get("tool_calls")
        if not tool_calls or ultima:
            return (msg.get("content") or "").strip() or None
        mensajes.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            mensajes.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": _ejecutar(tc["function"]["name"], args, bitacora)})
    return None


def _preguntar_gemini(historial, modelo, bitacora):
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


def _preguntar_anthropic(historial, modelo, bitacora):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise _SinCapacidad("falta ANTHROPIC_API_KEY")
    sistema = historial[0]["content"] if historial and historial[0]["role"] == "system" else ""
    mensajes = [m for m in historial if m["role"] != "system"]
    for vuelta in range(config.MAX_TURNOS_TOOL + 1):
        ultima = vuelta == config.MAX_TURNOS_TOOL
        if ultima:
            mensajes.append({"role": "user", "content": _NOTA_CIERRE})
        cuerpo_a = {"model": modelo, "max_tokens": 1500, "system": sistema, "messages": mensajes}
        if not ultima:
            cuerpo_a["tools"] = _tools_activas(historial)
        resp = _post("https://api.anthropic.com/v1/messages", cuerpo_a,
                     headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                              "content-type": "application/json"}, timeout=120)
        data = resp.json()
        if data.get("stop_reason") != "tool_use" or ultima:
            return "".join(b["text"] for b in data["content"] if b["type"] == "text").strip()
        mensajes.append({"role": "assistant", "content": data["content"]})
        resultados = [{"type": "tool_result", "tool_use_id": b["id"],
                       "content": _ejecutar(b["name"], b["input"], bitacora)}
                      for b in data["content"] if b["type"] == "tool_use"]
        mensajes.append({"role": "user", "content": resultados})
    return None


# ------------------------------------------------------------------ cadena de respaldo
_groq_cache = None            # (instante, {ids}) de los modelos que Groq ofrece hoy
_groq_avisados = set()
_gemini_cache = None          # (instante, [ids]) modelos Gemini habilitados para esta API key


def _groq_disponibles():
    """
    Modelos que Groq realmente ofrece AHORA (GET /models), recordados 1 hora. Groq retira modelos seguido
    (llama-3.3-70b-versatile y llama-3.1-8b-instant daban error 404 en cada pregunta). None = no se pudo consultar.
    """
    global _groq_cache
    ahora = time.time()
    if _groq_cache and ahora - _groq_cache[0] < 3600:
        return _groq_cache[1]
    clave = os.environ.get("GROQ_API_KEY")
    if not clave:
        return None
    try:
        r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {clave}"}, timeout=6)
        if r.status_code != 200:
            return None
        ids = {m["id"] for m in r.json().get("data", []) if m.get("id")}
    except Exception:
        return None
    if not ids:
        return None
    _groq_cache = (ahora, ids)
    return ids


def _modelos_groq():
    """GROQ_MODELOS sin los que Groq ya no tiene (se avisa una sola vez con qué otros hay)."""
    disp = _groq_disponibles()
    if disp is None:
        return list(config.GROQ_MODELOS)
    buenos = [m for m in config.GROQ_MODELOS if m in disp]
    quitados = [m for m in config.GROQ_MODELOS if m not in disp]
    if quitados and not set(quitados) <= _groq_avisados:
        _groq_avisados.update(quitados)
        chat = sorted(m for m in disp if not re.search(r"whisper|tts|guard|orpheus|embed|distil-whisper", m, re.I))
        print(f"⚠️  Groq ya no ofrece: {', '.join(quitados)}. Los salto. Hoy hay: {', '.join(chat)}. "
              f"Cámbialos en GROQ_MODELOS (config.py).")
    return buenos or list(config.GROQ_MODELOS)


def _gemini_disponibles(forzar=False):
    """Consulta la API de Google para no insistir con modelos retirados/no habilitados."""
    global _gemini_cache
    ahora = time.time()
    if not forzar and _gemini_cache and ahora - _gemini_cache[0] < config.GEMINI_CACHE_SEGUNDOS:
        return _gemini_cache[1]
    clave = os.environ.get("GEMINI_API_KEY")
    if not clave:
        return []
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": clave}, timeout=8,
            params={"pageSize": 1000},
        )
        if r.status_code != 200:
            return None
        modelos = []
        for item in r.json().get("models", []):
            nombre = (item.get("name") or "").removeprefix("models/")
            metodos = item.get("supportedGenerationMethods") or []
            if nombre.startswith("gemini-") and "generateContent" in metodos and not any(
                x in nombre.lower() for x in ("embedding", "aqa", "tts", "image", "robotics")
            ):
                modelos.append(nombre)
        # Los modelos flash suelen ofrecer mejor latencia/coste para un asistente general.
        modelos.sort(key=lambda m: ("flash" not in m.lower(), "lite" not in m.lower(), m))
        _gemini_cache = (ahora, modelos)
        return modelos
    except Exception:
        return None


def _modelos_gemini():
    """Prefiere modelos configurados si la API los anuncia; si no, descubre un Flash vigente."""
    disponibles = _gemini_disponibles()
    configurados = list(config.GEMINI_MODELOS)
    if disponibles is None:
        # Sin poder consultar la API, intenta la configuración y deja que el backend reporte el error.
        return configurados
    if not disponibles:
        return configurados
    elegidos = [m for m in configurados if m in disponibles]
    # Conserva alternativas adicionales: un modelo puede aparecer en el catálogo y aun así
    # no estar habilitado para el endpoint compatible OpenAI de una cuenta concreta.
    flash = [m for m in disponibles if "flash" in m.lower()]
    candidatos = elegidos + [m for m in (flash or disponibles) if m not in elegidos]
    return candidatos[:4]


def _cadena():
    """Lista de (backend, modelo) en el orden en que se probarán."""
    cadena = []
    for backend in config.ORDEN_CEREBROS:
        if backend == "ollama":
            cadena.append(("ollama", config.OLLAMA_MODEL))
        elif backend == "groq":
            if os.environ.get("GROQ_API_KEY"):
                cadena += [("groq", m) for m in _modelos_groq()]
        elif backend == "gemini":
            cadena += [("gemini", m) for m in _modelos_gemini()]
        elif backend == "anthropic":
            if os.environ.get("ANTHROPIC_API_KEY"):
                cadena.append(("anthropic", config.ANTHROPIC_MODEL))
    return cadena


_FUNCIONES = {"ollama": _preguntar_ollama, "groq": _preguntar_groq,
              "gemini": _preguntar_gemini, "anthropic": _preguntar_anthropic}
_MSG_TOPE = "Me enredé usando mis herramientas. ¿Puedes pedírmelo de otra forma?"


# Motivos por los que NO vale la pena probar los demás modelos del mismo backend
# (da igual el modelo: sin clave, sin internet o sin respuesta fallarán todos igual).
_MOTIVOS_DE_BACKEND = ("falta ", "clave rechazada", "sin conexión", "tardó demasiado", "no está corriendo")


def _resumen_fallos(fallos):
    """Una frase corta (se lee en voz alta) con el primer motivo de cada backend."""
    vistos, partes = set(), []
    for backend, motivo in fallos:
        if backend not in vistos:
            vistos.add(backend)
            partes.append(f"{backend}: {motivo}")
    return "; ".join(partes)


# ---- guardia contra el «ya lo hice» falso -----------------------------------------------------
# Un modelo chico a veces responde «Listo, creé hola.txt en tu escritorio» SIN llamar a la herramienta.
# Si el usuario pidió una acción, el modelo dice que la hizo y no se ejecutó NINGUNA herramienta,
# no se le cree: se le obliga a usarla, y si no puede, se le dice la verdad al usuario.
_RE_PIDE_ACCION = re.compile(
    r"\b(cre[ae]r?|cr[eé]a|haz|hacer|genera\w*|guarda\w*|escrib\w*|edita\w*|cambia\w*|reemplaza\w*|"
    r"borra\w*|elimina\w*|mueve|copia|renombra\w*|archivo|documento|word|excel|pdf|carpeta|txt|imagen|video|vídeo|"
    r"dibuj\w*|anima\w*|corta|recorta\w*|une|unir|convierte\w*)\b", re.I)
_RE_AFIRMA_HECHO = re.compile(
    r"\b(list[oa]|hecho|cre[eé]|cre[oó]|creado|guard[eé]|guardado|guard[oó]|escrib[ií]|escrito|"
    r"agregu[eé]|edit[eé]|modifiqu[eé]|ya (lo |la )?(hice|cre|guard)|he (creado|guardado|hecho)|se (ha )?(creado|guardado))\b",
    re.I)
_MSG_NO_EJECUTE = ("No pude hacerlo: no logré ejecutar la acción en tu equipo, así que no hice nada. "
                   "Pídemelo otra vez con el nombre del archivo y la carpeta.")


def _miente_sobre_accion(pedido: str, respuesta: str, bitacora) -> bool:
    return (not bitacora and bool(_RE_PIDE_ACCION.search(pedido or ""))
            and bool(_RE_AFIRMA_HECHO.search(respuesta or "")))


def preguntar(historial: list[dict]):
    """
    historial: [{"role": "system"/"user"/"assistant", "content": "..."}]
    Devuelve (texto, ok). ok=False cuando es un aviso de error (no se guarda como conversación).
    Si un cerebro falla o es muy lento, prueba el siguiente de la cadena.
    """
    fallos, bitacora, descartados = [], [], set()
    pedido = _ultimo_mensaje_usuario(historial)
    tools.nuevo_turno(pedido)
    saltado_por_lento = False
    for backend, modelo in _cadena():
        if backend in descartados:
            continue
        if backend == "ollama" and _ollama_en_pausa():
            saltado_por_lento = True
            continue
        entrada = list(historial)
        if bitacora:   # un cerebro anterior ya alcanzó a hacer cosas: que este no las repita
            entrada.append({"role": "user", "content":
                            "[Nota interna: en un intento anterior ya ejecutaste estas herramientas; "
                            "no las repitas, continúa desde aquí y responde al usuario]\n" + "\n".join(bitacora)})
        t0 = time.time()
        try:
            texto = _FUNCIONES[backend](entrada, modelo, bitacora)
            if texto and _es_basura(texto):
                raise _SinCapacidad("respuesta ilegible")
            if texto and _miente_sobre_accion(pedido, texto, bitacora):
                print(f"🚨 {backend}:{modelo} dijo que lo hizo pero no usó ninguna herramienta. Reintento obligándola.")
                entrada += [{"role": "assistant", "content": texto},
                            {"role": "user", "content":
                             "[Nota interna: NO has ejecutado ninguna herramienta, así que no hiciste nada. "
                             "Llama ahora a la herramienta que corresponde (escribir_archivo, crear_documento_word, "
                             "etc.) con los datos pedidos y recién después confirma el resultado real.]"}]
                texto = _FUNCIONES[backend](entrada, modelo, bitacora)
                if texto and _miente_sobre_accion(pedido, texto, bitacora):
                    return _MSG_NO_EJECUTE, False
        except _SinCapacidad as e:
            motivo = str(e)
            fallos.append((backend, motivo))
            print(f"⚠️  {backend}:{modelo} no pudo ({motivo}) tras {time.time() - t0:.1f}s. Pruebo el siguiente…")
            if any(k in motivo for k in _MOTIVOS_DE_BACKEND):
                descartados.add(backend)
            if backend == "gemini" and ("404" in motivo or "no longer available" in motivo.lower()
                                        or "not found" in motivo.lower()):
                # El modelo puntual puede estar retirado; invalida el catálogo para la próxima
                # pregunta, pero prueba los otros modelos ya preparados para esta solicitud.
                global _gemini_cache
                _gemini_cache = None
            continue
        except Exception as e:           # un error raro de un cerebro no debe tumbar a los demás
            fallos.append((backend, str(e)))
            print(f"⚠️  {backend}:{modelo} falló ({e}). Pruebo el siguiente…")
            continue
        print(f"⏱️  {backend}:{modelo} respondió en {time.time() - t0:.1f}s")
        if texto is None:
            return _MSG_TOPE, False
        return texto, True

    if saltado_por_lento and not fallos:
        return ("Mi cerebro local va muy lento en este equipo y no hay otro configurado. "
                "Pon tu GROQ_API_KEY, o usa un modelo más chico en OLLAMA_MODEL."), False
    if not fallos:
        return "No tengo ningún cerebro configurado. Revisa ORDEN_CEREBROS en config.py.", False
    print("❌ Ningún cerebro pudo responder: " + _resumen_fallos(fallos))
    nube = [m for b, m in fallos if b != "ollama"]
    if nube and all("límite" in m for m in nube):
        return ("Se agotó el uso gratuito de todos mis modelos por ahora. "
                "Prueba en un minuto, o instala Ollama para tener un cerebro local sin límites."), False
    return f"No pude pensar la respuesta. {_resumen_fallos(fallos)}.", False


# ------------------------------------------------------------------ visión
def _vision(backend, datos: bytes, media_type: str, pregunta: str) -> str:
    b64 = base64.b64encode(datos).decode()
    if backend == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise _SinCapacidad("falta ANTHROPIC_API_KEY")
        r = _post("https://api.anthropic.com/v1/messages",
                  {"model": config.ANTHROPIC_MODEL, "max_tokens": 1200,
                   "messages": [{"role": "user", "content": [
                       {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                       {"type": "text", "text": pregunta}]}]},
                  headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                           "content-type": "application/json"}, timeout=120)
        return "".join(b["text"] for b in r.json()["content"] if b["type"] == "text").strip()

    if backend == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise _SinCapacidad("falta GEMINI_API_KEY")
        r = _post(config.GEMINI_URL,
                  {"model": (_modelos_gemini() or config.GEMINI_MODELOS)[0], "messages": [{"role": "user", "content": [
                      {"type": "text", "text": pregunta},
                      {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}]}]},
                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                  timeout=config.GEMINI_TIMEOUT)
        return (r.json()["choices"][0]["message"].get("content") or "").strip()

    if backend == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise _SinCapacidad("falta GROQ_API_KEY")
        r = _post("https://api.groq.com/openai/v1/chat/completions",
                  {"model": config.GROQ_VISION_MODEL, "messages": [{"role": "user", "content": [
                      {"type": "text", "text": pregunta},
                      {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}]}]},
                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        texto = r.json()["choices"][0]["message"].get("content") or ""
        return re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()

    # ollama
    r = _post(config.OLLAMA_URL,
              {"model": config.OLLAMA_VISION_MODEL, "stream": False, "keep_alive": config.OLLAMA_KEEP_ALIVE,
               "messages": [{"role": "user", "content": pregunta, "images": [b64]}]}, timeout=300)
    return (r.json()["message"].get("content") or "").strip()


def describir_imagen(datos: bytes, media_type: str, pregunta: str) -> str:
    """Le pasa una imagen al primer modelo de visión disponible de la cadena y devuelve su respuesta."""
    fallos = []
    for backend in config.ORDEN_CEREBROS:
        try:
            return _vision(backend, datos, media_type, pregunta)
        except _SinCapacidad as e:
            fallos.append(f"{backend}: {e}")
    raise RuntimeError("ningún modelo de visión pudo atender (" + "; ".join(fallos) + ")")


# ------------------------------------------------------------------ consulta simple (tareas internas)
def completar(sistema: str, usuario: str, max_tokens: int = 400):
    """
    Una pregunta SIN herramientas para tareas internas en segundo plano (p. ej. aprender de la conversación).
    Respeta ORDEN_CEREBROS (si solo tienes Ollama, nada sale a la nube) y prefiere los modelos de nube más
    chicos para no competir con tus preguntas por el límite de uso ni por el procesador. Devuelve None si
    ningún cerebro pudo.
    """
    mensajes = [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]
    for backend in ("gemini", "groq", "anthropic", "ollama"):
        if backend not in config.ORDEN_CEREBROS:
            continue
        try:
            if backend == "gemini":
                api_key = os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    continue
                for modelo in list(reversed(_modelos_gemini() or config.GEMINI_MODELOS)):  # primero el más liviano
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
                api_key = os.environ.get("GROQ_API_KEY")
                if not api_key:
                    continue
                for modelo in list(reversed(config.GROQ_MODELOS))[:3]:      # del más chico al más grande
                    cuerpo = {"model": modelo, "messages": mensajes, "max_tokens": max_tokens, "temperature": 0.1}
                    if "gpt-oss" in modelo:
                        cuerpo["reasoning_effort"] = "low"
                        cuerpo["max_tokens"] = max_tokens + 600              # el razonamiento también gasta tokens
                    try:
                        r = _post("https://api.groq.com/openai/v1/chat/completions", cuerpo,
                                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                    except _SinCapacidad:
                        continue
                    texto = (r.json()["choices"][0]["message"].get("content") or "").strip()
                    if texto:
                        return texto
            elif backend == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    continue
                r = _post("https://api.anthropic.com/v1/messages",
                          {"model": config.ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": sistema,
                           "messages": [mensajes[1]]},
                          headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"}, timeout=60)
                texto = "".join(b["text"] for b in r.json()["content"] if b["type"] == "text").strip()
                if texto:
                    return texto
            else:
                if _ollama_en_pausa():
                    continue
                msg = _ollama_chat({"model": config.OLLAMA_MODEL, "messages": mensajes,
                                    "keep_alive": config.OLLAMA_KEEP_ALIVE,
                                    "options": {"num_ctx": config.OLLAMA_NUM_CTX, "num_predict": max_tokens,
                                                "temperature": 0.1}}, time.time() + 90)
                texto = (msg.get("content") or "").strip()
                if texto:
                    return texto
        except _SinCapacidad:
            continue
        except Exception as e:
            print(f"⚠️  completar({backend}) falló: {e}")
    return None
