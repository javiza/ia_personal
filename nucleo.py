"""
El "núcleo" compartido: una sola conversación, memoria y cerebro, sin importar si
le hablas por voz o le escribes en el chat. Un candado evita que dos peticiones
(voz y texto a la vez) se mezclen.
"""
import threading

import aprendizaje
import config
import llm
import memoria
import personalidad


class Asistente:
    def __init__(self):
        self._lock = threading.Lock()
        self.ultimo_ok = True            # ¿la última respuesta fue real (True) o un aviso de error (False)?
        memoria.iniciar()                # base local + copia en la nube (si está configurada)
        self.historial = [{"role": "system", "content": personalidad.construir_system_prompt()}]
        self.historial += memoria.cargar_historial_reciente()
        llm.precalentar_ollama()

    def recargar_historial(self):
        """Vuelve a armar la conversación en curso desde la memoria (p. ej. después de borrar pedidos del historial)."""
        with self._lock:
            self.historial = [self.historial[0]] + memoria.cargar_historial_reciente()

    def responder(self, texto: str) -> str:
        with self._lock:
            # El system prompt se rearma en cada turno: hora, nombre, reglas y los recuerdos que vienen al caso.
            self.historial[0] = {"role": "system", "content": personalidad.construir_system_prompt(texto)}
            self.historial.append({"role": "user", "content": texto})

            respuesta, ok = llm.preguntar(self.historial)

            self.ultimo_ok = ok
            if not ok:
                # Un aviso de error NO entra en la conversación: antes se guardaban
                # («Llegué al límite…») y el modelo los imitaba en las respuestas siguientes.
                self.historial.pop()
                try:
                    memoria.guardar_prompt_fallido(texto)    # el prompt se recuerda aunque no haya podido responder
                except Exception:
                    pass
                return respuesta
            self.historial.append({"role": "assistant", "content": respuesta})
            memoria.guardar_mensaje("user", texto)
            memoria.guardar_mensaje("assistant", respuesta)
            aprendizaje.observar(texto, respuesta)       # aprende en segundo plano; no demora la respuesta
            if len(self.historial) > config.MAX_HISTORY_MESSAGES + 1:
                self.historial[1:] = self.historial[-config.MAX_HISTORY_MESSAGES:]
            return respuesta
