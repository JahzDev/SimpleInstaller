"""Three-page installer interface; the engine never accesses Qt widgets."""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config.installer_schema import InstallerError
from ..installer.engine import InstallationResult, InstallerEngine
from ..installer.package import InstallerPackage
from .widgets import ParameterForm

LOGGER = logging.getLogger(__name__)


def text_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class InstallationWorker(QObject):
    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, package: InstallerPackage, path: Path, parameters: dict[str, str]):
        super().__init__()
        self.package, self.path, self.parameters = package, path, parameters

    @Slot()
    def run(self):
        try:
            result = InstallerEngine().install(
                self.package, self.path, self.parameters, self.progress.emit)
        except Exception as exc:
            LOGGER.exception("Installation fehlgeschlagen")
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, package_path: Path | None = None):
        super().__init__()
        self.setWindowTitle("Simple Windows Installer")
        self.resize(640, 460)
        self.package: InstallerPackage | None = None
        self._thread: QThread | None = None
        self._worker: InstallationWorker | None = None
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self._create_start_page()
        self._create_install_page()
        self._create_completion_page()
        if package_path is not None:
            self.load_package(package_path)

    def _create_start_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.package_label = text_label("Bitte ein Installationspaket auswählen.")
        layout.addWidget(self.package_label)
        choose = QPushButton("Paket auswählen …")
        choose.clicked.connect(self.choose_package)
        layout.addWidget(choose)
        self.info = text_label()
        layout.addWidget(self.info)
        layout.addWidget(text_label("Installationsordner"))
        row = QHBoxLayout()
        self.install_path = QLineEdit()
        row.addWidget(self.install_path)
        browse = QPushButton("Durchsuchen …")
        browse.clicked.connect(self.choose_install_path)
        row.addWidget(browse)
        layout.addLayout(row)
        self.parameters = ParameterForm()
        layout.addWidget(self.parameters)
        layout.addStretch()
        self.install_button = QPushButton("Installieren")
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self.start_installation)
        layout.addWidget(self.install_button)
        self.pages.addWidget(page)

    def _create_install_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(text_label("Installation"))
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        self.current_operation = text_label()
        layout.addWidget(self.current_operation)
        self.error_label = text_label()
        layout.addWidget(self.error_label)
        layout.addStretch()
        self.back_button = QPushButton("Zurück")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        layout.addWidget(self.back_button)
        self.pages.addWidget(page)

    def _create_completion_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(text_label("Installation erfolgreich abgeschlossen."))
        self.result_label = text_label()
        layout.addWidget(self.result_label)
        layout.addStretch()
        self.another_button = QPushButton("Weiteres Paket installieren")
        self.another_button.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        layout.addWidget(self.another_button)
        close = QPushButton("Schließen")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.pages.addWidget(page)

    @Slot()
    def choose_package(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Installationspaket auswählen", "", "Installer-Pakete (*.installer)")
        if filename:
            self.load_package(Path(filename))

    def load_package(self, path: Path):
        if self._thread is not None:
            return
        try:
            package = InstallerPackage(path)
        except InstallerError as exc:
            QMessageBox.critical(self, "Paketfehler", str(exc))
            return
        self.package = package
        config = package.config
        self.package_label.setText(str(package.path))
        self.info.setText(f"{config.name}\nVersion: {config.version}\nHerausgeber: {config.publisher}")
        self.install_path.setText(config.default_install_path)
        self.parameters.set_parameters(config.required_parameters)
        self.install_button.setEnabled(True)
        self.pages.setCurrentIndex(0)

    @Slot()
    def choose_install_path(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Installationsordner auswählen", self.install_path.text())
        if directory:
            self.install_path.setText(directory)

    @Slot()
    def start_installation(self):
        if self.package is None or self._thread is not None:
            return
        path = Path(self.install_path.text().strip())
        if not path.is_absolute():
            QMessageBox.warning(self, "Eingabe prüfen", "Bitte einen absoluten Installationspfad angeben.")
            return
        values = self.parameters.values()
        for parameter in self.package.config.required_parameters:
            if not values[parameter.name].strip():
                QMessageBox.warning(self, "Eingabe prüfen", f"Bitte '{parameter.description}' angeben.")
                return
        answer = QMessageBox.question(
            self, "Installation bestätigen",
            f"Nur vertrauenswürdige Pakete installieren.\nZiel: {path}\n"
            "Vorhandene Dateien werden überschrieben, auch im Benutzerprofil.\nFortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.install_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.another_button.setEnabled(False)
        self.error_label.clear()
        self.progress_bar.setValue(0)
        self.current_operation.setText("Installation vorbereiten …")
        self.pages.setCurrentIndex(1)
        self._thread = QThread(self)
        self._worker = InstallationWorker(self.package, path, values)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.succeeded.connect(self._completed)
        self._worker.failed.connect(self._failed)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._cleanup)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(int, str)
    def _update_progress(self, value: int, message: str):
        self.progress_bar.setValue(value)
        self.current_operation.setText(message)

    @Slot(object)
    def _completed(self, result: InstallationResult):
        links = "\n".join(str(path) for path in result.shortcuts) or "Keine Desktop-Verknüpfungen angefordert."
        self.result_label.setText(f"{len(result.files)} Dateien installiert.\nVerknüpfungen:\n{links}")
        self.pages.setCurrentIndex(2)

    @Slot(str)
    def _failed(self, message: str):
        self.current_operation.setText("Installation fehlgeschlagen.")
        self.error_label.setText(message + "\nBereits kopierte Dateien werden nicht zurückgesetzt.")

    @Slot()
    def _cleanup(self):
        # finished is emitted before all thread-local cleanup has completed.
        self._thread.wait()
        self._thread = None
        self._worker = None
        self.install_button.setEnabled(self.package is not None)
        self.back_button.setEnabled(True)
        self.another_button.setEnabled(True)

    def closeEvent(self, event):
        if self._thread is not None:
            QMessageBox.information(self, "Installation läuft", "Bitte warten, bis die Installation beendet ist.")
            event.ignore()
        else:
            event.accept()
