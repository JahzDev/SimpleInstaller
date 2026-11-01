"""Installation orchestration. GUI integration uses only a progress callback."""

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Callable

from ..config.installer_schema import InstallerError
from .file_copy import FileCopier, safe_destination, user_profile
from .generators import TemplateGenerator
from .package import InstallerPackage
from .shortcuts import ShortcutCreator, desktop_directory

LOGGER = logging.getLogger(__name__)


@dataclass
class InstallationResult:
    files: list[Path] = field(default_factory=list)
    shortcuts: list[Path] = field(default_factory=list)


class InstallerEngine:
    def __init__(self, copier: FileCopier | None = None,
                 generator: TemplateGenerator | None = None,
                 shortcut_creator: ShortcutCreator | None = None):
        self.copier = copier or FileCopier()
        self.generator = generator or TemplateGenerator()
        self.shortcut_creator = shortcut_creator or ShortcutCreator()

    def install(self, package: InstallerPackage, install_path: Path,
                parameters: dict[str, str] | None = None,
                progress: Callable[[int, str], None] | None = None) -> InstallationResult:
        parameters = parameters or {}
        progress = progress or (lambda percent, message: None)
        install_path = Path(install_path)
        if not install_path.is_absolute():
            raise InstallerError("Der Installationspfad muss absolut sein.")
        install_path = install_path.resolve()
        for parameter in package.config.required_parameters:
            value = parameters.get(parameter.name)
            if not isinstance(value, str) or not value.strip():
                raise InstallerError(f"Bitte '{parameter.description}' angeben.")
        if any(not isinstance(v, str) for v in parameters.values()):
            raise InstallerError("Template-Parameter müssen Zeichenketten sein.")
        result = InstallationResult()
        try:
            progress(0, "Paketdaten prüfen …")
            with package.extract() as data:
                profile = user_profile() if (data / "User").exists() or (data / "templates/User").exists() else None
                desktop = desktop_directory() if package.config.desktop_shortcut and package.shortcuts else None
                copies = []
                templates = []
                destinations = set()

                def register(root, relative):
                    target = safe_destination(root, relative)
                    key = str(target.resolve()).casefold()
                    if key in destinations:
                        raise InstallerError(f"Mehrere Paketdateien haben dasselbe Ziel: {target}")
                    destinations.add(key)
                    return target

                for prefix, root in ((package.source_root, install_path), ("User", profile)):
                    source_root = data / prefix
                    if not source_root.exists():
                        continue
                    for source in sorted(source_root.rglob("*")):
                        if source.is_file():
                            relative = source.relative_to(source_root).as_posix()
                            register(root, relative)
                            copies.append((source, root, relative))
                template_root = data / "templates"
                if template_root.exists():
                    for source in sorted(template_root.rglob("*")):
                        if not source.is_file():
                            continue
                        relative = source.relative_to(template_root).as_posix()
                        if not relative.endswith(".template"):
                            raise InstallerError(f"Template benötigt die Endung .template: {relative}")
                        relative = relative.removesuffix(".template")
                        root = install_path
                        if relative.startswith("User/"):
                            root, relative = profile, relative.removeprefix("User/")
                        register(root, relative)
                        templates.append((self.generator.render(source, parameters), root, relative))
                links = package.shortcuts if desktop is not None else []
                icon = None
                if package.config.shortcut_icon:
                    icon = safe_destination(install_path, package.config.shortcut_icon[len(package.source_root) + 1:])
                planned_links = []
                for index, link in enumerate(links, 1):
                    name = package.config.name if len(links) == 1 else f"{package.config.name}-{index}"
                    register(desktop, f"{name}.lnk")
                    target = safe_destination(install_path, link["target"][len(package.source_root) + 1:])
                    planned_links.append((name, target, link["arguments"]))
                total = len(copies) + len(templates) + len(planned_links)
                if not total:
                    raise InstallerError("Das Paket enthält keine installierbaren Dateien.")
                completed = 0

                def update(message):
                    nonlocal completed
                    completed += 1
                    progress(int(completed * 100 / total), message)

                for source, root, relative in copies:
                    progress(int(completed * 100 / total), f"Kopiere: {safe_destination(root, relative)}")
                    result.files.append(self.copier.copy(source, root, relative))
                    update(f"Kopiert: {result.files[-1]}")
                for text, root, relative in templates:
                    result.files.append(self.generator.write(text, root, relative))
                    update(f"Generiert: {result.files[-1]}")
                for name, target, arguments in planned_links:
                    result.shortcuts.append(self.shortcut_creator.create(desktop, name, target, arguments, icon))
                    update(f"Verknüpfung: {result.shortcuts[-1]}")
            LOGGER.info("Installation abgeschlossen: %s", package.config.name)
            return result
        except (OSError, UnicodeError) as exc:
            raise InstallerError(f"Installation fehlgeschlagen: {exc}") from exc
