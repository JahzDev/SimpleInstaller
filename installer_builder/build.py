"""Build a reusable .installer package from a prepared project directory."""

import argparse
import logging
from pathlib import Path

from src.config.installer_schema import InstallerError
from src.installer.package import PackageBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Ordner mit installer.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "packages")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        print(PackageBuilder().build(args.project, args.output))
    except (InstallerError, OSError, UnicodeError) as exc:
        logging.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
