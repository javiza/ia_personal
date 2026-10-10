"""
Avatar flotante en pantalla (PySide6/Qt): un icono circular siempre visible, arrastrable,
que cambia de color y "respira" según lo que hace:
  reposo (cian) · escuchando (verde) · pensando (ámbar, arco giratorio) · hablando (rosa)
- Clic: la activa sin decir la palabra de activación. Clic en la insignia 💬: abre el chat de texto.
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMenu, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

import ajustes
import config

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
QPushButton { background: #5ee7ff; color: #06182e; border: none; border-radius: 10px;
              padding: 8px 16px; font-weight: bold; }
QPushButton:hover { background: #8ff0ff; }
QCheckBox { color: #8aa4c8; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #5ee7ff; border-radius: 4px; background: #101a30; }
QCheckBox::indicator:checked { background: #5ee7ff; }
QLabel#pensando { color: #fbbf24; }
"""


class Chat(QWidget):
    """Ventana de chat: escribes y responde con el mismo cerebro que la voz."""

    def __init__(self, puente: Puente, avatar: QWidget):
        super().__init__(None, Qt.Window)
        self.puente = puente
        self.avatar = avatar
        self.nombre = ajustes.obtener_nombre()
        self.setWindowTitle(f"Chat con {self.nombre}")
        self.resize(430, 540)
        self.setStyleSheet(ESTILO_CHAT)

        self.historial = QTextBrowser()
        self.historial.setOpenExternalLinks(True)
        self.pensando = QLabel("")
        self.pensando.setObjectName("pensando")
        self.pensando.hide()
        self.entrada = QLineEdit()
        self.entrada.setPlaceholderText("Escribe aquí y pulsa Enter…")
        self.boton = QPushButton("Enviar")
        self.leer = QCheckBox("Leer las respuestas en voz alta")

        fila = QHBoxLayout()
        fila.addWidget(self.entrada, 1)
        fila.addWidget(self.boton)
        caja = QVBoxLayout(self)
        caja.addWidget(self.historial, 1)
        caja.addWidget(self.pensando)
        caja.addLayout(fila)
        caja.addWidget(self.leer)

        self.entrada.returnPressed.connect(self.enviar)
        self.boton.clicked.connect(self.enviar)
        puente.mensaje.connect(self.agregar_externo)
        puente.estado.connect(self._estado)
        puente.nombre.connect(self._nombre)

    # ------------------------------------------------------------ mensajes
    def _agregar(self, quien: str, texto: str):
        seguro = html.escape(texto).replace("\n", "<br>")
        if quien == "tu":
            bloque = f"<p><b style='color:#8aa4c8'>Tú</b><br>{seguro}</p>"
        elif quien == "ella":
            bloque = f"<p><b style='color:#5ee7ff'>{html.escape(self.nombre)}</b><br>{seguro}</p>"
        else:
            bloque = f"<p style='color:#8aa4c8'><i>{seguro}</i></p>"
        self.historial.append(bloque)
        self.historial.verticalScrollBar().setValue(self.historial.verticalScrollBar().maximum())

    def agregar_externo(self, quien: str, texto: str):
        if (texto or "").strip():
            self._agregar(quien, texto.strip())

    def enviar(self):
        texto = self.entrada.text().strip()
        if not texto:
            return
        self._agregar("tu", texto)
        self.entrada.clear()
        self.puente.texto_escrito.emit(texto, self.leer.isChecked())

    def _estado(self, estado: str):
        if estado == "pensando":
            self.pensando.setText(f"{self.nombre} está pensando…")
            self.pensando.show()
        else:
            self.pensando.hide()

    def _nombre(self, nombre: str):
        self.nombre = nombre
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
        self.fase = 0.0
        self.foto = self._cargar_foto()
        self.animaciones = self._cargar_animaciones()
        self.burbuja = Burbuja()
        self.chat = Chat(puente, self)
        self._insignia = QRectF()
        self._arrastre = None
        self._movido = False

        self.reloj = QTimer(self, timeout=self._animar)
        self.reloj.start(33)

        puente.estado.connect(self.set_estado)
        puente.mensaje.connect(self.mostrar_mensaje)
        puente.nombre.connect(self.set_nombre)
        puente.abrir_chat.connect(self.chat.mostrar)

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
                    m.start()
                    return m
        return None

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
        self.update()

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
            else:
                self.puente.activar.emit()
            self._arrastre = None

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction("🎙️  Hablar ahora", self.puente.activar.emit)
        menu.addAction("💬  Escribir…", self.puente.abrir_chat.emit)
        menu.addAction("🪟  ¿Qué ventanas tengo abiertas?", self.puente.ver_ventanas.emit)
        menu.addAction("✏️  Cambiar nombre…", self._pedir_nombre)
        menu.addSeparator()
        menu.addAction("Salir", self.puente.salir.emit)
        menu.exec(e.globalPos())

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
