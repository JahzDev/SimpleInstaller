import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from src.config.installer_schema import InstallerConfig, InstallerError, relative_path
from src.installer.engine import InstallerEngine
from src.installer.file_copy import safe_destination
from src.installer.package import InstallerPackage, PackageBuilder, parse_links
from src.installer.shortcuts import ShortcutCreator


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.config = {
            "name": "GameXY", "version": "1.0", "publisher": "Example",
            "default_install_path": "C:/Games/GameXY", "desktop_shortcut": False,
            "required_parameters": [{"name": "PLAYER_NAME", "description": "Spielername"}],
        }
        self.write("src/GameXY/Game.exe", "example payload")
        self.write("User/Documents/config.ini", "user config")
        self.write("User/AppData/settings.json", "{}")
        self.write("templates/config.ini.template", "username={{PLAYER_NAME}}")
        self.write("link.txt", "./src/GameXY/Game.exe;-nosteam")
        self.install = self.root / "installed"
        self.profile = self.root / "profile"
        self.profile.mkdir()

    def write(self, relative, text):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def build(self):
        self.write("installer.json", json.dumps(self.config))
        return InstallerPackage(PackageBuilder().build(self.project, self.root / "packages"))

    def test_build_and_install_files_user_profile_and_templates(self):
        package = self.build()
        self.assertEqual(package.path.name, "GameXY-1.0.installer")
        with ZipFile(package.path) as archive:
            self.assertEqual(set(archive.namelist()), {"manifest.json", "payload.zip"})
        progress = []
        with patch("src.installer.engine.user_profile", return_value=self.profile):
            result = InstallerEngine().install(package, self.install, {"PLAYER_NAME": "Alice"},
                                               lambda value, text: progress.append((value, text)))
        self.assertEqual((self.install / "Game.exe").read_text(), "example payload")
        self.assertFalse((self.install / "GameXY").exists())
        self.assertEqual((self.profile / "Documents/config.ini").read_text(), "user config")
        self.assertEqual((self.profile / "AppData/settings.json").read_text(), "{}")
        self.assertEqual((self.install / "config.ini").read_text(), "username=Alice")
        self.assertEqual(len(result.files), 4)
        self.assertEqual(result.shortcuts, [])
        self.assertEqual(progress[-1][0], 100)

    def test_multiple_src_entries_keep_directory_names(self):
        self.write("src/Other/data.txt", "other")
        package = self.build()
        self.assertEqual(package.source_root, "src")
        with patch("src.installer.engine.user_profile", return_value=self.profile):
            InstallerEngine().install(package, self.install, {"PLAYER_NAME": "Alice"})
        self.assertTrue((self.install / "GameXY/Game.exe").is_file())
        self.assertTrue((self.install / "Other/data.txt").is_file())

    def test_user_templates(self):
        self.write("templates/User/Documents/player.ini.template", "{{PLAYER_NAME}}")
        with patch("src.installer.engine.user_profile", return_value=self.profile):
            InstallerEngine().install(self.build(), self.install, {"PLAYER_NAME": "Alice"})
        self.assertEqual((self.profile / "Documents/player.ini").read_text(), "Alice")

    def test_missing_parameters_do_not_write_files(self):
        package = self.build()
        with self.assertRaises(InstallerError):
            InstallerEngine().install(package, self.install)
        self.assertFalse(self.install.exists())

    def test_unknown_template_parameter_is_checked_before_copy(self):
        self.write("templates/config.ini.template", "{{MISSING}}")
        with patch("src.installer.engine.user_profile", return_value=self.profile):
            with self.assertRaises(InstallerError):
                InstallerEngine().install(self.build(), self.install, {"PLAYER_NAME": "Alice"})
        self.assertFalse(self.install.exists())

    def test_conflicting_destinations_are_rejected_before_copy(self):
        self.write("templates/Game.exe.template", "conflict")
        with patch("src.installer.engine.user_profile", return_value=self.profile):
            with self.assertRaises(InstallerError):
                InstallerEngine().install(self.build(), self.install, {"PLAYER_NAME": "Alice"})
        self.assertFalse(self.install.exists())

    def test_shortcut_targets_arguments_working_directory_and_icon(self):
        self.config["desktop_shortcut"] = True
        self.config["shortcut_icon"] = "src/GameXY/icon.ico"
        self.write("src/GameXY/icon.ico", "example icon")
        desktop = self.root / "desktop"
        creator = unittest.mock.Mock()
        creator.create.return_value = desktop / "GameXY.lnk"
        with patch("src.installer.engine.desktop_directory", return_value=desktop):
            with patch("src.installer.engine.user_profile", return_value=self.profile):
                result = InstallerEngine(shortcut_creator=creator).install(
                    self.build(), self.install, {"PLAYER_NAME": "Alice"})
        creator.create.assert_called_once_with(
            desktop, "GameXY", self.install / "Game.exe", "-nosteam", self.install / "icon.ico")
        self.assertEqual(result.shortcuts, [desktop / "GameXY.lnk"])

    def test_powershell_receives_values_as_data(self):
        desktop = self.root / "desktop"
        arguments = "'; Write-Output evil; #"
        environment = {"SystemRoot": str(self.root)}

        def run(command, **kwargs):
            self.assertNotIn(arguments, command[-1])
            data = json.loads(kwargs["env"]["SIMPLEINSTALLER_SHORTCUT"])
            self.assertEqual(data["arguments"], arguments)
            self.assertEqual(data["working_directory"], str(self.install))
            Path(data["path"]).write_text("shortcut")

        with patch("src.installer.shortcuts.os", SimpleNamespace(name="nt", environ=environment)):
            with patch("src.installer.shortcuts.subprocess.run", side_effect=run):
                result = ShortcutCreator().create(desktop, "GameXY", self.install / "Game.exe", arguments)
        self.assertTrue(result.is_file())

    def test_invalid_paths(self):
        for value in ("../outside", "/absolute", "C:/Windows/file", "User/../file",
                      "User/file:stream", "User/NUL.txt", "User/trailing.", "User//file"):
            with self.subTest(value=value), self.assertRaises(InstallerError):
                relative_path(value)
        self.assertEqual(relative_path(r"User\Documents\config.ini"), "User/Documents/config.ini")

    def test_destination_symlink_cannot_escape_root(self):
        self.install.mkdir()
        try:
            (self.install / "escape").symlink_to(self.profile, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is unavailable.")
        with self.assertRaises(InstallerError):
            safe_destination(self.install, "escape/config.ini")

    def test_payload_traversal_rejected(self):
        package = self.build()
        payload = self.root / "evil.zip"
        with ZipFile(payload, "w") as archive:
            archive.writestr("../outside.txt", "bad")
        with ZipFile(package.path) as archive:
            manifest = archive.read("manifest.json")
        with ZipFile(package.path, "w") as archive:
            archive.writestr("manifest.json", manifest)
            archive.write(payload, "payload.zip")
        with self.assertRaises(InstallerError):
            with InstallerPackage(package.path).extract():
                pass
        self.assertFalse((self.root / "outside.txt").exists())

    def test_duplicate_archive_names_rejected(self):
        package = self.build()
        with ZipFile(package.path, "a") as archive:
            archive.writestr("MANIFEST.JSON", "{}")
        with self.assertRaises(InstallerError):
            InstallerPackage(package.path)

    def test_manifest_link_must_be_installed_file(self):
        self.write("link.txt", "./User/Documents/config.ini;")
        with self.assertRaises(InstallerError):
            self.build()

    def test_invalid_configuration_and_link_format(self):
        for change in ({"name": "../bad"}, {"desktop_shortcut": "yes"},
                       {"required_parameters": [{"name": "invalid name"}]}):
            with self.subTest(change=change), self.assertRaises(InstallerError):
                InstallerConfig.from_dict(self.config | change)
        with self.assertRaises(InstallerError):
            parse_links("./src/GameXY/Game.exe")


if __name__ == "__main__":
    unittest.main()
