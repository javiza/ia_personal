"""
Avatar flotante en pantalla (PySide6/Qt): un icono circular siempre visible, arrastrable,
que cambia de color y "respira" según lo que hace:
  reposo (cian) · escuchando (verde) · pensando (ámbar, arco giratorio) · hablando (rosa)
- Clic: la activa sin decir la palabra de activación. Clic en la insignia 💬: abre el chat de texto.
- Insignia 🎙️: interruptor de voz. Apagada = solo escritura (no se abre el micrófono).
- Avatar animado: un GIF por estado (assets/avatar_reposo|escuchando|pensando|hablando.gif; ver crear_avatar_gifs.py).
- Arrastrar: mueve el icono (recuerda dónde lo dejaste).
- Clic derecho: menú (hablar, ver ventanas, cambiar nombre, esconder, salir).
- Insignia «–» (arriba a la derecha) o menú: esconde el avatar y deja un icono en la bandeja del sistema (junto al reloj,
  wifi, batería…). Clic en ese icono = mostrar/esconder; clic derecho = menú. Solo existe en la versión de escritorio.
- Modo banner (por defecto en PC): el avatar es un banner pequeño pegado al borde izquierdo de la pantalla; se arrastra
  solo en vertical y la flecha del costado (◀/▶) lo retrae contra el borde o lo vuelve a sacar. Clic derecho: alternar
  con el modo flotante (círculo libre).
- Ventana de prompt (chat): al iniciar, y al pulsar «➖ Retraer» o la X, se retrae y queda como un botón redondo 💬 que
  se mueve libremente por la pantalla (se recuerda dónde lo dejaste). Clic en el botón = despliega el chat de nuevo.
- Muestra lo que dices y lo que responde en una burbuja que se oculta sola.
"""
import html
import math
import os
import shutil
import sys
from string import Template

# En sesiones Wayland, Qt nativo ignora "siempre encima" y la posición; XWayland sí las respeta.
if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QFont, QIcon, QImageReader, QKeySequence, QMovie, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QFileDialog, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSystemTrayIcon,
                               QTextBrowser, QVBoxLayout, QWidget)

import ajustes
import config
import rutas

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


EXT_IMAGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _es_imagen(ruta: str) -> bool:
    return os.path.splitext(ruta)[1].lower() in EXT_IMAGEN


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
    historial_cambiado = Signal()       # se borraron pedidos del historial: refrescar el chat y la memoria de la conversación
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
        if getattr(ancla, "banner", False):          # banner en el borde izquierdo: el globo sale a su derecha
            x = g.right() + 6
            y = min(max(pantalla.top() + 6, g.top()), pantalla.bottom() - self.height() - 6)
        else:
            x = min(max(pantalla.left() + 6, g.right() - self.width()), pantalla.right() - self.width() - 6)
            y = g.top() - self.height() - 6
            if y < pantalla.top() + 6:
                y = g.bottom() + 6
        self.move(x, y)
        self.show()
        self.temporizador.start(int(segundos * 1000))


_PLANTILLA_CHAT = Template("""
QWidget { background: $fondo; color: $texto; font-size: 13px; }
QTextBrowser { background: $panel; border: 1px solid $borde; border-radius: 10px; padding: 8px; }
QLineEdit { background: $panel; border: 1px solid $acento; border-radius: 10px; padding: 8px 10px; }
QListWidget { background: $panel; border: 1px solid $borde; border-radius: 10px; padding: 4px; }
QListWidget::item { padding: 6px 4px; border-bottom: 1px solid $suave; }
QListWidget::item:selected { background: $suave_h; color: $sel_t; }
QPushButton { background: $acento; color: $sobre_acento; border: none; border-radius: 10px;
              padding: 8px 16px; font-weight: bold; }
QPushButton:hover { background: $acento_h; }
QPushButton#suave { background: $suave; color: $suave_t; font-weight: normal; padding: 6px 12px; }
QPushButton#suave:hover { background: $suave_h; }
QPushButton#peligro { background: $pel_bg; color: $pel_t; border: 1px solid $pel_b; font-weight: normal; padding: 6px 10px; }
QPushButton#peligro:hover { background: $pel_h; }
QPushButton#peligro:disabled { background: $dis_bg; color: $dis_t; border: 1px solid $borde; }
QPushButton#voz { background: $voz; color: $voz_t; padding: 6px 12px; }
QPushButton#voz:hover { background: $voz_h; }
QPushButton#voz:!checked { background: $pel_bg; color: $pel_t; border: 1px solid $pel_b; }
QPushButton#voz:!checked:hover { background: $pel_h; }
QCheckBox { color: $tenue; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $acento; border-radius: 4px; background: $panel; }
QCheckBox::indicator:checked { background: $acento; }
QLabel#titulo { font-size: 17px; font-weight: bold; color: $texto; }
QLabel#estado { color: $tenue; }
QLabel#pensando { color: $pensando; }
QFrame#adjunto { background: $panel; border: 1px solid $borde; border-radius: 10px; }
QFrame#adjunto QLabel { background: transparent; }
QPushButton#quitar { background: $suave; color: $suave_t; border: none; border-radius: 11px; padding: 0; font-weight: bold;
                     min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }
QPushButton#quitar:hover { background: $pel_bg; color: $pel_t; }
""")

# Dos paletas: el chat se puede pasar de modo oscuro a claro con el botón «Modo claro / Modo oscuro» (se recuerda en ajustes.json).
PALETAS = {
    "oscuro": dict(fondo="#0b1222", texto="#eaf6ff", panel="#101a30", borde="#25406b", acento="#5ee7ff",
                   acento_h="#8ff0ff", sobre_acento="#06182e", suave="#16294d", suave_h="#1d3a66", suave_t="#cfe6ff",
                   sel_t="#ffffff", pel_bg="#3a1f2b", pel_t="#ff9fb0", pel_b="#ff6b81", pel_h="#4d2736",
                   dis_bg="#141c2e", dis_t="#4b5b78", voz="#4ade80", voz_t="#04210f", voz_h="#7cf0a6",
                   tenue="#8aa4c8", hora="#5c7396", pensando="#fbbf24"),
    "claro": dict(fondo="#f5f7fa", texto="#1b2535", panel="#ffffff", borde="#c8d2e0", acento="#1d78c2",
                  acento_h="#3a8fd6", sobre_acento="#ffffff", suave="#e4ebf4", suave_h="#d3deec", suave_t="#1b2535",
                  sel_t="#0f2a44", pel_bg="#fde8eb", pel_t="#b3263a", pel_b="#e07a88", pel_h="#fbd5db",
                  dis_bg="#eceff4", dis_t="#9aa6b8", voz="#2f9e5b", voz_t="#ffffff", voz_h="#3fb56d",
                  tenue="#5d6b80", hora="#8a97aa", pensando="#b7791f"),
}


def estilo_chat(tema: str) -> str:
    return _PLANTILLA_CHAT.substitute(PALETAS.get(tema, PALETAS["oscuro"]))


ESTILO_CHAT = estilo_chat("oscuro")

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
    """
    Todo lo que le has pedido, con buscador. Doble clic = volver a usarlo.
    Se puede borrar: lo seleccionado (Supr), todo lo que coincide con la búsqueda, o todo el historial.
    Al borrar un pedido también se borra la respuesta que dio.
    """

    def __init__(self, padre, prompts):
        super().__init__(padre)
        self.resize(560, 580)
        self.setStyleSheet(estilo_chat(ajustes.tema()))
        self.todos = list(reversed(prompts))        # [(uid, fecha, texto)], el más nuevo arriba
        self.visibles: list[str] = []               # uids que coinciden con la búsqueda actual
        self.elegido = None
        self.cambio = False                         # ¿se borró algo? (el chat se refresca al cerrar)
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar en todo lo que has pedido…")
        self.lista = QListWidget()
        self.lista.setSelectionMode(QListWidget.ExtendedSelection)
        self.info = QLabel("")
        self.info.setObjectName("estado")
        self.btn_sel = QPushButton("🗑 Borrar seleccionados")
        self.btn_vis = QPushButton("🗑 Borrar los que coinciden")
        self.btn_todo = QPushButton("🗑 Borrar todo")
        for b in (self.btn_sel, self.btn_vis, self.btn_todo):
            b.setObjectName("peligro")
            b.setCursor(Qt.PointingHandCursor)
        fila = QHBoxLayout()
        fila.addWidget(self.btn_sel)
        fila.addWidget(self.btn_vis)
        fila.addWidget(self.btn_todo)
        caja = QVBoxLayout(self)
        caja.addWidget(self.buscar)
        caja.addWidget(self.lista, 1)
        caja.addWidget(self.info)
        caja.addLayout(fila)
        self.buscar.textChanged.connect(self.filtrar)
        self.lista.itemActivated.connect(self._elegir)
        self.lista.itemDoubleClicked.connect(self._elegir)
        self.lista.itemSelectionChanged.connect(self._botones)
        self.btn_sel.clicked.connect(self.borrar_seleccionados)
        self.btn_vis.clicked.connect(self.borrar_visibles)
        self.btn_todo.clicked.connect(self.borrar_todo)
        QShortcut(QKeySequence.Delete, self.lista, activated=self.borrar_seleccionados)
        self.filtrar("")
        self.buscar.setFocus()

    def _titulo(self):
        self.setWindowTitle(f"Historial de pedidos ({len(self.todos)})")

    def _botones(self):
        n = len(self.lista.selectedItems())
        self.btn_sel.setEnabled(n > 0)
        self.btn_sel.setText(f"🗑 Borrar seleccionados ({n})" if n else "🗑 Borrar seleccionados")
        self.btn_vis.setEnabled(bool(self.visibles))
        self.btn_vis.setText(f"🗑 Borrar los {len(self.visibles)} que coinciden" if self.buscar.text().strip()
                             else "🗑 Borrar los que coinciden")
        self.btn_vis.setVisible(bool(self.buscar.text().strip()))      # sin búsqueda sería igual a «Borrar todo»
        self.btn_todo.setEnabled(bool(self.todos))

    def filtrar(self, consulta: str):
        q = _plano(consulta.strip())
        self.lista.clear()
        self.visibles = []
        for uid, fecha, texto in self.todos:
            if q in _plano(texto):
                self.visibles.append(uid)
                if self.lista.count() < 500:
                    item = QListWidgetItem(f"{fecha}   {texto}")
                    item.setData(Qt.UserRole, texto)
                    item.setData(Qt.UserRole + 1, uid)
                    item.setToolTip(texto)
                    self.lista.addItem(item)
        self.info.setText(f"{len(self.visibles)} de {len(self.todos)} pedidos · doble clic: volver a usar · "
                          f"Supr: borrar lo seleccionado")
        self._titulo()
        self._botones()

    def _elegir(self, item):
        self.elegido = item.data(Qt.UserRole)
        self.accept()

    # ------------------------------------------------------------ borrar
    def _confirmar(self, texto: str) -> bool:
        caja = QMessageBox(self)
        caja.setIcon(QMessageBox.Warning)
        caja.setWindowTitle("Borrar del historial")
        caja.setText(texto)
        caja.setInformativeText("También se borra la respuesta que dio. No se puede deshacer.")
        caja.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        caja.setDefaultButton(QMessageBox.Cancel)
        caja.button(QMessageBox.Yes).setText("Borrar")
        caja.button(QMessageBox.Cancel).setText("Cancelar")
        return caja.exec() == QMessageBox.Yes

    def _borrar(self, uids):
        try:
            memoria.borrar_prompts(uids)
        except Exception as e:
            QMessageBox.warning(self, "Historial", f"No pude borrar: {e}")
            return
        fuera = set(uids)
        self.todos = [t for t in self.todos if t[0] not in fuera]
        self.cambio = True
        self.filtrar(self.buscar.text())

    def borrar_seleccionados(self):
        uids = [i.data(Qt.UserRole + 1) for i in self.lista.selectedItems()]
        if uids and self._confirmar(f"¿Borrar {len(uids)} pedido(s) seleccionado(s)?"):
            self._borrar(uids)

    def borrar_visibles(self):
        if self.visibles and self._confirmar(f"¿Borrar los {len(self.visibles)} pedidos que coinciden con «{self.buscar.text().strip()}»?"):
            self._borrar(list(self.visibles))

    def borrar_todo(self):
        if self.todos and self._confirmar(f"¿Borrar TODO el historial ({len(self.todos)} pedidos)?"):
            try:
                memoria.borrar_todo_el_historial()
            except Exception as e:
                QMessageBox.warning(self, "Historial", f"No pude borrar: {e}")
                return
            self.todos = []
            self.cambio = True
            self.filtrar("")


class BotonChat(QWidget):
    """Ventana de prompt retraída: un botón redondo y movible por toda la pantalla. Clic = desplegar el chat."""
    LADO = 58

    def __init__(self, chat: "Chat"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.chat = chat
        self.setWindowTitle("jarvis-boton-chat")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.LADO, self.LADO)
        self.setToolTip("Clic: abrir el chat · Arrastra para moverme")
        self._arrastre = None
        self._movido = False
        self.reloj = QTimer(self, timeout=self.update)

    def showEvent(self, e):
        self.reloj.start(50)
        super().showEvent(e)

    def hideEvent(self, e):
        self.reloj.stop()
        super().hideEvent(e)

    def _limitar(self, punto: QPoint) -> QPoint:
        """Que el botón no se pierda fuera de la pantalla (la que tenga más cerca)."""
        centro = punto + QPoint(self.width() // 2, self.height() // 2)
        pantalla = (QApplication.screenAt(centro) or self.screen() or QApplication.primaryScreen()).availableGeometry()
        x = min(max(punto.x(), pantalla.left()), pantalla.right() - self.width() + 1)
        y = min(max(punto.y(), pantalla.top()), pantalla.bottom() - self.height() + 1)
        return QPoint(x, y)

    def colocar(self, preferida: QPoint = None):
        guardada = ajustes.boton_chat_pos()
        if guardada:
            destino = QPoint(*guardada)
        elif preferida is not None:
            destino = preferida
        else:
            pantalla = QApplication.primaryScreen().availableGeometry()
            destino = QPoint(pantalla.right() - self.width() - 24, pantalla.bottom() - self.height() - 24)
        self.move(self._limitar(destino))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = COLORES.get(getattr(self.chat, "_estado_actual", "reposo"), COLORES["reposo"])
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        fondo = QRadialGradient(rect.center(), rect.width() / 2)
        fondo.setColorAt(0, QColor("#16294d")); fondo.setColorAt(1, QColor("#0b1222"))
        p.setPen(Qt.NoPen); p.setBrush(fondo)
        p.drawEllipse(rect)
        aro = QPen(color, 3); aro.setCapStyle(Qt.RoundCap)
        p.setPen(aro); p.setBrush(Qt.NoBrush)
        if getattr(self.chat, "_estado_actual", "reposo") == "pensando":
            giro = int(-self.chat.avatar.fase * 70 * 16)
            p.drawArc(rect, giro, 110 * 16)
            p.drawArc(rect, giro + 180 * 16, 110 * 16)
        else:
            p.drawEllipse(rect)
        p.setPen(QColor("#eaf6ff")); p.setFont(QFont("Sans", 17))
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, "💬")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._arrastre = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._movido = False

    def mouseMoveEvent(self, e):
        if self._arrastre is not None and e.buttons() & Qt.LeftButton:
            destino = self._limitar(e.globalPosition().toPoint() - self._arrastre)
            if (destino - self.frameGeometry().topLeft()).manhattanLength() > 3:
                self._movido = True
            self.move(destino)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._arrastre is not None:
            self._arrastre = None
            if self._movido:
                ajustes.guardar_boton_chat_pos(self.x(), self.y())
            else:
                self.chat.mostrar()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction("💬  Abrir chat", self.chat.mostrar)
        menu.addSeparator()
        menu.addAction("Salir", self.chat.puente.salir.emit)
        menu.exec(e.globalPos())


class Chat(QWidget):
    """Ventana de chat: escribes (o hablas) y responde con el mismo cerebro. Recuerda todo lo que has pedido."""

    def __init__(self, puente: Puente, avatar: QWidget):
        super().__init__(None, Qt.Window)
        self.puente = puente
        self.avatar = avatar
        self.nombre = ajustes.obtener_nombre()
        self.setWindowTitle(f"Chat con {self.nombre}")
        self.resize(460, 620)
        self.tema = ajustes.tema()                  # 'oscuro' | 'claro'
        self._entradas = []                         # lo que hay en pantalla: (quien, texto, fecha); sirve para repintar al cambiar de tema
        self._estado_actual = "reposo"
        self._adjuntos = []                         # archivos adjuntos que aún no se envían (se ven como vista previa)
        self.setStyleSheet(estilo_chat(self.tema))
        self.boton_flotante = BotonChat(self)       # lo que queda en pantalla cuando el chat se retrae

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
        self.btn_limpiar = QPushButton("🧹 Limpiar pantalla")
        self.btn_limpiar.setObjectName("suave")
        self.btn_limpiar.setToolTip("Oculta los mensajes anteriores. No borra tu historial («📜 Historial» sigue teniéndolo todo).")
        self.btn_limpiar.setCursor(Qt.PointingHandCursor)
        self.btn_tema = QPushButton()
        self.btn_tema.setObjectName("suave")
        self.btn_tema.setCursor(Qt.PointingHandCursor)
        self.btn_retraer = QPushButton("➖ Retraer")
        self.btn_retraer.setObjectName("suave")
        self.btn_retraer.setToolTip("Convierte esta ventana en un botón que puedes mover por la pantalla")
        self.btn_retraer.setCursor(Qt.PointingHandCursor)
        botones = QHBoxLayout()
        botones.addWidget(self.btn_voz)
        botones.addWidget(self.btn_hist)
        botones.addStretch(1)
        botones2 = QHBoxLayout()
        botones2.addWidget(self.btn_limpiar)
        botones2.addWidget(self.btn_tema)
        botones2.addWidget(self.btn_retraer)
        botones2.addStretch(1)
        textos = QVBoxLayout()
        textos.addWidget(self.titulo)
        textos.addWidget(self.estado_txt)
        textos.addLayout(botones)
        textos.addLayout(botones2)
        cabecera = QHBoxLayout()
        cabecera.addWidget(self.mini)
        cabecera.addLayout(textos, 1)

        self.historial = QTextBrowser()
        self.historial.setOpenExternalLinks(True)
        self.entrada = CampoPrompt()
        self.boton = QPushButton("Enviar")
        self.btn_adj = QPushButton("📎")
        self.btn_adj.setObjectName("suave")
        self.btn_adj.setToolTip("Adjuntar un archivo para que lo lea, edite o convierta")
        self.btn_adj.setCursor(Qt.PointingHandCursor)
        self.leer = QCheckBox("Leer en voz alta las respuestas a lo que escribo")
        self.leer.setChecked(ajustes.leer_respuestas())

        fila = QHBoxLayout()
        fila.addWidget(self.btn_adj)
        fila.addWidget(self.entrada, 1)
        fila.addWidget(self.boton)
        caja = QVBoxLayout(self)
        caja.addLayout(cabecera)
        caja.addWidget(self.historial, 1)
        self.zona_adj = QWidget()                   # vista previa de lo adjuntado: SEPARADA de la caja donde escribes
        self.caja_adj = QVBoxLayout(self.zona_adj)
        self.caja_adj.setContentsMargins(0, 0, 0, 0)
        self.caja_adj.setSpacing(4)
        self.zona_adj.hide()
        caja.addWidget(self.zona_adj)
        caja.addLayout(fila)
        caja.addWidget(self.leer)

        self.entrada.returnPressed.connect(self.enviar)
        self.boton.clicked.connect(self.enviar)
        self.btn_voz.toggled.connect(self._cambiar_voz)
        self.btn_hist.clicked.connect(self.abrir_historial)
        self.btn_limpiar.clicked.connect(self.limpiar_pantalla)
        self.btn_tema.clicked.connect(self.alternar_tema)
        self.btn_retraer.clicked.connect(self.retraer)
        self.btn_adj.clicked.connect(self.adjuntar)
        self.leer.toggled.connect(ajustes.guardar_leer_respuestas)
        puente.mensaje.connect(self.agregar_externo)
        puente.estado.connect(self._estado)
        puente.nombre.connect(self._nombre)
        puente.voz_modo.connect(self.aplicar_voz)

        self._texto_boton_tema()
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

    # ------------------------------------------------------------ tema claro / oscuro y limpiar pantalla
    def _texto_boton_tema(self):
        if self.tema == "oscuro":
            self.btn_tema.setText("☀️ Modo claro")
            self.btn_tema.setToolTip("Cambiar al tema claro")
        else:
            self.btn_tema.setText("🌙 Modo oscuro")
            self.btn_tema.setToolTip("Cambiar al tema oscuro")

    def alternar_tema(self):
        self.tema = "claro" if self.tema == "oscuro" else "oscuro"
        ajustes.guardar_tema(self.tema)
        self.setStyleSheet(estilo_chat(self.tema))
        self._texto_boton_tema()
        self._estado(self._estado_actual)               # el color de «Pensando…» también cambia
        self.historial.clear()                          # se repinta lo que había, con los colores del tema nuevo
        for quien, texto, fecha, adj in self._entradas:
            self._pintar(quien, texto, fecha, adj)

    def limpiar_pantalla(self):
        """Deja la pantalla en blanco. NO borra nada: el historial y la memoria siguen intactos, y al reabrir el chat
        tampoco vuelven a aparecer los mensajes anteriores (se guarda desde cuándo mostrar)."""
        self._entradas.clear()
        self.historial.clear()
        try:
            ajustes.guardar_chat_desde(memoria._ahora())
        except Exception as e:
            print(f"⚠️  No pude recordar que limpiaste la pantalla: {e}")
        self._agregar("sep", "pantalla limpiada · tu historial sigue guardado en «📜 Historial»")

    # ------------------------------------------------------------ historial (todo lo que has pedido)
    def _cargar_conversacion_previa(self):
        try:
            previos = memoria.mensajes_para_chat(120, ajustes.chat_desde())
            prompts = [t for _, t in memoria.todos_los_prompts(2000)]
        except Exception as e:
            print(f"⚠️  No pude cargar el historial: {e}")
            return
        self.entrada.cargar(prompts)
        if previos:
            self._agregar("sep", f"— conversación anterior ({len(previos)} mensajes; «📜 Historial» muestra todo lo que has pedido) —")
            for fecha, quien, texto in previos:
                self._agregar(quien, texto, fecha)
            self._agregar("sep", "— ahora —")

    def abrir_historial(self):
        try:
            prompts = memoria.prompts_con_id(5000)
        except Exception as e:
            self._agregar("aviso", f"No pude leer el historial: {e}")
            return
        dlg = DialogoHistorial(self, prompts)
        aceptado = dlg.exec() == QDialog.Accepted
        if dlg.cambio:                                   # se borró algo: el chat y la memoria de la conversación se ponen al día
            self.refrescar_conversacion()
            self.puente.historial_cambiado.emit()
        if aceptado and dlg.elegido:
            self.entrada.setText(dlg.elegido)
            self.entrada.setFocus()

    def refrescar_conversacion(self):
        self._entradas.clear()
        self.historial.clear()
        self._cargar_conversacion_previa()

    # ------------------------------------------------------------ mensajes
    def _agregar(self, quien: str, texto: str, fecha: str = "", adjuntos=()):
        self._entradas.append((quien, texto, fecha, list(adjuntos)))
        self._pintar(quien, texto, fecha, adjuntos)

    def _pintar(self, quien: str, texto: str, fecha: str = "", adjuntos=()):
        c = PALETAS[self.tema]
        seguro = html.escape(texto).replace("\n", "<br>")
        hora = f" <span style='color:{c['hora']};font-size:11px'>{html.escape(fecha)}</span>" if fecha else ""
        if quien == "tu":
            extra = ""
            for ruta in adjuntos:                       # lo que adjuntaste se ve en el chat (la imagen, en miniatura)
                if _es_imagen(ruta):
                    ancho = min(220, QImageReader(ruta).size().width() or 220)
                    extra += f"<br><img src='{html.escape(QUrl.fromLocalFile(ruta).toString())}' width='{ancho}'>"
                else:
                    extra += f"<br>📎 {html.escape(os.path.basename(ruta))}"
            bloque = f"<p><b style='color:{c['tenue']}'>Tú</b>{hora}<br>{seguro}{extra}</p>"
        elif quien == "ella":
            bloque = f"<p><b style='color:{c['acento']}'>{html.escape(self.nombre)}</b>{hora}<br>{seguro}</p>"
        else:                                          # 'aviso' y 'sep' (separadores)
            bloque = f"<p style='color:{c['tenue']}'><i>{seguro}</i></p>"
        self.historial.append(bloque)
        self.historial.verticalScrollBar().setValue(self.historial.verticalScrollBar().maximum())

    def agregar_externo(self, quien: str, texto: str):
        if (texto or "").strip():
            self._agregar(quien, texto.strip())
            if quien == "tu":                         # lo que dices por voz también se recuerda con ↑
                self.entrada.recordar(texto.strip())

    def adjuntar(self):
        """📎: elige uno o más archivos. Si ya están en una carpeta que ella puede usar (Escritorio, Documentos...) se usa
        esa ruta; si no, se COPIA a ~/JarvisArchivos (el original no se toca). Queda como vista previa (la imagen se ve)
        encima de la caja; escribes la orden («resúmelo», «cámbiale el título»...) y al enviar va junto con el archivo."""
        elegidos, _ = QFileDialog.getOpenFileNames(self, "Elegir archivo(s)", os.path.expanduser("~"))
        usados = []
        for origen in elegidos:
            try:
                if rutas.resolver_ruta(origen):
                    usados.append(origen)
                    continue
                os.makedirs(config.OUTPUT_DIR, exist_ok=True)
                base, ext = os.path.splitext(os.path.basename(origen))
                destino, i = os.path.join(config.OUTPUT_DIR, base + ext), 2
                while os.path.exists(destino):
                    destino = os.path.join(config.OUTPUT_DIR, f"{base} ({i}){ext}")
                    i += 1
                shutil.copy2(origen, destino)
                usados.append(destino)
                self._agregar("aviso", f"📎 Copié «{os.path.basename(origen)}» a {config.OUTPUT_DIR} para poder trabajarlo.")
            except OSError as e:
                self._agregar("aviso", f"No pude adjuntar «{os.path.basename(origen)}»: {e}")
        nuevos = [u for u in usados if u not in self._adjuntos]
        if nuevos:
            self._adjuntos += nuevos
            self._repintar_adjuntos()
            self.entrada.setFocus()

    def _repintar_adjuntos(self):
        while self.caja_adj.count():
            it = self.caja_adj.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for ruta in self._adjuntos:
            marco = QFrame()
            marco.setObjectName("adjunto")
            fila = QHBoxLayout(marco)
            fila.setContentsMargins(6, 6, 6, 6)
            mini = QLabel()
            mini.setFixedSize(56, 56)
            mini.setAlignment(Qt.AlignCenter)
            pm = QPixmap(ruta) if _es_imagen(ruta) else QPixmap()
            if not pm.isNull():
                mini.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                mini.setText("📄")
                mini.setStyleSheet("font-size: 28px;")
            nombre = QLabel()
            nombre.setToolTip(ruta)
            nombre.setText(nombre.fontMetrics().elidedText(os.path.basename(ruta), Qt.ElideMiddle, 280))
            quitar = QPushButton("✕")
            quitar.setObjectName("quitar")
            quitar.setToolTip("Quitar adjunto")
            quitar.setCursor(Qt.PointingHandCursor)
            quitar.clicked.connect(lambda _=False, r=ruta: self.quitar_adjunto(r))
            fila.addWidget(mini)
            fila.addWidget(nombre, 1)
            fila.addWidget(quitar)
            self.caja_adj.addWidget(marco)
        self.zona_adj.setVisible(bool(self._adjuntos))

    def quitar_adjunto(self, ruta: str):
        if ruta in self._adjuntos:
            self._adjuntos.remove(ruta)
        self._repintar_adjuntos()

    def enviar(self):
        texto = self.entrada.text().strip()
        adj = list(self._adjuntos)
        if not texto and not adj:
            return
        if not texto:                                   # solo adjuntó algo: una orden por defecto
            texto = "Describe y analiza esta imagen." if all(_es_imagen(a) for a in adj) else "Léelo y dime de qué trata."
        nota = ("Archivo adjunto: " + "; ".join(f'"{a}"' for a in adj) + ". ") if adj else ""
        self._agregar("tu", texto, "", adj)
        self.entrada.recordar(texto)
        self.entrada.clear()
        self._adjuntos.clear()
        self._repintar_adjuntos()
        self.puente.texto_escrito.emit(nota + texto, self.leer.isChecked())

    def _estado(self, estado: str):
        self._estado_actual = estado
        self.estado_txt.setText(TEXTO_ESTADO.get(estado, ""))
        self.estado_txt.setStyleSheet(f"color: {PALETAS[self.tema]['pensando']};" if estado == "pensando" else "")

    def _nombre(self, nombre: str):
        self.nombre = nombre
        self.titulo.setText(nombre)
        self.setWindowTitle(f"Chat con {nombre}")

    def mostrar(self):
        """Despliega el chat y esconde el botón flotante."""
        if not self.isVisible():
            if self.boton_flotante.isVisible():          # se abre junto al botón, sin salirse de la pantalla
                b = self.boton_flotante.frameGeometry()
                pantalla = (QApplication.screenAt(b.center()) or QApplication.primaryScreen()).availableGeometry()
                x = b.left() - self.width() - 8 if b.center().x() > pantalla.center().x() else b.right() + 8
                y = b.bottom() - self.height() if b.center().y() > pantalla.center().y() else b.top()
                self.move(min(max(x, pantalla.left()), pantalla.right() - self.width() + 1),
                          min(max(y, pantalla.top()), pantalla.bottom() - self.height() + 1))
            else:
                g = self.avatar.frameGeometry()
                if getattr(self.avatar, "banner", False):    # el chat se abre a la derecha del banner
                    self.move(g.right() + 12, max(0, g.top()))
                else:
                    self.move(max(0, g.left() - self.width() - 12), max(0, g.bottom() - self.height()))
        self.boton_flotante.hide()
        self.show()
        self.raise_()
        self.activateWindow()
        self.entrada.setFocus()

    def retraer(self, *_):
        """Esconde la ventana de prompt y deja un botón redondo, movible por toda la pantalla."""
        preferida = None
        if self.isVisible():                             # el botón aparece donde estaba la esquina del chat
            g = self.frameGeometry()
            preferida = QPoint(g.right() - self.boton_flotante.width(), g.top())
        self.hide()
        if not ajustes.boton_chat_pos() and preferida is not None:
            self.boton_flotante.colocar(preferida)
        else:
            self.boton_flotante.colocar()
        self.boton_flotante.show()
        self.boton_flotante.raise_()

    def closeEvent(self, e):
        if e.spontaneous():                              # la X de la ventana: en vez de cerrar, se retrae a botón
            e.ignore()
            self.retraer()
        else:
            super().closeEvent(e)


class Avatar(QWidget):
    def __init__(self, puente: Puente):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.puente = puente
        self.setWindowTitle("jarvis-avatar")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)

        self.banner = ajustes.modo_banner()          # banner pegado al borde izquierdo (o círculo flotante)
        self.retraido = ajustes.banner_retraido()
        self._anim = None
        self._insignia_flecha = QRectF()
        self._aplicar_modo()

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
        self._insignia_ocultar = QRectF()
        self._arrastre = None
        self._movido = False
        self.bandeja = None
        self._crear_bandeja()

        self.reloj = QTimer(self, timeout=self._animar)
        self.reloj.start(33)

        puente.estado.connect(self.set_estado)
        puente.mensaje.connect(self.mostrar_mensaje)
        puente.nombre.connect(self.set_nombre)
        puente.abrir_chat.connect(self.chat.mostrar)
        puente.voz_modo.connect(self.set_voz)
        self._activar_animacion()

        self._colocar()
        if self.bandeja is not None and ajustes.avatar_oculto():
            self.bandeja.show()               # arrancó escondido: solo el icono de la bandeja
        else:
            self.show()
        self.chat.retraer()                   # al arrancar, la ventana de prompt ya está retraída como botón movible

    # ---------------------------------------------------------- bandeja del sistema (solo versión de PC)
    def _icono_bandeja(self) -> QIcon:
        """El avatar recortado en círculo, para el icono junto al reloj / wifi / batería."""
        lado = 128
        pm = QPixmap(lado, lado)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        camino = QPainterPath()
        camino.addEllipse(QRectF(4, 4, lado - 8, lado - 8))
        p.setClipPath(camino)
        img = self.foto
        p.drawPixmap(QRectF(4, 4, lado - 8, lado - 8), img, QRectF(img.rect()))
        p.setClipping(False)
        p.setPen(QPen(COLORES["reposo"], 6)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(5, 5, lado - 10, lado - 10))
        p.end()
        return QIcon(pm)

    def _crear_bandeja(self):
        """Icono en la bandeja del sistema. Si el sistema no tiene bandeja, no se ofrece esconder (para no perderla)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.bandeja = QSystemTrayIcon(self._icono_bandeja(), self)
        self.bandeja.setToolTip(self.nombre)
        menu = QMenu()
        self._accion_alternar = menu.addAction("", self.alternar_visibilidad)
        menu.addAction("💬  Escribir…", self._abrir_chat_desde_bandeja)
        menu.addAction("🎙️  Hablar ahora", self._hablar_ahora)
        menu.addSeparator()
        menu.addAction("Salir", self.puente.salir.emit)
        menu.aboutToShow.connect(self._texto_accion_alternar)
        self._menu_bandeja = menu                      # Qt no lo conserva solo
        self.bandeja.setContextMenu(menu)
        self.bandeja.activated.connect(self._clic_bandeja)
        QApplication.instance().aboutToQuit.connect(self.bandeja.hide)   # que no quede un icono fantasma al salir
        self._texto_accion_alternar()

    def _texto_accion_alternar(self):
        self._accion_alternar.setText("👁  Mostrar avatar" if not self.isVisible() else "🫥  Esconder avatar")

    def _clic_bandeja(self, motivo):
        if motivo in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):    # clic izquierdo: mostrar / esconder
            self.alternar_visibilidad()

    def _abrir_chat_desde_bandeja(self):
        self.puente.abrir_chat.emit()

    def alternar_visibilidad(self):
        if self.isVisible():
            self.esconder()
        else:
            self.mostrar_avatar()

    def esconder(self):
        """Quita el avatar del escritorio; queda el icono en la bandeja (el asistente sigue funcionando)."""
        if self.bandeja is None:
            return
        self.burbuja.hide()
        self.bandeja.show()
        self.hide()
        ajustes.guardar_avatar_oculto(True)
        self._texto_accion_alternar()
        if not getattr(self, "_aviso_bandeja", False):             # solo la primera vez, para que sepa dónde quedó
            self._aviso_bandeja = True
            self.bandeja.showMessage(self.nombre, "Sigo aquí, en la bandeja del sistema. Clic en mi icono para mostrarme.",
                                     QSystemTrayIcon.Information, 4000)

    def mostrar_avatar(self):
        if self.banner and self.retraido:            # al mostrarlo desde la bandeja sale desplegado
            self.retraido = False
            ajustes.guardar_banner_retraido(False)
        self._colocar()
        self.show()
        self.raise_()
        ajustes.guardar_avatar_oculto(False)
        self._texto_accion_alternar()

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
        return pm.scaled(config.AVATAR_TAMANO * 2, config.AVATAR_TAMANO * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)

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

    # ---------------------------------------------------------- modo banner (borde izquierdo) / flotante
    def _aplicar_modo(self):
        if self.banner:
            self.d, self.margen, self.alto_nombre, self.asa = 64, 8, 0, 20     # asa = franja de la flecha
            self.k = 0.62                                                      # escala de las insignias
            self.setToolTip(ajustes.obtener_nombre())
        else:
            self.d, self.margen, self.alto_nombre, self.asa = config.AVATAR_TAMANO, 22, 24, 0
            self.k = 1.0
            self.setToolTip("")
        self.resize(self.d + 2 * self.margen + self.asa, self.d + 2 * self.margen + self.alto_nombre)

    def _pantalla(self):
        return (self.screen() or QApplication.primaryScreen()).availableGeometry()

    def _colocar(self, animar: bool = False):
        """Banner: pegado al borde izquierdo (retraído = solo asoma la flecha); solo se mueve en vertical. Flotante: libre."""
        if not self.banner:
            self._posicionar()
            return
        g = self._pantalla()
        y = ajustes.banner_y()
        if y is None:
            y = g.top() + (g.height() - self.height()) // 2
        y = min(max(y, g.top()), g.bottom() - self.height())
        x = g.left() - ((self.width() - self.asa) if self.retraido else 0)
        destino = QPoint(x, y)
        if animar and self.isVisible():
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.setStartValue(self.pos())
            anim.setEndValue(destino)
            anim.start()
            self._anim = anim
        else:
            self.move(destino)

    def alternar_retraido(self):
        """Flecha del banner: lo esconde contra el borde (queda solo la flecha) o lo vuelve a sacar."""
        if not self.banner:
            return
        self.retraido = not self.retraido
        ajustes.guardar_banner_retraido(self.retraido)
        self.burbuja.hide()
        self._colocar(animar=True)
        self.update()

    def alternar_modo(self):
        """Cambia entre banner en el borde y círculo flotante (menú clic derecho)."""
        self.banner = not self.banner
        ajustes.guardar_modo_banner(self.banner)
        self.retraido = False
        ajustes.guardar_banner_retraido(False)
        self.burbuja.hide()
        self._aplicar_modo()
        self._colocar()
        self.update()

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
        if self.bandeja is not None:
            self.bandeja.setToolTip(nombre)
        if self.banner:
            self.setToolTip(nombre)
        self.update()

    def mostrar_mensaje(self, quien: str, texto: str):
        texto = (texto or "").strip()
        if not texto or self.chat.isVisible() or not self.isVisible() or (self.banner and self.retraido):
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
        cx, cy = ((self.margen + self.d / 2) if self.banner else self.width() / 2), self.margen + self.d / 2
        r = self.d / 2
        color = COLORES[self.estado]
        k = self.k
        if self.banner:
            # fondo del banner: pegado al borde izquierdo (esquinas izquierdas fuera de pantalla), redondeado a la derecha
            p.setPen(QPen(color, 1.5)); p.setBrush(QColor(10, 16, 32, 235))
            p.drawRoundedRect(QRectF(-14, 0.75, self.width() + 13.25, self.height() - 1.5), 14, 14)

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

        # halo de luz (en el banner no: es compacto)
        if not self.banner:
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

        # nombre (solo en el modo flotante)
        if not self.banner:
            p.setFont(QFont("Sans", 9, QFont.DemiBold))
            texto = self.nombre
            ancho = p.fontMetrics().horizontalAdvance(texto) + 18
            pill = QRectF(cx - ancho / 2, self.margen + self.d + 4, ancho, 18)
            fondo = QColor(10, 16, 32, 215)
            p.setPen(Qt.NoPen); p.setBrush(fondo)
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor("#eaf6ff"))
            p.drawText(pill, Qt.AlignCenter, texto)

        # insignia 💬: abre el chat de texto (se dibuja centrada en el origen y escalada por k)
        bx, by = cx + r * 0.74, cy + r * 0.74
        self._insignia = QRectF(bx - 14 * k, by - 14 * k, 28 * k, 28 * k)
        p.save(); p.translate(bx, by); p.scale(k, k)
        p.setBrush(QColor(10, 16, 32, 240)); p.setPen(QPen(color, 2))
        p.drawEllipse(QRectF(-14, -14, 28, 28))
        p.setPen(Qt.NoPen); p.setBrush(QColor("#eaf6ff"))
        p.drawRoundedRect(QRectF(-8, -7, 16, 11), 3, 3)
        p.drawPolygon(QPolygonF([QPointF(-4, 3), QPointF(-7, 8), QPointF(2, 3)]))
        p.setBrush(color)
        for dx in (-4, 0, 4):
            p.drawEllipse(QPointF(dx, -1.5), 1.2, 1.2)
        p.restore()

        # insignia 🎙️: interruptor de voz (verde = te escucha · roja tachada = solo escritura)
        mx, my = cx - r * 0.74, cy + r * 0.74
        self._insignia_voz = QRectF(mx - 14 * k, my - 14 * k, 28 * k, 28 * k)
        tinta = QColor("#4ade80") if self.voz else QColor("#ff6b81")
        p.save(); p.translate(mx, my); p.scale(k, k)
        p.setBrush(QColor(10, 16, 32, 240)); p.setPen(QPen(tinta, 2))
        p.drawEllipse(QRectF(-14, -14, 28, 28))
        p.setPen(Qt.NoPen); p.setBrush(QColor("#eaf6ff"))
        p.drawRoundedRect(QRectF(-3, -9, 6, 11), 3, 3)                   # cuerpo del micrófono
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor("#eaf6ff"), 1.6))
        p.drawArc(QRectF(-6, -6, 12, 11), 180 * 16, 180 * 16)             # soporte
        p.drawLine(QPointF(0, 5), QPointF(0, 8))
        p.drawLine(QPointF(-3, 8), QPointF(3, 8))
        if not self.voz:
            p.setPen(QPen(tinta, 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(-8, -8), QPointF(8, 8))
        p.restore()

        # insignia «–»: esconder el avatar a la bandeja del sistema (solo si el sistema tiene bandeja)
        if self.bandeja is not None:
            hx, hy = cx + r * 0.74, cy - r * 0.74
            self._insignia_ocultar = QRectF(hx - 11 * k, hy - 11 * k, 22 * k, 22 * k)
            p.save(); p.translate(hx, hy); p.scale(k, k)
            p.setBrush(QColor(10, 16, 32, 240)); p.setPen(QPen(color, 2))
            p.drawEllipse(QRectF(-11, -11, 22, 22))
            p.setPen(QPen(QColor("#eaf6ff"), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(-5, 0), QPointF(5, 0))
            p.restore()

        # flecha del banner: ◀ retrae contra el borde · ▶ lo vuelve a sacar
        if self.banner:
            self._insignia_flecha = QRectF(self.width() - self.asa, 0, self.asa, self.height())
            ax, ay = self._insignia_flecha.center().x(), self._insignia_flecha.center().y()
            if not self.retraido:
                p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 90), 1))
                p.drawLine(QPointF(self._insignia_flecha.left(), 10), QPointF(self._insignia_flecha.left(), self.height() - 10))
            sentido = 1 if self.retraido else -1                  # ▶ si está retraído, ◀ si está desplegado
            p.setPen(QPen(color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(ax - 3 * sentido, ay - 7), QPointF(ax + 3 * sentido, ay),
                                      QPointF(ax - 3 * sentido, ay + 7)]))
        else:
            self._insignia_flecha = QRectF()

    # ---------------------------------------------------------------- ratón
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._arrastre = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._movido = False

    def mouseMoveEvent(self, e):
        if self._arrastre is not None and e.buttons() & Qt.LeftButton:
            destino = e.globalPosition().toPoint() - self._arrastre
            if self.banner:                            # el banner solo se desliza en vertical por el borde
                g = self._pantalla()
                destino = QPoint(self.x(), min(max(destino.y(), g.top()), g.bottom() - self.height()))
            if (destino - self.frameGeometry().topLeft()).manhattanLength() > 3:
                self._movido = True
            self.move(destino)
            if self.burbuja.isVisible():
                self.burbuja.hide()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._arrastre is not None:
            if self._movido:
                if self.banner:
                    ajustes.guardar_banner_y(self.y())
                else:
                    ajustes.guardar_posicion(self.x(), self.y())
            elif self.banner and self._insignia_flecha.contains(e.position()):
                self.alternar_retraido()
            elif self.bandeja is not None and self._insignia_ocultar.contains(e.position()):
                self.esconder()
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
        menu.addAction("🪟  Modo flotante (círculo libre)" if self.banner else "📌  Modo banner (borde izquierdo)",
                       self.alternar_modo)
        if self.bandeja is not None:
            menu.addAction("🫥  Esconder en la bandeja del sistema", self.esconder)
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
