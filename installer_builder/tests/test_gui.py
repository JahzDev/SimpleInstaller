import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
except ModuleNotFoundError:
    QApplication = None
else:
    from src.gui.main_window import MainWindow

from src.config.installer_schema import InstallerError
from src.installer.package import PackageBuilder


@unittest.skipIf(QApplication is None, "PySide6 is not installed.")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        project = self.root / "project"
        (project / "src/Demo").mkdir(parents=True)
        (project / "src/Demo/file.txt").write_text("payload")
        (project / "templates").mkdir()
        (project / "templates/player.ini.template").write_text("name={{PLAYER_NAME}}")
        config = {
            "name": "Demo", "version": "1", "publisher": "Example",
            "default_install_path": str(self.root / "installed"),
            "desktop_shortcut": False,
            "required_parameters": [{"name": "PLAYER_NAME", "description": "Spielername"}],
        }
        (project / "installer.json").write_text(json.dumps(config))
        package = PackageBuilder().build(project, self.root / "packages")
        self.window = MainWindow(package)
        self.window.show()
        self.addCleanup(self.window.close)

    def wait_for_worker(self):
        deadline = time.monotonic() + 10
        while self.window._thread is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(self.window._thread, "Installation thread did not finish.")
        self.app.processEvents()

    def test_gui_installs_and_displays_success(self):
        self.assertTrue(self.window.install_button.isEnabled())
        self.assertIn("Demo", self.window.info.text())
        self.window.parameters.inputs["PLAYER_NAME"].setText("Alice")
        with patch("src.gui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.install_button.click()
            self.assertEqual(self.window.pages.currentIndex(), 1)
            self.assertFalse(self.window.install_button.isEnabled())
            self.wait_for_worker()
        self.assertEqual(self.window.pages.currentIndex(), 2)
        self.assertEqual(self.window.progress_bar.value(), 100)
        self.assertIn("2 Dateien installiert", self.window.result_label.text())
        self.assertEqual((self.root / "installed/player.ini").read_text(), "name=Alice")
        self.assertEqual((self.root / "installed/file.txt").read_text(), "payload")
        self.assertTrue(self.window.another_button.isEnabled())

    def test_worker_failure_shows_error_and_allows_retry(self):
        self.window.parameters.inputs["PLAYER_NAME"].setText("Alice")
        with patch("src.gui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            with patch("src.gui.main_window.InstallerEngine.install", side_effect=InstallerError("Testfehler")):
                with self.assertLogs("src.gui.main_window", level="ERROR"):
                    self.window.start_installation()
                    self.wait_for_worker()
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertIn("Testfehler", self.window.error_label.text())
        self.assertTrue(self.window.back_button.isEnabled())
        self.window.back_button.click()
        self.assertEqual(self.window.pages.currentIndex(), 0)
        self.assertTrue(self.window.install_button.isEnabled())

    def test_missing_parameter_is_rejected_without_starting_worker(self):
        with patch("src.gui.main_window.QMessageBox.warning") as warning:
            self.window.start_installation()
        warning.assert_called_once()
        self.assertIsNone(self.window._thread)
        self.assertFalse((self.root / "installed").exists())

    def test_invalid_package_shows_actionable_error(self):
        previous = self.window.package
        with patch("src.gui.main_window.QMessageBox.critical") as critical:
            self.window.load_package(self.root / "missing.installer")
        critical.assert_called_once()
        self.assertIs(self.window.package, previous)


if __name__ == "__main__":
    unittest.main()
