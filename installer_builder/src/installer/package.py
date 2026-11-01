"""Versioned ZIP packages; archive paths are checked before extraction."""

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import shutil
import stat
import tempfile
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from ..config.installer_schema import InstallerConfig, InstallerError, relative_path

LOGGER = logging.getLogger(__name__)
MAX_BYTES = 1024 * 1024 * 1024
MAX_FILES = 10000
MAX_JSON_BYTES = 1024 * 1024


def read_json(raw: bytes) -> dict:
    if len(raw) > MAX_JSON_BYTES:
        raise InstallerError("JSON-Datei ist zu groß.")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise InstallerError(f"Ungültige JSON-Datei: {exc}") from exc


def checked_members(archive: ZipFile) -> list:
    members = archive.infolist()
    if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_BYTES:
        raise InstallerError("Paket überschreitet das Limit von 1 GiB oder 10000 Einträgen.")
    names = set()
    for member in members:
        name = relative_path(member.filename.rstrip("/") if member.is_dir() else member.filename)
        if name.casefold() in names:
            raise InstallerError(f"Doppelter Paketpfad: {name}")
        names.add(name.casefold())
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise InstallerError(f"Symbolische Links sind nicht erlaubt: {name}")
    return members


def parse_links(text: str) -> list[dict]:
    links = []
    for line in text.splitlines():
        if not line.strip():
            continue
        executable, separator, arguments = line.partition(";")
        if not separator:
            raise InstallerError("link.txt erwartet relative_exe;argumente.")
        links.append({"target": relative_path(executable.strip().removeprefix("./")),
                      "arguments": arguments.strip()})
    return links


class PackageBuilder:
    def build(self, project: Path, output_dir: Path) -> Path:
        project = project.resolve()
        config = InstallerConfig.from_dict(read_json((project / "installer.json").read_bytes()))
        files = []
        for folder in ("src", "User", "templates"):
            root = project / folder
            if root.is_symlink():
                raise InstallerError(f"Symbolischer Quellordner ist nicht erlaubt: {root}")
            if root.exists() and not root.is_dir():
                raise InstallerError(f"Quellordner erwartet: {root}")
            if root.exists():
                for path in sorted(root.rglob("*")):
                    if path.is_symlink():
                        raise InstallerError(f"Symbolische Links sind nicht erlaubt: {path}")
                    if path.is_file():
                        relative_path(path.relative_to(project).as_posix())
                        files.append(path)
        if not files:
            raise InstallerError("Das Projekt enthält keine Installationsdateien.")
        if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_BYTES:
            raise InstallerError("Quelldaten überschreiten die Paketlimits.")
        src = project / "src"
        children = list(src.iterdir()) if src.is_dir() else []
        source_root = f"src/{children[0].name}" if len(children) == 1 and children[0].is_dir() else "src"
        links_file = project / "link.txt"
        links = parse_links(links_file.read_text(encoding="utf-8-sig")) if links_file.exists() else []
        available = {p.relative_to(project).as_posix() for p in files}
        for path in [link["target"] for link in links] + ([config.shortcut_icon] if config.shortcut_icon else []):
            if path not in available or not path.startswith(source_root + "/"):
                raise InstallerError(f"Verknüpfungsziel muss eine Datei unter {source_root}/ sein: {path}")
        manifest = {"format_version": 1, "config": config.to_dict(),
                    "source_root": source_root, "shortcuts": links}
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{config.name}-{config.version}.installer"
        # Build beside the destination, then replace atomically on success.
        with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
            payload = Path(temporary) / "payload.zip"
            with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
                for path in files:
                    archive.write(path, path.relative_to(project).as_posix())
            result = Path(temporary) / "package.installer"
            with ZipFile(result, "w", ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                archive.write(payload, "payload.zip", compress_type=0)
            # Use the same validation as the installer before publishing.
            with InstallerPackage(result).extract():
                pass
            result.replace(output)
        LOGGER.info("Paket erstellt: %s", output)
        return output


class InstallerPackage:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        try:
            with ZipFile(self.path) as archive:
                members = checked_members(archive)
                names = {m.filename for m in members}
                if not {"manifest.json", "payload.zip"} <= names:
                    raise InstallerError("manifest.json oder payload.zip fehlt.")
                if archive.getinfo("manifest.json").file_size > MAX_JSON_BYTES:
                    raise InstallerError("Manifest ist zu groß.")
                self._manifest_bytes = archive.read("manifest.json")
                manifest = read_json(self._manifest_bytes)
            if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
                raise InstallerError("Nicht unterstütztes Paketformat.")
            self.config = InstallerConfig.from_dict(manifest.get("config"))
            self.source_root = relative_path(manifest.get("source_root", "src"))
            if self.source_root != "src" and not (
                    self.source_root.startswith("src/") and self.source_root.count("/") == 1):
                raise InstallerError("Ungültiger src-Wurzelordner.")
            raw_links = manifest.get("shortcuts", [])
            if not isinstance(raw_links, list):
                raise InstallerError("Ungültige Verknüpfungsliste.")
            self.shortcuts = []
            for link in raw_links:
                if not isinstance(link, dict) or not isinstance(link.get("arguments", ""), str):
                    raise InstallerError("Ungültige Verknüpfung.")
                target = relative_path(link.get("target"))
                if not target.startswith(self.source_root + "/"):
                    raise InstallerError("Verknüpfungsziel liegt nicht im src-Ordner.")
                self.shortcuts.append({"target": target, "arguments": link.get("arguments", "")})
            if self.config.shortcut_icon and not self.config.shortcut_icon.startswith(self.source_root + "/"):
                raise InstallerError("Icon liegt nicht im src-Ordner.")
        except (OSError, BadZipFile, KeyError, RuntimeError) as exc:
            raise InstallerError(f"Paket kann nicht geladen werden: {exc}") from exc

    @contextmanager
    def extract(self):
        try:
            with tempfile.TemporaryDirectory(prefix="simpleinstaller-") as temporary:
                root = Path(temporary)
                payload = root / "payload.zip"
                with ZipFile(self.path) as archive:
                    checked_members(archive)
                    if archive.getinfo("manifest.json").file_size > MAX_JSON_BYTES:
                        raise InstallerError("Manifest ist zu groß.")
                    if archive.read("manifest.json") != self._manifest_bytes:
                        raise InstallerError("Das Paket wurde geändert. Bitte erneut laden.")
                    with archive.open("payload.zip") as source, payload.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                data = root / "data"
                data.mkdir()
                with ZipFile(payload) as archive:
                    members = checked_members(archive)
                    for member in members:
                        parts = member.filename.split("/")
                        if parts[0] not in {"src", "User", "templates"}:
                            raise InstallerError(f"Unbekannter Payload-Ordner: {member.filename}")
                        if parts[0] == "src" and not member.is_dir() and not member.filename.startswith(self.source_root + "/"):
                            raise InstallerError(f"Datei außerhalb des src-Wurzelordners: {member.filename}")
                        target = data.joinpath(*parts)
                        if member.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(member) as source, target.open("wb") as destination:
                                shutil.copyfileobj(source, destination)
                for link in self.shortcuts:
                    if not (data / link["target"]).is_file():
                        raise InstallerError(f"Verknüpfungsziel fehlt: {link['target']}")
                if self.config.shortcut_icon and not (data / self.config.shortcut_icon).is_file():
                    raise InstallerError("Verknüpfungsicon fehlt.")
                yield data
        except (OSError, BadZipFile, KeyError, RuntimeError) as exc:
            raise InstallerError(f"Paketdaten können nicht verarbeitet werden: {exc}") from exc
