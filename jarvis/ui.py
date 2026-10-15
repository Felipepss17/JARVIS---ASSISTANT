"""Janelas e widgets do aplicativo."""
import collections
import html
import math

from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QTextCursor, QTextCharFormat, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTextEdit, QLineEdit, QPushButton,
    QHBoxLayout, QLabel,
)

from .audio import tocar_som
from .settings import *  # noqa: F403

class ChatWindow(QWidget):
    message_submitted = Signal(str)
    decided = Signal(bool)
    closed = Signal()

    PLACEHOLDER = "Escreva uma ordem ou mensagem ao JARVIS..."
    PLACEHOLDER_ESCREVENDO = "JARVIS está respondendo..."

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S. // Terminal de Comunicação")
        self.resize(680, 760)
        self.setStyleSheet("""
            QWidget { background-color: #050b14; color: #2accff; font-family: 'Consolas'; }
            QTextEdit {
                background-color: #081220; border: 1px solid #1a5276; border-radius: 8px;
                padding: 15px; color: #9af2ff; font-size: 15px;
            }
            QLineEdit {
                background-color: #081220; border: 1px solid #2accff; border-radius: 6px;
                padding: 10px; color: #ffffff; font-size: 15px;
            }
            QLineEdit:disabled { border-color: #1a5276; color: #4b7387; }
            QPushButton {
                background-color: #0b2545; border: 1px solid #2accff; border-radius: 6px;
                color: #2accff; font-weight: bold; padding: 10px 20px; font-size: 15px;
            }
            QPushButton:hover { background-color: #133a6f; color: #ffffff; }
            QPushButton:disabled { border-color: #1a5276; color: #4b7387; }
            QPushButton#yes { border-color: #3ddc84; color: #3ddc84; }
            QPushButton#no { border-color: #ff5c5c; color: #ff5c5c; }
        """)

        layout = QVBoxLayout()
        header_label = QLabel("--- MODO AGENTE: ferramentas ativas, ações sensíveis pedem autorização ---")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header_label)

        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        layout.addWidget(self.chat_history)

        self.confirm_bar = QWidget()
        bar = QHBoxLayout(self.confirm_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.btn_yes = QPushButton("Autorizar")
        self.btn_yes.setObjectName("yes")
        self.btn_no = QPushButton("Negar")
        self.btn_no.setObjectName("no")
        self.btn_yes.clicked.connect(lambda: self.decided.emit(True))
        self.btn_no.clicked.connect(lambda: self.decided.emit(False))
        bar.addWidget(self.btn_yes)
        bar.addWidget(self.btn_no)
        self.confirm_bar.hide()
        layout.addWidget(self.confirm_bar)

        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(self.PLACEHOLDER)
        self.input_field.returnPressed.connect(self.send_message)
        self.send_button = QPushButton("Enviar")
        self.send_button.clicked.connect(self.send_message)
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        layout.addLayout(input_layout)

        self.setLayout(layout)

        self._fila = collections.deque()
        self._digit = None
        self._instantaneo = False
        self._timer = QTimer(self)
        self._timer.setInterval(DIGITACAO_INTERVALO_MS)
        self._timer.timeout.connect(self._passo_digitacao)

        self.append_message("JARVIS", "Terminal aberto, senhor. Posso ler o projeto, criar arquivos "
                                      "na pasta jarvis_workspace e criar plugins. Ações sensíveis "
                                      "pedirão a sua autorização.")

    def send_message(self):
        if not self.input_field.isEnabled():
            return
        text = self.input_field.text().strip()
        if text:
            tocar_som("send_message.wav") # <--- Som ao enviar mensagem
            self.append_message("Felipe", text)
            self.input_field.clear()
            self.message_submitted.emit(text)

    def _travar(self, travar):
        self.input_field.setEnabled(not travar)
        self.send_button.setEnabled(not travar)
        self.input_field.setPlaceholderText(self.PLACEHOLDER_ESCREVENDO if travar else self.PLACEHOLDER)
        if not travar:
            self.input_field.setFocus()

    def append_message(self, sender, message, animar=None):
        if animar is None:
            animar = (sender == "JARVIS")
        self._fila.append(("anim" if animar else "inst", sender, str(message)))
        self._processar_fila()

    def _processar_fila(self):
        if self._digit is not None:
            return
        while self._fila:
            tipo, sender, msg = self._fila.popleft()
            if tipo == "barra":
                self._mostrar_barra()
            elif tipo == "anim" and not self._instantaneo:
                self._iniciar_digitacao(sender, msg)
                self._travar(True)
                return
            else:
                self._inserir_instantaneo(sender, msg)
        self._travar(False)

    def _inserir_instantaneo(self, sender, message):
        color = "#ffffff" if sender.startswith("Felipe") else "#2accff"
        corpo = html.escape(message).replace("\n", "<br>").replace("  ", "&nbsp;&nbsp;")
        self.chat_history.append(
            f"<div style='margin-bottom: 12px;'><b style='color:{color};'>{html.escape(sender)}:</b>"
            f"<br>{corpo}</div>")

    def _iniciar_digitacao(self, sender, message):
        self.chat_history.append(f"<b style='color:#2accff;'>{html.escape(sender)}:</b>")
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        self.chat_history.setTextCursor(cursor)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#9af2ff"))
        cps = max(DIGITACAO_CPS, len(message) / DIGITACAO_MAX_SEG)
        passo = max(1, round(cps * DIGITACAO_INTERVALO_MS / 1000))
        self._digit = {"texto": message, "pos": 0, "passo": passo, "fmt": fmt}
        self._timer.start()

    def _escrever(self, trecho):
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(trecho, self._digit["fmt"])
        self.chat_history.setTextCursor(cursor)
        self.chat_history.ensureCursorVisible()

    def _passo_digitacao(self):
        d = self._digit
        if d is None:
            self._timer.stop()
            return
        trecho = d["texto"][d["pos"]:d["pos"] + d["passo"]]
        d["pos"] += d["passo"]
        if trecho:
            tocar_som("typing_click.wav") # <--- Som enquanto ele digita (a cada passo)
            self._escrever(trecho)
        if d["pos"] >= len(d["texto"]):
            self._finalizar_digitacao()

    def _finalizar_digitacao(self):
        self._timer.stop()
        self._digit = None
        self.chat_history.append("")
        self._processar_fila()

    def pular_digitacao(self):
        self._instantaneo = True
        try:
            d = self._digit
            if d is not None:
                resto = d["texto"][d["pos"]:]
                if resto:
                    self._escrever(resto)
                self._timer.stop()
                self._digit = None
                self.chat_history.append("")
            self._processar_fila()
        finally:
            self._instantaneo = False

    def ask_confirmation(self, descricao):
        self.append_message("⚠ AUTORIZAÇÃO NECESSÁRIA", descricao +
                            "\n\nClique em Autorizar ou Negar (ou digite sim / não).", animar=False)
        self._fila.append(("barra", "", ""))
        self._processar_fila()

    def _mostrar_barra(self):
        self.confirm_bar.show()
        self.raise_()
        self.activateWindow()

    def close_confirmation(self, mensagem):
        self.confirm_bar.hide()
        self._fila = collections.deque(i for i in self._fila if i[0] != "barra")
        self.append_message("JARVIS", mensagem, animar=False)

    def closeEvent(self, event):
        self._timer.stop()
        self.closed.emit()
        event.accept()


class FloatingReactor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(150, 150)

        screen = QApplication.primaryScreen().geometry()
        self.move(24, screen.height() - 174)

        self.phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(30)

        self.dragging = False
        self.offset = QPoint()

    def animate(self):
        self.phase = (self.phase + 1) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2
        outer = side * 0.475
        inner = side * 0.235
        cyan = QColor(91, 235, 255)
        blue = QColor(27, 151, 220)
        gold = QColor(255, 202, 52)

        p.setPen(Qt.PenStyle.NoPen)
        glow = QRadialGradient(cx, cy, outer * 1.08)
        glow.setColorAt(0.0, QColor(0, 174, 230, 24))
        glow.setColorAt(0.67, QColor(0, 119, 179, 13))
        glow.setColorAt(1.0, QColor(0, 60, 100, 0))
        p.setBrush(glow)
        p.drawEllipse(QPoint(int(cx), int(cy)), int(outer * 1.08), int(outer * 1.08))

        # Fundo escuro e retícula central para dar profundidade ao HUD.
        p.setBrush(QColor(3, 13, 22, 238))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(inner * 1.62), int(inner * 1.62))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(51, 183, 211, 65), 1))
        for r in (inner * 1.18, inner * 1.43, inner * 1.62):
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))
        p.save()
        p.translate(cx, cy)
        p.rotate(-self.phase * 0.22)
        p.setPen(QPen(QColor(57, 179, 202, 48), 1))
        for r in (inner * 0.72, inner * 0.91):
            p.drawEllipse(int(-r), int(-r), int(2 * r), int(2 * r))
        for angle in range(0, 360, 15):
            p.save()
            p.rotate(angle)
            p.drawLine(0, int(-inner * 0.72), 0, int(-inner * (0.72 if angle % 45 else 0.84)))
            p.restore()
        p.restore()

        # Arco azul segmentado que gira devagar, com brilho ciano nas bordas.
        p.save()
        p.translate(cx, cy)
        p.rotate(self.phase * 0.35)
        p.setBrush(Qt.BrushStyle.NoBrush)
        ring_r = side * 0.355
        p.setPen(QPen(QColor(38, 153, 209, 55), 18, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawArc(int(-ring_r), int(-ring_r), int(2 * ring_r), int(2 * ring_r), 28 * 16, 290 * 16)
        for angle in range(35, 325, 13):
            p.save()
            p.rotate(angle)
            color = QColor(48, 174, 226, 190 if angle % 26 else 235)
            p.setPen(QPen(color, 7 if angle % 26 else 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawLine(0, int(-ring_r), 0, int(-ring_r + (side * 0.043)))
            p.restore()
        p.restore()

        # Anéis externos, traços de escala e marcadores de navegação.
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r, color, width in (
            (outer, QColor(91, 235, 255, 215), 2.2),
            (side * 0.435, QColor(58, 199, 225, 110), 1),
            (side * 0.302, QColor(114, 238, 248, 205), 2),
        ):
            p.setPen(QPen(color, width))
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))
        p.save()
        p.translate(cx, cy)
        for angle in range(0, 360, 5):
            p.save()
            p.rotate(angle)
            major = angle % 15 == 0
            p.setPen(QPen(QColor(117, 230, 240, 175 if major else 72), 2 if major else 1))
            p.drawLine(0, int(-outer + 4), 0, int(-outer + (17 if major else 10)))
            p.restore()
        p.restore()

        # Pequenos segmentos que orbitam em sentido contrário.
        p.save()
        p.translate(cx, cy)
        p.rotate(-self.phase * 0.72)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for angle, sweep, color, width in (
            (8, 38, cyan, 4), (93, 22, gold, 3), (158, 31, cyan, 3),
            (218, 18, gold, 3), (278, 43, cyan, 4),
        ):
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            r = side * 0.405
            p.drawArc(int(-r), int(-r), int(2 * r), int(2 * r), angle * 16, sweep * 16)
        p.restore()

        # Pontos luminosos e linhas técnicas giram em camada própria.
        p.save()
        p.translate(cx, cy)
        p.rotate(self.phase * 1.15)
        for angle in (0, 54, 127, 203, 251, 314):
            p.save()
            p.rotate(angle)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(gold if angle in (54, 203) else cyan)
            dot_r = 3.3 if angle in (54, 203) else 2.2
            p.drawEllipse(QPoint(0, int(-side * 0.29)), int(dot_r), int(dot_r))
            p.restore()
        p.restore()

        # Núcleo com aro luminoso e identidade central.
        p.setPen(QPen(QColor(95, 233, 255, 225), 2))
        p.setBrush(QColor(4, 20, 32, 245))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(inner), int(inner))
        p.setPen(QPen(QColor(65, 190, 213, 110), 1))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(inner * 0.84), int(inner * 0.84))
        p.setPen(QColor(222, 250, 255))
        p.setFont(QFont("Consolas", max(10, int(side * 0.071)), QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")
        p.setPen(QColor(75, 204, 224, 190))
        p.setFont(QFont("Consolas", max(6, int(side * 0.026))))
        p.drawText(int(cx - inner), int(cy + inner * 0.42), int(inner * 2), 14,
                   Qt.AlignmentFlag.AlignCenter, "SISTEMA ONLINE")
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False


\n