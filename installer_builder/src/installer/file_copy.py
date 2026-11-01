"""Destination mapping and file copying."""

import logging
import os
from pathlib import Path
import shutil

from ..config.installer_schema import InstallerError, relative_path

LOGGER = logging.getLogger(__name__)


def user_profile() -> Path:
    profile = os.environ.get("USERPROFILE") if os.name == "nt" else str(Path.home())
    if not profile or not Path(profile).is_absolute() or not Path(profile).is_dir():
        raise InstallerError("Benutzerprofil konnte nicht ermittelt werden.")
    return Path(profile).resolve()


def safe_destination(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = root.joinpath(*relative_path(relative).split("/"))
    # Resolving also catches existing junctions/symlinks that escape the root.
    if not target.resolve().is_relative_to(root):
        raise InstallerError(f"Zielpfad verlässt den erlaubten Ordner: {target}")
    return target


class FileCopier:
    def copy(self, source: Path, root: Path, relative: str) -> Path:
        target = safe_destination(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        LOGGER.info("Kopiert: %s -> %s", source, target)
        return target
