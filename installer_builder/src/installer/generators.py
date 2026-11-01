"""Simple text templates, deliberately without expression evaluation."""

import logging
from pathlib import Path
import re

from ..config.installer_schema import InstallerError
from .file_copy import safe_destination

LOGGER = logging.getLogger(__name__)
PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


class TemplateGenerator:
    def render(self, source: Path, parameters: dict[str, str]) -> str:
        text = source.read_text(encoding="utf-8-sig")

        def replace(match):
            name = match.group(1)
            if name not in parameters:
                raise InstallerError(f"Template-Parameter fehlt: {name}")
            return parameters[name]

        return PLACEHOLDER.sub(replace, text)

    def write(self, text: str, root: Path, relative: str) -> Path:
        target = safe_destination(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        LOGGER.info("Generiert: %s", target)
        return target
