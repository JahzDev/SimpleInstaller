"""Windows shortcuts via built-in PowerShell and WScript.Shell."""

import json
import logging
import os
from pathlib import Path
import subprocess

from ..config.installer_schema import InstallerError
from .file_copy import safe_destination

LOGGER = logging.getLogger(__name__)


def desktop_directory() -> Path:
    if os.name != "nt":
        raise InstallerError("Desktop-Verknüpfungen können nur unter Windows erstellt werden.")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
        desktop, _ = winreg.QueryValueEx(key, "Desktop")
    path = Path(os.path.expandvars(desktop))
    if not path.is_absolute():
        raise InstallerError("Windows-Desktopordner konnte nicht ermittelt werden.")
    return path.resolve()


class ShortcutCreator:
    def create(self, desktop: Path, name: str, target: Path,
               arguments: str = "", icon: Path | None = None) -> Path:
        if os.name != "nt":
            raise InstallerError("Desktop-Verknüpfungen benötigen Windows.")
        shortcut = safe_destination(desktop, f"{name}.lnk")
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        values = {"path": str(shortcut), "target": str(target), "arguments": arguments,
                  "working_directory": str(target.parent), "icon": str(icon) if icon else ""}
        # Package values are data, never interpolated into PowerShell source.
        script = """
$ErrorActionPreference = 'Stop'
$data = $env:SIMPLEINSTALLER_SHORTCUT | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($data.path)
$link.TargetPath = $data.target
$link.Arguments = $data.arguments
$link.WorkingDirectory = $data.working_directory
if ($data.icon) { $link.IconLocation = $data.icon }
$link.Save()
"""
        environment = os.environ.copy()
        environment["SIMPLEINSTALLER_SHORTCUT"] = json.dumps(values, ensure_ascii=True)
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
            "System32/WindowsPowerShell/v1.0/powershell.exe")
        try:
            subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                           env=environment, check=True, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallerError(f"Verknüpfung konnte nicht erstellt werden: {shortcut}") from exc
        if not shortcut.is_file():
            raise InstallerError(f"Windows hat keine Verknüpfung erzeugt: {shortcut}")
        LOGGER.info("Verknüpfung erstellt: %s", shortcut)
        return shortcut
