"""JSON schema validation shared by the builder and installer."""

from dataclasses import dataclass
from pathlib import PureWindowsPath
import re


class InstallerError(Exception):
    """An actionable package or installation error."""


def relative_path(value: str) -> str:
    """Accept only portable relative paths, including on non-Windows builders."""
    if not isinstance(value, str) or not value:
        raise InstallerError("Ein relativer Dateipfad darf nicht leer sein.")
    value = value.replace("\\", "/")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10))
    if PureWindowsPath(value).drive or value.startswith("/"):
        raise InstallerError(f"Absoluter Paketpfad ist nicht erlaubt: {value}")
    for part in parts:
        if (part in ("", ".", "..") or part.endswith((" ", "."))
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or part.split(".")[0].upper() in reserved):
            raise InstallerError(f"Ungültiger Paketpfad: {value}")
    return "/".join(parts)


@dataclass(frozen=True)
class Parameter:
    name: str
    description: str


@dataclass(frozen=True)
class InstallerConfig:
    name: str
    version: str
    publisher: str
    default_install_path: str
    desktop_shortcut: bool
    required_parameters: tuple[Parameter, ...]
    shortcut_icon: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "InstallerConfig":
        if not isinstance(data, dict):
            raise InstallerError("Die Installer-Konfiguration muss ein JSON-Objekt sein.")
        values = {}
        for key in ("name", "version", "publisher", "default_install_path"):
            value = data.get(key, "" if key == "publisher" else None)
            if not isinstance(value, str) or (key != "publisher" and not value.strip()):
                raise InstallerError(f"Konfiguration: '{key}' muss eine Zeichenkette sein.")
            if "\x00" in value:
                raise InstallerError(f"Konfiguration: ungültiger Wert für '{key}'.")
            values[key] = value
        for key in ("name", "version"):
            if "/" in relative_path(values[key]):
                raise InstallerError(f"Konfiguration: '{key}' darf keinen Pfad enthalten.")
        shortcut = data.get("desktop_shortcut", True)
        if not isinstance(shortcut, bool):
            raise InstallerError("'desktop_shortcut' muss true oder false sein.")
        raw_parameters = data.get("required_parameters", [])
        if not isinstance(raw_parameters, list):
            raise InstallerError("'required_parameters' muss eine Liste sein.")
        parameters = []
        names = set()
        for item in raw_parameters:
            if not isinstance(item, dict):
                raise InstallerError("Ungültiger Parameter.")
            name = item.get("name")
            description = item.get("description", name)
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
                    or name in names or not isinstance(description, str)):
                raise InstallerError("Parameternamen müssen eindeutig sein, z. B. PLAYER_NAME.")
            names.add(name)
            parameters.append(Parameter(name, description))
        icon = data.get("shortcut_icon")
        if icon is not None:
            icon = relative_path(icon.removeprefix("./")) if isinstance(icon, str) else relative_path(icon)
        return cls(**values, desktop_shortcut=shortcut,
                   required_parameters=tuple(parameters), shortcut_icon=icon)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "version": self.version, "publisher": self.publisher,
            "default_install_path": self.default_install_path,
            "desktop_shortcut": self.desktop_shortcut,
            "required_parameters": [
                {"name": p.name, "description": p.description} for p in self.required_parameters
            ],
            "shortcut_icon": self.shortcut_icon,
        }
