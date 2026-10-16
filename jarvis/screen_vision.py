"""Detecção de perguntas sobre a tela e captura em memória, sob demanda."""
import base64
import re
import unicodedata


def is_screen_question(text):
    value = unicodedata.normalize("NFD", str(text).casefold())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = re.sub(r"\s+", " ", value).strip(" ?.!,")
    patterns = (
        r"^(?:o que (?:esta acontecendo|tem|aparece) (?:aqui|na tela)|"
        r"o que eu estou vendo|o que estou vendo|"
        r"(?:analise|descreva|leia) (?:a )?(?:minha )?tela|"
        r"veja (?:a )?tela|interprete (?:essa|esta) tela)$",
    )
    return any(re.match(pattern, value) for pattern in patterns)


def capture_primary_screen_data_url(max_dimension=1600, quality=75):
    """Captura o monitor principal e retorna JPEG base64, sem criar arquivos."""
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
    from PySide6.QtWidgets import QApplication

    screen = QApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("Não encontrei uma tela para capturar.")
    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        raise RuntimeError("A captura da tela ficou vazia.")
    if max(pixmap.width(), pixmap.height()) > max_dimension:
        pixmap = pixmap.scaled(
            max_dimension, max_dimension,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    image_bytes = QByteArray()
    buffer = QBuffer(image_bytes)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("Não consegui preparar a imagem para análise.")
    try:
        if not pixmap.save(buffer, "JPEG", quality):
            raise RuntimeError("Não consegui codificar a captura da tela.")
    finally:
        buffer.close()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise RuntimeError("A captura ficou grande demais para enviar com segurança.")
    encoded = base64.b64encode(bytes(image_bytes)).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
