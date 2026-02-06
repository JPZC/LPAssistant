import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from lpassistant.app import AssistantController


class StatusBadge(QtWidgets.QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StatusBadge")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        self.label = QtWidgets.QLabel("Inicializando")
        self.label.setObjectName("StatusLabel")
        layout.addWidget(self.label)

    def set_status(self, text: str) -> None:
        self.label.setText(text)
        self.setProperty("mode", text)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, model_path: str) -> None:
        super().__init__()
        self.setWindowTitle("LP Assistant")
        self.setMinimumSize(960, 640)
        self.controller = AssistantController(model_path)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        header = QtWidgets.QFrame()
        header.setObjectName("HeaderCard")
        header_layout = QtWidgets.QVBoxLayout(header)
        header_layout.setContentsMargins(24, 24, 24, 24)
        self.title = QtWidgets.QLabel("LP Assistant")
        self.title.setObjectName("Title")
        self.subtitle = QtWidgets.QLabel(
            "Dicta con \"Escuchar\", usa \"Escuchar libremente\" para dictado sin comandos, "
            "activa comandos con \"Escuchar comandos\" y detén con \"Detener\"."
        )
        self.subtitle.setObjectName("Subtitle")
        header_layout.addWidget(self.title)
        header_layout.addWidget(self.subtitle)

        self.status_badge = StatusBadge()

        controls = QtWidgets.QFrame()
        controls.setObjectName("ControlsCard")
        controls_layout = QtWidgets.QVBoxLayout(controls)
        controls_layout.setContentsMargins(20, 20, 20, 20)
        controls_layout.setSpacing(12)

        toolbox = QtWidgets.QToolBox()
        toolbox.setObjectName("CommandSections")
        toolbox.setStyleSheet("""
            QToolBox::tab {
                padding-top: 60px;
                padding-bottom: 60px;
                min-height: 60px; 
            }
        """)
        controls_layout.addWidget(toolbox)

        def add_section(title: str, items: list[tuple[str, str]]) -> None:
            page = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(page)
            grid.setContentsMargins(16, 16, 16, 16)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(10)
            for row, (command, description) in enumerate(items):
                cmd_label = QtWidgets.QLabel(command)
                cmd_label.setObjectName("CommandLabel")
                desc_label = QtWidgets.QLabel(description)
                desc_label.setObjectName("CommandDesc")
                desc_label.setWordWrap(True)
                grid.addWidget(cmd_label, row, 0)
                grid.addWidget(desc_label, row, 1)
            toolbox.addItem(page, title)

        add_section(
            "Modos de escucha",
            [
                ("Escuchar", "Inicia la transcripción global con puntuación por voz."),
                ("Escuchar libremente", "Dictado sin comandos ni puntuación por voz."),
                ("Escuchar comandos", "Escucha comandos sin transcribir."),
                ("Detener", "Detiene la transcripción."),
            ],
        )
        add_section(
            "Edición rápida",
            [
                ("Mejorar texto", "Corrige ortografía y puntuación."),
                ("Seleccionar todo", "Envía CTRL + A."),
                ("Copiar", "Envía CTRL + C."),
                ("Pegar", "Envía CTRL + V."),
                ("Deshacer / Rehacer", "Envía CTRL + Z / CTRL + Y."),
                ("Guardar", "Envía CTRL + S."),
                ("Cerrar pestaña / ventana", "Envía CTRL + W / ALT + F4."),
                ("Salto de línea", "Inserta una nueva línea (Enter)."),
                ("Borrar última palabra", "Envía CTRL + Backspace."),
            ],
        )
        add_section(
            "Navegación",
            [
                ("Mover cursor (izq/der/arriba/abajo)", "Usa flechas del teclado."),
                ("Mover cursor palabra (izq/der)", "Envía CTRL + flecha."),
                ("Inicio/Fin de línea", "Usa teclas Home y End."),
                ("Página arriba / abajo", "Usa Page Up / Page Down."),
                ("Mover teclado (atrás)", "Usa Tab / Shift + Tab."),
            ],
        )
        add_section(
            "Ratón",
            [
                ("Clic / Click", "Click izquierdo sobre la posición actual del cursor."),
                ("Clic derecho / Click derecho", "Abre el menú contextual."),
                ("Doble clic / Doble click", "Ejecuta doble click izquierdo."),
                ("Clic pulsado / Click pulsado", "Mantiene el click por unos instantes."),
            ],
        )
        add_section(
            "Puntuación en dictado",
            [
                ("Puntuación", "Punto, coma, dos puntos, signos y más en dictado."),
                ("Frases comunes", "Di \"punto\", \"coma\", \"dos puntos\" o \"puntos suspensivos\"."),
            ],
        )

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("LogPanel")

        layout.addWidget(header)
        layout.addWidget(self.status_badge)
        layout.addWidget(controls)
        layout.addWidget(self.log, stretch=1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll_updates)

        self.controller.start()
        self._timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.controller.stop()
        event.accept()

    def _poll_updates(self) -> None:
        status = self.controller.poll_status()
        if status:
            self.status_badge.set_status(status)
        while True:
            message = self.controller.poll_log()
            if message is None:
                break
            self.log.append(message)


def load_styles(app: QtWidgets.QApplication) -> None:
    qss_path = Path(__file__).with_name("styles.qss")
    app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("LP Assistant")
    load_styles(app)
    model_path = str(Path(__file__).with_name("models") / "vosk-model-small-es-0.42")
    window = MainWindow(model_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
