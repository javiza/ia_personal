"""
Asistente de voz con avatar en pantalla.

  python3 main.py              -> con avatar flotante
  python3 main.py --sin-ui     -> solo consola (sin interfaz gráfica)

Flujo por voz: espera tu "Hey Jarvis" (o un clic en el avatar) -> graba hasta que callas ->
Whisper transcribe -> el modelo piensa y usa herramientas -> responde en voz alta.
Por texto: clic en la insignia 💬 del avatar (o clic derecho > Escribir…) y escribe.
Interruptor de voz: botón «Voz» del chat, insignia 🎙️ del avatar o clic derecho. Apagado = solo escritura (no usa el micrófono).
Para salir: dile "adiós", clic derecho > Salir, o Ctrl+C.
"""
import sys
import threading
import time

import ajustes
import config

try:
    import nucleo
except ModuleNotFoundError as e:
    # Falta una librería: salir con 78 para que iniciar.sh la instale sola (en vez de reiniciar en bucle).
    print(f"✖ Falta la librería «{e.name}». Abre el programa con ./iniciar.sh: la instala sola.")
    sys.exit(78)

SALIDAS = ("salir", "adios", "adiós", "chao", "chau")


class SalidaConsola:
    """Misma interfaz que la UI, pero imprime en la terminal."""
    def estado(self, e): pass
    def mensaje(self, quien, texto):
        if quien == "aviso":
            print(f"ℹ️  {texto}")


class SalidaUI:
    def __init__(self, puente): self.p = puente
    def estado(self, e): self.p.estado.emit(e)
    def mensaje(self, quien, texto): self.p.mensaje.emit(quien, texto)


def bucle_voz(asistente, salida, manual: threading.Event, cerrar: threading.Event, respetar_interruptor=True):
    # Imports pesados aquí (hilo de voz) para que el avatar aparezca de inmediato.
    import audio_io, stt, tts, wakeword

    stt.precargar()                 # Whisper se carga mientras esperas la palabra de activación
    detector = wakeword.crear_detector()

    print("👂 Lista. Di 'Hey Jarvis' o haz clic en el avatar.")
    salida.mensaje("aviso", "Lista. Di «Hey Jarvis» o haz clic en mí.")

    while not cerrar.is_set():
        try:
            salida.estado("reposo")
            if respetar_interruptor and not ajustes.voz_activa():
                # Modo solo escritura: el micrófono queda libre (no se abre) hasta que se vuelva a activar la voz.
                manual.clear()
                cerrar.wait(0.3)
                continue
            seguir = ajustes.voz_activa if respetar_interruptor else None
            oido = wakeword.esperar_wake_word(detector, manual, cerrar, seguir=seguir)
            if oido is None:             # apagaron la voz mientras esperaba
                continue
            if not oido:
                break

            salida.estado("escuchando")
            print("🟢 Te escucho...")
            audio = audio_io.grabar_hasta_silencio()

            salida.estado("pensando")
            print("✍️  Transcribiendo...")
            texto = stt.transcribir(audio)
            if not texto:
                print("🤔 No escuché nada claro.")
                continue
            print(f"🗣️  Tú: {texto}")
            salida.mensaje("tu", texto)

            if texto.lower().strip(" .,!¡¿?") in SALIDAS:
                salida.estado("hablando")
                tts.hablar("Hasta luego.")
                cerrar.set()
                break

            print("🧠 Pensando...")
            t0 = time.time()
            respuesta = asistente.responder(texto)
            print(f"⏱️  Total pensar+herramientas: {time.time() - t0:.1f}s")

            salida.mensaje("ella", respuesta)
            salida.estado("hablando")
            tts.hablar(respuesta)
        except Exception as e:
            print(f"⚠️  Error en el ciclo de voz: {e}")
            salida.mensaje("aviso", f"Tuve un problema: {e}")
    salida.estado("reposo")


_candado = None   # se mantiene abierto mientras el programa viva


def _instancia_unica() -> bool:
    """
    Evita dos copias a la vez (autoinicio + doble clic, etc.): se pelearían por el micrófono.
    Devuelve False si ya hay otra corriendo. En Windows (sin fcntl) no bloquea nada.
    """
    global _candado
    try:
        import fcntl
    except ImportError:
        return True
    import os
    carpeta = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "jarvis")
    os.makedirs(carpeta, exist_ok=True)
    _candado = open(os.path.join(carpeta, "jarvis.lock"), "w")
    try:
        fcntl.flock(_candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def main():
    if not _instancia_unica():
        print("ℹ️  Ya hay otra copia corriendo; no abro una segunda.")
        return
    manual, cerrar = threading.Event(), threading.Event()
    sin_ui = "--sin-ui" in sys.argv
    asistente = nucleo.Asistente()      # una sola conversación para voz y chat

    print("=" * 52)
    print(f"  {ajustes.obtener_nombre().upper()} — asistente de voz")
    print(f"  Cerebro: {' → '.join(config.ORDEN_CEREBROS)} | Voz: {config.TTS_VOICE}")
    print("=" * 52)

    if not sin_ui:
        try:
            import avatar_ui
        except ImportError as e:
            print(f"⚠️  No pude cargar la interfaz gráfica ({e}). Sigo en modo consola.\n"
                  f"    Instala con: pip install PySide6")
            sin_ui = True

    if sin_ui:
        try:
            bucle_voz(asistente, SalidaConsola(), manual, cerrar, respetar_interruptor=False)
        except KeyboardInterrupt:
            print("\n👋 Cerrando.")
        return

    app = avatar_ui.crear_aplicacion()
    puente = avatar_ui.Puente()
    ventana = avatar_ui.Avatar(puente)   # se guarda en una variable para que Qt no la destruya

    ajustes.suscribir_cambio_nombre(lambda n: puente.nombre.emit(n))   # funciona aunque cambie desde otro hilo
    puente.activar.connect(manual.set)

    def procesar_escrito(texto: str, leer_en_voz_alta: bool):
        """Atiende un mensaje escrito en el chat (en su propio hilo, sin congelar la ventana)."""
        def tarea():
            try:
                puente.estado.emit("pensando")
                respuesta = asistente.responder(texto)
                puente.mensaje.emit("ella", respuesta)
                if leer_en_voz_alta:
                    import tts
                    puente.estado.emit("hablando")
                    tts.hablar(respuesta)
            except Exception as e:
                puente.mensaje.emit("aviso", f"Tuve un problema: {e}")
            finally:
                puente.estado.emit("reposo")
        threading.Thread(target=tarea, daemon=True).start()
    puente.texto_escrito.connect(procesar_escrito)

    def mostrar_ventanas():
        import ventanas
        puente.mensaje.emit("aviso", ventanas.listar_ventanas().split("Lista: ")[-1].replace(" | ", "\n"))
    puente.ver_ventanas.connect(mostrar_ventanas)

    def cerrar_todo():
        cerrar.set()
        app.quit()
    puente.salir.connect(cerrar_todo)

    def hilo_voz():
        try:
            bucle_voz(asistente, SalidaUI(puente), manual, cerrar)
        except Exception as e:
            print(f"⚠️  No pude iniciar el audio: {e}")
            puente.mensaje.emit("aviso", f"No pude iniciar el audio: {e}")
        if cerrar.is_set():          # se despidió ("adiós"): cerrar también el avatar
            puente.salir.emit()

    threading.Thread(target=hilo_voz, daemon=True).start()

    try:
        app.exec()
    except KeyboardInterrupt:
        pass
    cerrar.set()
    print("👋 Cerrando.")


if __name__ == "__main__":
    main()
