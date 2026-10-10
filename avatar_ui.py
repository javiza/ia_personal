"""
Avatar flotante en pantalla (PySide6/Qt): un icono circular siempre visible, arrastrable,
que cambia de color y "respira" según lo que hace:
  reposo (cian) · escuchando (verde) · pensando (ámbar, arco giratorio) · hablando (rosa)
- Clic: la activa sin decir la palabra de activación. Clic en la insignia 💬: abre el chat de texto.
- Insignia 🎙️: interruptor de voz. Apagada = solo escritura (no se abre el micrófono).
- Avatar animado: un GIF por estado (assets/avatar_reposo|escuchando|pensando|hablando.gif; ver crear_avatar_gifs.py).
- Arrastrar: mueve el icono (recuerda dónde lo dejaste).
- Clic derecho: menú (hablar, ver ventanas, cambiar nombre, salir).
- Muestra lo que dices y lo que responde en una burbuja que se oculta sola.
"""
import html
import math
import os
import sys

# En sesiones Wayland, Qt nativo ignora "siempre encima" y la posición; XWayland sí las respeta.
if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMovie, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

import ajustes
import config

try:
    import memoria
except Exception:            # sin memoria el chat sigue funcionando, solo que sin historial
    memoria = None

COLORES = {
    "reposo": QColor("#5ee7ff"),
    "escuchando": QColor("#4ade80"),
    "pensando": QColor("#fbbf24"),
    "hablando": QColor("#f472b6"),
}


class Puente(QObject):
    """Canal seguro entre el hilo de voz y la interfaz (las señales cruzan hilos solas)."""
    estado = Signal(str)            # reposo | escuchando | pensando | hablando
    mensaje = Signal(str, str)      # (quien: 'tu' | 'ella' | 'aviso', texto)
    nombre = Signal(str)
    activar = Signal()              # clic en el avatar
    salir = Signal()
    ver_ventanas = Signal()
    abrir_chat = Signal()
    texto_escrito = Signal(str, bool)   # (lo que escribiste, ¿leerlo en voz alta?)
    voz_modo = Signal(bool)             # True = se le habla por voz · False = solo escritura (micrófono apagado)


class Burbuja(QWidget):
    """Globo de texto junto al avatar. No intercepta clics."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setWindowTitle("jarvis-burbuja")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.etiqueta = QLabel(self)
        self.etiqueta.setWordWrap(True)
        self.etiqueta.setTextFormat(Qt.RichText)
        self.etiqueta.setMaximumWidth(340)
        self.etiqueta.setStyleSheet(
            "QLabel { background: rgba(10,16,32,235); color: #eaf6ff; border: 1px solid #5ee7ff;"
            " border-radius: 14px; padding: 10px 14px; font-size: 13px; }")
        self.temporizador = QTimer(self, singleShot=True, timeout=self.hide)

    def mostrar(self, html: str, segundos: float, ancla: QWidget):
        self.etiqueta.setText(html)
        self.etiqueta.adjustSize()
        self.resize(self.etiqueta.size())
        g = ancla.frameGeometry()
        pantalla = ancla.screen().availableGeometry()
        x = min(max(pantalla.left() + 6, g.right() - self.width()), pantalla.right() - self.width() - 6)
        y = g.top() - self.height() - 6
        if y < pantalla.top() + 6:
            y = g.bottom() + 6
        self.move(x, y)
        self.show()
        self.temporizador.start(int(segundos * 1000))


ESTILO_CHAT = """
QWidget { background: #0b1222; color: #eaf6ff; font-size: 13px; }
QTextBrowser { background: #101a30; border: 1px solid #25406b; border-radius: 10px; padding: 8px; }
QLineEdit { background: #101a30; border: 1px solid #5ee7ff; border-radius: 10px; padding: 8px 10px; }
QListWidget { background: #101a30; border: 1px solid #25406b; border-radius: 10px; padding: 4px; }
QListWidget::item { padding: 6px 4px; border-bottom: 1px solid #16294d; }
QListWidget::item:selected { background: #1d3a66; color: #ffffff; }
QPushButton { background: #5ee7ff; color: #06182e; border: none; border-radius: 10px;
              padding: 8px 16px; font-weight: bold; }
QPushButton:hover { background: #8ff0ff; }
QPushButton#suave { background: #16294d; color: #cfe6ff; font-weight: normal; padding: 6px 12px; }
QPushButton#suave:hover { background: #1d3a66; }
QPushButton#voz { background: #4ade80; color: #04210f; padding: 6px 12px; }
QPushButton#voz:hover { background: #7cf0a6; }
QPushButton#voz:!checked { background: #3a1f2b; color: #ff9fb0; border: 1px solid #ff6b81; }
QPushButton#voz:!checked:hover { background: #4d2736; }
QCheckBox { color: #8aa4c8; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #5ee7ff; border-radius: 4px; background: #101a30; }
QCheckBox::indicator:checked { background: #5ee7ff; }
QLabel#titulo { font-size: 17px; font-weight: bold; color: #eaf6ff; }
QLabel#estado { color: #8aa4c8; }
QLabel#pensando { color: #fbbf24; }
"""

TEXTO_ESTADO = {"reposo": "En reposo", "escuchando": "Te escucho…", "pensando": "Pensando…", "hablando": "Hablando…"}


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes, para buscar «accion» y encontrar «acción»."""
    try:
        return memoria._sin_acentos(texto)
    except Exception:
        return (texto or "").lower()


class MiniAvatar(QWidget):
    """La peliroja animada dentro del chat: cambia de GIF según lo que esté haciendo (pensando, hablando…)."""

    def __init__(self, avatar: QWidget, lado: int = 104):
        super().__init__()
        self.avatar = avatar
        self.setFixedSize(lado, lado)
        self.reloj = QTimer(self, timeout=self.update)

    def showEvent(self, e):
        self.reloj.start(50)
        super().showEvent(e)

    def hideEvent(self, e):
        self.reloj.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        color = COLORES[self.avatar.estado]
        rect = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        camino = QPainterPath()
        camino.addEllipse(rect)
        p.save(); p.setClipPath(camino)
        img = self.avatar._imagen_actual()
        p.drawPixmap(rect, img, QRectF(img.rect()))
        p.restore()
        aro = QPen(color, 3); aro.setCapStyle(Qt.RoundCap)
        p.setPen(aro); p.setBrush(Qt.NoBrush)
        marco = rect.adjusted(-2, -2, 2, 2)
        if self.avatar.estado == "pensando":
            giro = int(-self.avatar.fase * 70 * 16)
            p.drawArc(marco, giro, 110 * 16)
            p.drawArc(marco, giro + 180 * 16, 110 * 16)
        else:
            p.drawEllipse(marco)


class CampoPrompt(QLineEdit):
    """Entrada con memoria: ↑ y ↓ recorren TODO lo que has pedido antes (como el historial de una terminal)."""

    def __init__(self):
        super().__init__()
        self.pasado: list[str] = []
        self.pos = 0
        self.borrador = ""

    def cargar(self, textos):
        self.pasado = list(textos)
        self.pos = len(self.pasado)

    def recordar(self, texto: str):
        if texto and (not self.pasado or self.pasado[-1] != texto):
            self.pasado.append(texto)
        self.pos = len(self.pasado)
        self.borrador = ""

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Up and self.pasado:
            if self.pos == len(self.pasado):
                self.borrador = self.text()
            self.pos = max(0, self.pos - 1)
            self.setText(self.pasado[self.pos])
        elif e.key() == Qt.Key_Down and self.pos < len(self.pasado):
            self.pos += 1
            self.setText(self.borrador if self.pos == len(self.pasado) else self.pasado[self.pos])
        else:
            super().keyPressEvent(e)


class DialogoHistorial(QDialog):
    """Todo lo que le has pedido, con buscador. Doble clic = volver a usarlo."""

    def __init__(self, padre, prompts):
        super().__init__(padre)
        self.setWindowTitle(f"Historial de pedidos ({len(prompts)})")
        self.resize(540, 540)
        self.setStyleSheet(ESTILO_CHAT)
        self.todos = list(reversed(prompts))        # el más nuevo arriba
        self.elegido = None
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar en todo lo que has pedido…")
        self.lista = QListWidget()
        self.info = QLabel("")
        self.info.setObjectName("estado")
        caja = QVBoxLayout(self)
        caja.addWidget(self.buscar)
        caja.addWidget(self.lista, 1)
        caja.addWidget(self.info)
        self.buscar.textChanged.connect(self.filtrar)
        self.lista.itemActivated.connect(self._elegir)
        self.lista.itemDoubleClicked.connect(self._elegir)
        self.filtrar("")
        self.buscar.setFocus()

    def filtrar(self, consulta: str):
        q = _plano(consulta.strip())
        self.lista.clear()
        coinciden = 0
        for fecha, texto in self.todos:
            if q in _plano(texto):
                coinciden += 1
                if self.lista.count() < 500:
                    item = QListWidgetItem(f"{fecha}   {texto}")
                    item.setData(Qt.UserRole, texto)
                    item.setToolTip(texto)
                    self.lista.addItem(item)
        self.info.setText(f"{coinciden} de {len(self.todos)} pedidos · doble clic para volver a usar uno")

    def _elegir(self, item):
        self.elegido = item.data(Qt.UserRole)
        self.accept()


class Chat(QWidget):
    """Ventana de chat: escribes (o hablas) y responde con el mismo cerebro. Recuerda todo lo que has pedido."""

    def __init__(self, puente: Puente, avatar: QWidget):
        super().__init__(None, Qt.Window)
        self.puente = puente
        self.avatar = avatar
        self.nombre = ajustes.obtener_nombre()
        self.setWindowTitle(f"Chat con {self.nombre}")
        self.resize(460, 620)
        self.setStyleSheet(ESTILO_CHAT)

        # cabecera: la peliroja animada + estado + botones
        self.mini = MiniAvatar(avatar)
        self.titulo = QLabel(self.nombre)
        self.titulo.setObjectName("titulo")
        self.estado_txt = QLabel(TEXTO_ESTADO["reposo"])
        self.estado_txt.setObjectName("estado")
        self.btn_voz = QPushButton()
        self.btn_voz.setObjectName("voz")
        self.btn_voz.setCheckable(True)
        self.btn_voz.setCursor(Qt.PointingHandCursor)
        self.btn_hist = QPushButton("📜 Historial")
        self.btn_hist.setObjectName("suave")
        self.btn_hist.setCursor(Qt.PointingHandCursor)
        botones = QHBoxLayout()
        botones.addWidget(self.btn_voz)
        botones.addWidget(self.btn_hist)
        botones.addStretch(1)
        textos = QVBoxLayout()
        textos.addWidget(self.titulo)
        textos.addWidget(self.estado_txt)
        textos.addLayout(botones)
        cabecera = QHBoxLayout()
        cabecera.addWidget(self.mini)
        cabecera.addLayout(textos, 1)

        self.historial = QTextBrowser()
        self.historial.setOpenExternalLinks(True)
        self.entrada = CampoPrompt()
        self.boton = QPushButton("Enviar")
        self.leer = QCheckBox("Leer en voz alta las respuestas a lo que escribo")
        self.leer.setChecked(ajustes.leer_respuestas())

        fila = QHBoxLayout()
        fila.addWidget(self.entrada, 1)
        fila.addWidget(self.boton)
        caja = QVBoxLayout(self)
        caja.addLayout(cabecera)
        caja.addWidget(self.historial, 1)
        caja.addLayout(fila)
        caja.addWidget(self.leer)

        self.entrada.returnPressed.connect(self.enviar)
        self.boton.clicked.connect(self.enviar)
        self.btn_voz.toggled.connect(self._cambiar_voz)
        self.btn_hist.clicked.connect(self.abrir_historial)
        self.leer.toggled.connect(ajustes.guardar_leer_respuestas)
        puente.mensaje.connect(self.agregar_externo)
        puente.estado.connect(self._estado)
        puente.nombre.connect(self._nombre)
        puente.voz_modo.connect(self.aplicar_voz)

        self.aplicar_voz(ajustes.voz_activa())
        self._cargar_conversacion_previa()

    # ------------------------------------------------------------ modo voz / escritura
    def _cambiar_voz(self, activa: bool):
        ajustes.guardar_voz_activa(activa)
        self.puente.voz_modo.emit(activa)

    def aplicar_voz(self, activa: bool):
        self.btn_voz.blockSignals(True)
        self.btn_voz.setChecked(activa)
        self.btn_voz.blockSignals(False)
        if activa:
            self.btn_voz.setText("🎙️ Voz: activada")
            self.btn_voz.setToolTip("Te escucha por el micrófono («Hey Jarvis» o clic en el avatar). Clic para apagarla.")
            self.entrada.setPlaceholderText("Háblame, o escribe aquí y pulsa Enter…")
        else:
            self.btn_voz.setText("🔇 Voz apagada · solo escritura")
            self.btn_voz.setToolTip("El micrófono está apagado: solo recibe lo que escribes. Clic para activar la voz.")
            self.entrada.setPlaceholderText("Escribe aquí y pulsa Enter…")

    # ------------------------------------------------------------ historial (todo lo que has pedido)
    def _cargar_conversacion_previa(self):
        try:
            previos = memoria.mensajes_para_chat(120)
            prompts = [t for _, t in memoria.todos_los_prompts(2000)]
        except Exception as e:
            print(f"⚠️  No pude cargar el historial: {e}")
            return
        self.entrada.cargar(prompts)
        if previos:
            self.historial.append(f"<p style='color:#8aa4c8'><i>— conversación anterior ({len(previos)} mensajes; "
                                  f"«📜 Historial» muestra todo lo que has pedido) —</i></p>")
            for fecha, quien, texto in previos:
                self._agregar(quien, texto, fecha)
            self.historial.append("<p style='color:#8aa4c8'><i>— ahora —</i></p>")

    def abrir_historial(self):
        try:
            prompts = memoria.todos_los_prompts(5000)
        except Exception as e:
            self._agregar("aviso", f"No pude leer el historial: {e}")
            return
        dlg = DialogoHistorial(self, prompts)
        if dlg.exec() == QDialog.Accepted and dlg.elegido:
            self.entrada.setText(dlg.elegido)
            self.entrada.setFocus()

    # ------------------------------------------------------------ mensajes
    def _agregar(self, quien: str, texto: str, fecha: str = ""):
        seguro = html.escape(texto).replace("\n", "<br>")
        hora = f" <span style='color:#5c7396;font-size:11px'>{html.escape(fecha)}</span>" if fecha else ""
        if quien == "tu":
            bloque = f"<p><b style='color:#8aa4c8'>Tú</b>{hora}<br>{seguro}</p>"
        elif quien == "ella":
            bloque = f"<p><b style='color:#5ee7ff'>{html.escape(self.nombre)}</b>{hora}<br>{seguro}</p>"
        else:
            bloque = f"<p style='color:#8aa4c8'><i>{seguro}</i></p>"
        self.historial.append(bloque)
        self.historial.verticalScrollBar().setValue(self.historial.verticalScrollBar().maximum())

    def agregar_externo(self, quien: str, texto: str):
        if (texto or "").strip():
            self._agregar(quien, texto.strip())
            if quien == "tu":                         # lo que dices por voz también se recuerda con ↑
                self.entrada.recordar(texto.strip())

    def enviar(self):
        texto = self.entrada.text().strip()
        if not texto:
            return
        self._agregar("tu", texto)
        self.entrada.recordar(texto)
        self.entrada.clear()
        self.puente.texto_escrito.emit(texto, self.leer.isChecked())

    def _estado(self, estado: str):
        self.estado_txt.setText(TEXTO_ESTADO.get(estado, ""))
        self.estado_txt.setStyleSheet("color: #fbbf24;" if estado == "pensando" else "")

    def _nombre(self, nombre: str):
        self.nombre = nombre
        self.titulo.setText(nombre)
        self.setWindowTitle(f"Chat con {nombre}")

    def mostrar(self):
        if not self.isVisible():
            g = self.avatar.frameGeometry()
            self.move(max(0, g.left() - self.width() - 12), max(0, g.bottom() - self.height()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.entrada.setFocus()


class Avatar(QWidget):
    def __init__(self, puente: Puente):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.puente = puente
        self.setWindowTitle("jarvis-avatar")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)

        self.d = config.AVATAR_TAMANO
        self.margen = 22
        self.alto_nombre = 24
        self.resize(self.d + 2 * self.margen, self.d + 2 * self.margen + self.alto_nombre)

        self.nombre = ajustes.obtener_nombre()
        self.estado = "reposo"
        self.voz = ajustes.voz_activa()
        self.fase = 0.0
        self.foto = self._cargar_foto()
        self.animaciones = self._cargar_animaciones()
        self.burbuja = Burbuja()
        self.chat = Chat(puente, self)
        self._insignia = QRectF()
        self._insignia_voz = QRectF()
        self._arrastre = None
        self._movido = False

        self.reloj = QTimer(self, timeout=self._animar)
        self.reloj.start(33)

        puente.estado.connect(self.set_estado)
        puente.mensaje.connect(self.mostrar_mensaje)
        puente.nombre.connect(self.set_nombre)
        puente.abrir_chat.connect(self.chat.mostrar)
        puente.voz_modo.connect(self.set_voz)
        self._activar_animacion()

        self._posicionar()
        self.show()

    # ---------------------------------------------------------- preparación
    def _cargar_foto(self) -> QPixmap:
        pm = QPixmap(config.AVATAR_PATH)
        if pm.isNull():                       # sin imagen: un círculo con la inicial
            pm = QPixmap(512, 512)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor("#16294d")); p.setPen(Qt.NoPen)
            p.drawEllipse(0, 0, 512, 512)
            p.setPen(QColor("#5ee7ff")); p.setFont(QFont("Sans", 200, QFont.Bold))
            p.drawText(QRectF(0, 0, 512, 512), Qt.AlignCenter, self.nombre[:1].upper())
            p.end()
        return pm.scaled(self.d * 2, self.d * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _cargar_animaciones(self) -> dict:
        """
        Avatar ANIMADO. Pon en assets/ un GIF/WebP/APNG animado (cualquiera que tengas o generes):
          avatar.gif                      -> se usa en todos los estados
          avatar_reposo.gif, avatar_escuchando.gif, avatar_pensando.gif, avatar_hablando.gif
                                          -> uno distinto por estado (opcional; los que falten usan avatar.gif)
        Si no hay ninguno, la imagen fija (avatar.png) se mueve sola: respira, se mece y reacciona al estado.
        """
        carpeta = os.path.dirname(config.AVATAR_PATH)
        general = self._abrir_movie(os.path.join(carpeta, "avatar"))
        anim = {}
        for estado in COLORES:
            anim[estado] = self._abrir_movie(os.path.join(carpeta, f"avatar_{estado}")) or general
        return {k: v for k, v in anim.items() if v is not None}

    def _abrir_movie(self, base):
        for ext in (".gif", ".webp", ".apng"):
            if os.path.isfile(base + ext):
                m = QMovie(base + ext)
                if m.isValid():
                    m.setCacheMode(QMovie.CacheAll)
                    m.jumpToFrame(0)          # solo corre la animación del estado actual (ver _activar_animacion)
                    return m
        return None

    def _activar_animacion(self):
        """Solo anima el GIF del estado actual (los demás quedan quietos: no gastan CPU)."""
        activa = self.animaciones.get(self.estado)
        for m in {id(m): m for m in self.animaciones.values()}.values():
            if m is activa:
                if m.state() != QMovie.Running:
                    m.start()
            elif m.state() != QMovie.NotRunning:
                m.stop()

    def _imagen_actual(self) -> QPixmap:
        m = self.animaciones.get(self.estado)
        if m is not None:
            pm = m.currentPixmap()
            if not pm.isNull():
                return pm
        return self.foto

    def _posicionar(self):
        guardada = ajustes.obtener_posicion()
        pantalla = QApplication.primaryScreen().availableGeometry()
        if guardada and pantalla.adjusted(-50, -50, 50, 50).contains(QPoint(*guardada)):
            self.move(*guardada)
        else:
            self.move(pantalla.right() - self.width() - 24, pantalla.bottom() - self.height() - 24)

    # --------------------------------------------------------------- estado
    def set_estado(self, estado: str):
        self.estado = estado if estado in COLORES else "reposo"
        self._activar_animacion()
        self.update()

    def set_voz(self, activa: bool):
        self.voz = activa
        if not activa:
            self.burbuja.hide()
        self.update()

    def alternar_voz(self):
        nuevo = not self.voz
        ajustes.guardar_voz_activa(nuevo)
        self.puente.voz_modo.emit(nuevo)    # avisa al chat, al avatar y al bucle de voz

    def set_nombre(self, nombre: str):
        self.nombre = nombre
        self.update()

    def mostrar_mensaje(self, quien: str, texto: str):
        texto = (texto or "").strip()
        if not texto or self.chat.isVisible():
            return
        seguro = texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if len(seguro) > 420:
            seguro = seguro[:420] + "…"
        etiqueta = {"tu": "<span style='color:#8aa4c8'>Tú:</span> ",
                    "ella": f"<b style='color:#5ee7ff'>{self.nombre}:</b> ",
                    "aviso": ""}.get(quien, "")
        self.burbuja.mostrar(etiqueta + seguro, max(5.0, len(texto) * 0.07), self)

    def _animar(self):
        self.fase += 0.12
        self.update()

    # --------------------------------------------------------------- dibujo
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        cx, cy = self.width() / 2, self.margen + self.d / 2
        r = self.d / 2
        color = COLORES[self.estado]

        # respiración / pulso según estado
        if self.estado == "hablando":
            pulso = 0.5 + 0.5 * math.sin(self.fase * 2.6)
            escala = 1.0 + 0.03 * pulso
        elif self.estado == "escuchando":
            pulso = 0.5 + 0.5 * math.sin(self.fase * 1.8)
            escala = 1.0 + 0.02 * pulso
        else:
            pulso = 0.5 + 0.5 * math.sin(self.fase * 0.5)
            escala = 1.0 + 0.012 * pulso

        # halo de luz
        halo = QRadialGradient(cx, cy, r + self.margen)
        c1, c2 = QColor(color), QColor(color)
        c1.setAlpha(int(70 + 90 * pulso)); c2.setAlpha(0)
        halo.setColorAt(0.70, c1); halo.setColorAt(1.0, c2)
        p.setPen(Qt.NoPen); p.setBrush(halo)
        p.drawEllipse(QRectF(cx - r - self.margen, cy - r - self.margen,
                             2 * (r + self.margen), 2 * (r + self.margen)))

        # foto recortada en círculo
        rr = r * escala
        camino = QPainterPath()
        camino.addEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))
        p.save(); p.setClipPath(camino)
        # Vida propia: respira (sube/baja), se mece y se inclina un poco; más al hablar/escuchar.
        # Se amplía 7 % para que al moverse nunca asomen bordes dentro del círculo.
        energia = {"hablando": 1.6, "escuchando": 1.2, "pensando": 0.8}.get(self.estado, 1.0) * config.AVATAR_MOVIMIENTO
        if self.estado in self.animaciones:
            energia *= 0.3          # el GIF ya trae su propio movimiento
        dx = 2.2 * energia * math.sin(self.fase * 0.37)
        dy = 2.6 * energia * math.sin(self.fase * 0.55)
        giro = 1.4 * energia * math.sin(self.fase * 0.31)
        p.translate(cx + dx, cy + dy); p.rotate(giro)
        lado = 2 * rr * 1.07
        img = self._imagen_actual()
        p.drawPixmap(QRectF(-lado / 2, -lado / 2, lado, lado), img, QRectF(img.rect()))
        p.restore()

        # aro de estado
        aro = QPen(color, 3); aro.setCapStyle(Qt.RoundCap)
        p.setPen(aro); p.setBrush(Qt.NoBrush)
        rect_aro = QRectF(cx - rr - 2, cy - rr - 2, 2 * rr + 4, 2 * rr + 4)
        if self.estado == "pensando":
            p.drawArc(rect_aro, int(-self.fase * 70 * 16), 110 * 16)
            p.drawArc(rect_aro, int((-self.fase * 70 + 180) * 16), 110 * 16)
        else:
            p.drawEllipse(rect_aro)

        # nombre
        p.setFont(QFont("Sans", 9, QFont.DemiBold))
        texto = self.nombre
        ancho = p.fontMetrics().horizontalAdvance(texto) + 18
        pill = QRectF(cx - ancho / 2, self.margen + self.d + 4, ancho, 18)
        fondo = QColor(10, 16, 32, 215)
        p.setPen(Qt.NoPen); p.setBrush(fondo)
        p.drawRoundedRect(pill, 9, 9)
        p.setPen(QColor("#eaf6ff"))
        p.drawText(pill, Qt.AlignCenter, texto)

        # insignia 💬: abre el chat de texto
        bx, by = cx + r * 0.74, cy + r * 0.74
        self._insignia = QRectF(bx - 14, by - 14, 28, 28)
        p.setBrush(QColor(10, 16, 32, 240)); p.setPen(QPen(color, 2))
        p.drawEllipse(self._insignia)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#eaf6ff"))
        p.drawRoundedRect(QRectF(bx - 8, by - 7, 16, 11), 3, 3)
        p.drawPolygon(QPolygonF([QPointF(bx - 4, by + 3), QPointF(bx - 7, by + 8), QPointF(bx + 2, by + 3)]))
        p.setBrush(color)
        for dx in (-4, 0, 4):
            p.drawEllipse(QPointF(bx + dx, by - 1.5), 1.2, 1.2)

        # insignia 🎙️: interruptor de voz (verde = te escucha · roja tachada = solo escritura)
        mx, my = cx - r * 0.74, cy + r * 0.74
        self._insignia_voz = QRectF(mx - 14, my - 14, 28, 28)
        tinta = QColor("#4ade80") if self.voz else QColor("#ff6b81")
        p.setBrush(QColor(10, 16, 32, 240)); p.setPen(QPen(tinta, 2))
        p.drawEllipse(self._insignia_voz)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#eaf6ff"))
        p.drawRoundedRect(QRectF(mx - 3, my - 9, 6, 11), 3, 3)           # cuerpo del micrófono
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor("#eaf6ff"), 1.6))
        p.drawArc(QRectF(mx - 6, my - 6, 12, 11), 180 * 16, 180 * 16)     # soporte
        p.drawLine(QPointF(mx, my + 5), QPointF(mx, my + 8))
        p.drawLine(QPointF(mx - 3, my + 8), QPointF(mx + 3, my + 8))
        if not self.voz:
            p.setPen(QPen(tinta, 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(mx - 8, my - 8), QPointF(mx + 8, my + 8))

    # ---------------------------------------------------------------- ratón
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._arrastre = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._movido = False

    def mouseMoveEvent(self, e):
        if self._arrastre is not None and e.buttons() & Qt.LeftButton:
            destino = e.globalPosition().toPoint() - self._arrastre
            if (destino - self.frameGeometry().topLeft()).manhattanLength() > 3:
                self._movido = True
            self.move(destino)
            if self.burbuja.isVisible():
                self.burbuja.hide()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._arrastre is not None:
            if self._movido:
                ajustes.guardar_posicion(self.x(), self.y())
            elif self._insignia.contains(e.position()):
                self.puente.abrir_chat.emit()
            elif self._insignia_voz.contains(e.position()):
                self.alternar_voz()
            elif not self.voz:
                self.puente.abrir_chat.emit()      # voz apagada: un clic abre el chat para escribir
            else:
                self.puente.activar.emit()
            self._arrastre = None

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        accion_voz = menu.addAction("🎙️  Voz activada (desmarca para usar solo escritura)")
        accion_voz.setCheckable(True)
        accion_voz.setChecked(self.voz)
        accion_voz.triggered.connect(self.alternar_voz)
        menu.addAction("🎙️  Hablar ahora", self._hablar_ahora)
        menu.addAction("💬  Escribir…", self.puente.abrir_chat.emit)
        menu.addAction("🪟  ¿Qué ventanas tengo abiertas?", self.puente.ver_ventanas.emit)
        menu.addAction("✏️  Cambiar nombre…", self._pedir_nombre)
        menu.addSeparator()
        menu.addAction("Salir", self.puente.salir.emit)
        menu.exec(e.globalPos())

    def _hablar_ahora(self):
        if not self.voz:
            self.alternar_voz()            # pedirle «hablar ahora» enciende la voz
        self.puente.activar.emit()

    def _pedir_nombre(self):
        nombre, ok = QInputDialog.getText(self, "Nombre", "¿Cómo quieres llamarla?", text=self.nombre)
        if ok and ajustes.limpiar_nombre(nombre):
            ajustes.guardar_nombre(nombre)     # avisa a la interfaz por el mecanismo de suscripción

    def closeEvent(self, e):
        self.burbuja.hide()
        super().closeEvent(e)


def crear_aplicacion():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    return app
